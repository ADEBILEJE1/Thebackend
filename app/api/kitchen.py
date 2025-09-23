from fastapi import APIRouter, HTTPException, status, Depends, Request
from typing import List, Optional, Any, Dict
from datetime import datetime, date, timedelta
from decimal import Decimal
from pydantic import BaseModel, Field, validator, EmailStr

from ..models.order import OrderType, OrderStatus, PaymentStatus
from ..models.user import UserRole
from ..core.permissions import (
    get_current_user,
    require_super_admin,
    require_manager_up,
    require_staff,
    require_inventory_staff,
    require_sales_staff,
    require_chef_staff
)
from ..core.cache import invalidate_order_cache, CacheKeys
from ..services.redis import redis_client
from ..database import supabase, supabase_admin
from .websocket import notify_order_update
from ..services.celery import send_order_ready_notification
from ..core.activity_logger import log_activity
from ..models.order import OrderType, OrderStatus, PaymentStatus, PaymentMethod
from ..models.inventory import StockStatus



class OrderItemCreate(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)
    notes: Optional[str] = None

class OnlineOrderCreate(BaseModel):
    customer_name: str
    customer_email: EmailStr
    customer_phone: str
    items: List[OrderItemCreate]



class OfflineOrderCreate(BaseModel):
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    payment_method: PaymentMethod  # Required field
    items: List[OrderItemCreate]

class OrderStatusUpdate(BaseModel):
    status: OrderStatus

class ChefOrderReady(BaseModel):
    order_number: str

class OrderResponse(BaseModel):
    id: str
    order_number: str
    order_type: str
    status: str
    payment_status: str
    customer_name: Optional[str]
    customer_email: Optional[str]
    customer_phone: Optional[str]
    items: List[dict]
    subtotal: float
    tax: float
    total: float
    created_at: datetime


router = APIRouter(prefix="/orders", tags=["Orders"])

def generate_order_number() -> str:
    """Generate unique order number: ORD-20250828-001"""
    today = date.today().strftime("%Y%m%d")

    # Get today's order count
    start_of_day = datetime.combine(date.today(), datetime.min.time())
    result = supabase.table("orders").select("id").gte("created_at", start_of_day.isoformat()).execute()

    count = len(result.data) + 1
    return f"ORD-{today}-{count:03d}"

# Corrected function to return a dict as intended, with the correct type hint
def calculate_order_total(items: List[dict]) -> dict:
    """Helper function to calculate order total, taxes, and subtotal."""
    subtotal = sum(Decimal(str(item["quantity"])) * Decimal(str(item["price"])) for item in items)
    tax = subtotal * Decimal("0.08")
    total = subtotal + tax
    return {"subtotal": subtotal, "tax": tax, "total": total}

async def check_product_availability(items: List[dict]) -> List[dict]:
    """Check if products are available and have sufficient stock"""
    processed_items = []

    for item in items:
        # Get product details
        product = supabase.table("products").select("*").eq("id", item["product_id"]).execute()

        if not product.data:
            raise HTTPException(status_code=404, detail=f"Product {item['product_id']} not found")

        product_data = product.data[0]

        if not product_data["is_available"]:
            raise HTTPException(
                status_code=400,
                detail=f"{product_data['name']} is not available"
            )

        if product_data["units"] < item["quantity"]:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient stock for {product_data['name']}. Available: {product_data['units']}"
            )

        processed_items.append({
            "product_id": item["product_id"],
            "product_name": product_data["name"],
            "quantity": item["quantity"],
            "unit_price": product_data["price"],
            "total_price": Decimal(str(product_data["price"])) * item["quantity"],
            "notes": item.get("notes")
        })

    return processed_items

async def deduct_stock(items: List[dict]):
    """Deduct stock after order confirmation"""
    from ..services.celery import send_low_stock_alert

    low_stock_products = []

    for item in items:
        # Get current stock
        product = supabase.table("products").select("*").eq("id", item["product_id"]).execute()
        product_data = product.data[0]
        current_units = product_data["units"]

        # Update stock
        new_units = current_units - item["quantity"]
        new_status = "out_of_stock" if new_units == 0 else ("low_stock" if new_units <= product_data["low_stock_threshold"] else "in_stock")

        supabase.table("products").update({
            "units": new_units,
            "status": new_status,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", item["product_id"]).execute()

        # Track low stock items
        if new_status in ["low_stock", "out_of_stock"]:
            low_stock_products.append({
                "name": product_data["name"],
                "units": new_units,
                "threshold": product_data["low_stock_threshold"]
            })

    # Send low stock alert if needed
    if low_stock_products:
        send_low_stock_alert.delay(low_stock_products)

# Kitchen Queue Management
@router.get("/queue/kitchen")
async def get_kitchen_queue(
    request: Request,
    current_user: dict = Depends(require_chef_staff)
):
    """Get orders for kitchen display"""
    cache_key = "orders:queue:kitchen"
    cached = redis_client.get(cache_key)
    if cached:
        return cached

    # Only get preparing orders (confirmed orders stay with sales)
    preparing = supabase_admin.table("orders").select("*, order_items(*)").eq("status", "preparing").order("preparing_at").execute()

    queue_data = {
        "preparing": preparing.data,
        "queue_length": len(preparing.data)
    }

    redis_client.set(cache_key, queue_data, 10)
    return queue_data



# @router.get("/queue/kitchen-batches")
# async def get_kitchen_batch_queue(current_user: dict = Depends(require_chef_staff)):
#     """Get orders grouped by batches"""
#     result = supabase_admin.table("orders").select("*, order_items(*)").eq("status", "preparing").not_.is_("batch_id", "null").order("preparing_at").execute()
    
#     # Group by batch_id
#     batches = {}
#     for order in result.data:
#         batch_id = order["batch_id"]
#         if batch_id not in batches:
#             batches[batch_id] = {
#                 "batch_id": batch_id,
#                 "customer_name": order.get("customer_name"),
#                 "orders": [],
#                 "total_items": 0
#             }
        
#         batches[batch_id]["orders"].append(order)
#         batches[batch_id]["total_items"] += len(order["order_items"])
    
#     return {"batches": list(batches.values())}


@router.get("/queue/kitchen-batches")
async def get_kitchen_batch_queue(current_user: dict = Depends(require_chef_staff)):
    """Get orders grouped by batches"""
    result = supabase_admin.table("orders").select("*, order_items(*)").not_.is_("batch_id", "null").order("preparing_at").execute()
    
    # Group by batch_id
    batches = {}
    for order in result.data:
        batch_id = order["batch_id"]
        if batch_id not in batches:
            batches[batch_id] = {
                "batch_id": batch_id,
                "customer_name": order.get("customer_name"),
                "orders": [],
                "total_items": 0,
                "preparing_at": order["preparing_at"]
            }
        
        batches[batch_id]["orders"].append(order)
        batches[batch_id]["total_items"] += len(order["order_items"])
    
    return {"batches": list(batches.values())}



@router.post("/chef/batch-ready")
async def mark_batch_ready(
    batch_id: str,
    current_user: dict = Depends(require_chef_staff)
):
    """Mark entire batch as completed"""
    orders = supabase_admin.table("orders").select("*").eq("batch_id", batch_id).eq("status", "preparing").execute()
    
    if not orders.data:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    order_ids = [o["id"] for o in orders.data]
    
    # Mark all orders as completed
    supabase_admin.table("orders").update({
        "status": "completed",
        "completed_at": datetime.utcnow().isoformat()
    }).in_("id", order_ids).execute()
    
    return {"message": f"Batch {batch_id} marked as ready"}


@router.get("/", response_model=List[dict])
async def get_orders(
    status: Optional[OrderStatus] = None,
    order_type: Optional[OrderType] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    query = supabase_admin.table("orders").select("*, order_items(*)")

    if status:
        query = query.eq("status", status)
    if order_type:
        query = query.eq("order_type", order_type)
    if date_from:
        query = query.gte("created_at", date_from.isoformat())
    if date_to:
        query = query.lte("created_at", date_to.isoformat())

    # Sales can only see confirmed+ orders
    if current_user["role"] == UserRole.SALES:
        query = query.in_("status", ["confirmed", "preparing", "ready", "completed"])

    result = query.order("created_at", desc=True).execute()
    return result.data

@router.get("/{order_id}")
async def get_order(
    order_id: str,
    current_user: dict = Depends(get_current_user)
):
    # Check cache first
    cache_key = CacheKeys.ORDER_DETAIL.format(order_id=order_id)
    cached = redis_client.get(cache_key)
    if cached:
        return cached

    result = supabase_admin.table("orders").select("*, order_items(*)").eq("id", order_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Order not found")

    # Cache for 30 seconds
    redis_client.set(cache_key, result.data[0], 30)

    return result.data[0]

@router.patch("/{order_id}/status")
async def update_order_status(
    order_id: str,
    status_update: OrderStatusUpdate,
    current_user: dict = Depends(require_sales_staff)
):
    # Get current order
    order = supabase_admin.table("orders").select("*").eq("id", order_id).execute()
    if not order.data:
        raise HTTPException(status_code=404, detail="Order not found")

    current_status = order.data[0]["status"]
    new_status = status_update.status

    # Validate status transition
    valid_transitions = {
        OrderStatus.PENDING: [OrderStatus.CONFIRMED, OrderStatus.CANCELLED],
        OrderStatus.CONFIRMED: [OrderStatus.PREPARING, OrderStatus.CANCELLED],
        OrderStatus.PREPARING: [OrderStatus.READY],
        OrderStatus.READY: [OrderStatus.COMPLETED],
    }

    if new_status not in valid_transitions.get(current_status, []):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot change status from {current_status} to {new_status}"
        )

    # Update status with timestamp
    update_data = {"status": new_status, "updated_at": datetime.utcnow().isoformat()}

    if new_status == OrderStatus.CONFIRMED:
        update_data["confirmed_at"] = datetime.utcnow().isoformat()
        # Deduct stock for online orders
        if order.data[0]["order_type"] == OrderType.ONLINE:
            items = supabase.table("order_items").select("*").eq("order_id", order_id).execute()
            await deduct_stock(items.data)
    elif new_status == OrderStatus.PREPARING:
        update_data["preparing_at"] = datetime.utcnow().isoformat()
    elif new_status == OrderStatus.READY:
        update_data["ready_at"] = datetime.utcnow().isoformat()
        # Send notification to customer if online order
        if order.data[0]["order_type"] == OrderType.ONLINE and order.data[0].get("customer_email"):
            send_order_ready_notification.delay(
                order.data[0]["order_number"],
                order.data[0]["customer_email"]
            )
    elif new_status == OrderStatus.COMPLETED:
        update_data["completed_at"] = datetime.utcnow().isoformat()
    elif new_status == OrderStatus.CANCELLED:
        update_data["cancelled_at"] = datetime.utcnow().isoformat()

    supabase.table("orders").update(update_data).eq("id", order_id).execute()

    # Invalidate cache
    invalidate_order_cache(order_id)

    # Notify via WebSocket
    await notify_order_update(order_id, "status_update", {"status": new_status})

    return {"message": f"Order status updated to {new_status}"}

@router.post("/chef/ready")
async def mark_order_ready(
   ready: ChefOrderReady,
   request: Request,
   current_user: dict = Depends(require_chef_staff)
):
   """Mark order as completed (ready for delivery)"""
   order = supabase_admin.table("orders").select("*, order_items(*)").eq("order_number", ready.order_number).execute()

   if not order.data:
       raise HTTPException(status_code=404, detail="Order not found")

   if order.data[0]["status"] != "preparing":
       raise HTTPException(
           status_code=400,
           detail=f"Order is not in preparing status. Current status: {order.data[0]['status']}"
       )

   # Update to completed (not ready)
   update_data = {
       "status": "completed",
       "completed_at": datetime.utcnow().isoformat(),
       "updated_at": datetime.utcnow().isoformat()
   }

   supabase.table("orders").update(update_data).eq("id", order.data[0]["id"]).execute()

   # Send notification if online order
   if order.data[0]["order_type"] == "online" and order.data[0].get("customer_email"):
       send_order_ready_notification.delay(
           order.data[0]["order_number"],
           order.data[0]["customer_email"]
       )

   invalidate_order_cache(order.data[0]["id"])

   await notify_order_update(order.data[0]["id"], "order_completed", {"order_number": ready.order_number})

   # Enhanced logging for chef analytics
   await log_activity(
       current_user["id"], current_user["email"], current_user["role"],
       "order_completed", "order", order.data[0]["id"],
       {
           "order_number": ready.order_number,
           "order_total": order.data[0]["total"],
           "items_count": len(order.data[0]["order_items"]),
           "order_type": order.data[0]["order_type"]
       },
       request
   )

   return {"message": "Order completed and ready for delivery", "order_number": ready.order_number}

@router.get("/stats/today")
async def get_today_stats(
    request: Request,
    current_user: dict = Depends(require_manager_up)
):
    # Check cache
    cache_key = CacheKeys.TODAYS_ORDERS
    cached = redis_client.get(cache_key)
    if cached:
        return cached

    start_of_day = datetime.combine(date.today(), datetime.min.time())

    # Get today's orders
    orders = supabase_admin.table("orders").select("status, total, order_type").gte("created_at", start_of_day.isoformat()).execute()

    stats = {
        "total_orders": len(orders.data),
        "pending": len([o for o in orders.data if o["status"] == OrderStatus.PENDING]),
        "preparing": len([o for o in orders.data if o["status"] == OrderStatus.PREPARING]),
        "completed": len([o for o in orders.data if o["status"] == OrderStatus.COMPLETED]),
        "total_revenue": sum(float(o["total"]) for o in orders.data if o["status"] != OrderStatus.CANCELLED),
        "online_orders": len([o for o in orders.data if o["order_type"] == OrderType.ONLINE]),
        "offline_orders": len([o for o in orders.data if o["order_type"] == OrderType.OFFLINE]),
        "timestamp": datetime.utcnow().isoformat()
    }

    # Cache for 30 seconds
    redis_client.set(cache_key, stats, 30)

    return stats


@router.get("/{order_id}/print")
async def print_order_receipt(
    order_id: str,
    request: Request,
    current_user: dict = Depends(require_chef_staff)
):
    """Generate printable order receipt for kitchen"""
    # Get order with items
    order_result = supabase_admin.table("orders").select("*, order_items(*)").eq("id", order_id).execute()
    
    if not order_result.data:
        raise HTTPException(status_code=404, detail="Order not found")
    
    order = order_result.data[0]
    
    # Generate print-friendly format
    receipt_data = {
        "order_number": order["order_number"],
        "order_type": order["order_type"],
        "customer_name": order.get("customer_name", "Walk-in Customer"),
        "created_at": order["created_at"],
        "status": order["status"],
        "items": [
            {
                "name": item["product_name"],
                "quantity": item["quantity"],
                "notes": item.get("notes", "")
            }
            for item in order["order_items"]
        ],
        "total_items": sum(item["quantity"] for item in order["order_items"]),
        "special_instructions": order.get("notes", "")
    }
    
    # Log activity
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "print", "order", order_id, {"order_number": order["order_number"]}, 
        request
    )
    
    return receipt_data






# @router.post("/online", response_model=dict)
# async def create_online_order(order: OnlineOrderCreate, request: Request):
#     # Validate and process items
#     processed_items = await check_product_availability([item.dict() for item in order.items])

#     # Correctly call the function and use the dictionary return value
#     totals = calculate_order_total(processed_items)

#     # Create order
#     order_data = {
#         "order_number": generate_order_number(),
#         "order_type": OrderType.ONLINE,
#         "status": OrderStatus.PENDING,
#         "payment_status": PaymentStatus.PENDING,
#         "customer_name": order.customer_name,
#         "customer_email": order.customer_email,
#         "customer_phone": order.customer_phone,
#         "subtotal": float(totals["subtotal"]),
#         "tax": float(totals["tax"]),
#         "total": float(totals["total"])
#     }

#     created_order = supabase.table("orders").insert(order_data).execute()
#     order_id = created_order.data[0]["id"]

#     # Create order items
#     for item in processed_items:
#         item["order_id"] = order_id
#         item["unit_price"] = float(item["unit_price"])
#         item["total_price"] = float(item["total_price"])
#         supabase.table("order_items").insert(item).execute()

#     # Add to pending queue in Redis
#     redis_client.lpush("orders:queue:pending", {
#         "order_id": order_id,
#         "order_number": order_data["order_number"],
#         "timestamp": datetime.utcnow().isoformat()
#     })

#     # Invalidate cache
#     invalidate_order_cache()

#     # Notify via WebSocket
#     await notify_order_update(order_id, "new_order", order_data)

#     return {
#         "message": "Order placed successfully",
#         "order_number": order_data["order_number"],
#         "total": float(totals["total"])
#     }

# @router.post("/offline", response_model=dict)
# async def create_offline_order(
#     order: OfflineOrderCreate,
#     request: Request,
#     current_user: dict = Depends(require_sales_staff) 
# ):
    
#     processed_items = await check_product_availability([item.dict() for item in order.items])
#     totals = calculate_order_total(processed_items)

#     # Create order with payment method
#     order_data = {
#         "order_number": generate_order_number(),
#         "order_type": OrderType.OFFLINE,
#         "status": OrderStatus.PREPARING,
#         "payment_status": PaymentStatus.PAID,
#         "payment_method": order.payment_method,  
#         "customer_name": order.customer_name,
#         "customer_phone": order.customer_phone,
#         "subtotal": float(totals["subtotal"]),
#         "tax": float(totals["tax"]),
#         "preparing_at": datetime.utcnow().isoformat(),
#         "total": float(totals["total"]),
#         "created_by": current_user["id"],
#         "confirmed_at": datetime.utcnow().isoformat()
#     }

#     created_order = supabase.table("orders").insert(order_data).execute()
#     order_id = created_order.data[0]["id"]

#     # Create order items
#     for item in processed_items:
#         item["order_id"] = order_id
#         item["unit_price"] = float(item["unit_price"])
#         item["total_price"] = float(item["total_price"])
#         supabase.table("order_items").insert(item).execute()

#     # Deduct stock immediately for offline orders
#     await deduct_stock(processed_items)

#     # Invalidate cache
#     invalidate_order_cache()

#     # Notify kitchen via WebSocket
#     await notify_order_update(order_id, "new_order", order_data)

#     return {
#         "message": "Order created successfully",
#         "order_number": order_data["order_number"],
#         "total": float(totals["total"])
#     }


# @router.get("/products-for-sale", response_model=List[dict])
# async def get_products_for_sale(
#     request: Request,
#     category_id: Optional[str] = None,
#     current_user: dict = Depends(require_sales_staff)
# ):
#     """Get products organized for sales staff during order creation"""
#     # Check cache
#     cache_key = f"sales:products:{category_id}"
#     cached = redis_client.get(cache_key)
#     if cached:
#         return cached
    
#     # Get products with all necessary info for sales
#     query = supabase.table("products").select("""
#         id, sku, variant_name, price, description, image_url, units, status, is_available,
#         product_templates(name),
#         categories(id, name),
#         suppliers(name)
#     """)
    
#     if category_id:
#         query = query.eq("category_id", category_id)
    
#     result = query.order("categories(name), product_templates(name)").execute()
    
#     # Format for sales interface
#     sales_products = []
#     for product in result.data:
#         # Determine availability status
#         availability_status = "available"
#         if not product["is_available"]:
#             availability_status = "disabled"
#         elif product["status"] == StockStatus.OUT_OF_STOCK:
#             availability_status = "out_of_stock"
#         elif product["status"] == StockStatus.LOW_STOCK:
#             availability_status = "low_stock"
        
#         # Create display name
#         display_name = product["product_templates"]["name"]
#         if product["variant_name"]:
#             display_name += f" - {product['variant_name']}"
        
#         sales_products.append({
#             "id": product["id"],
#             "display_name": display_name,
#             "sku": product["sku"],
#             "price": float(product["price"]),
#             "description": product["description"],
#             "image_url": product["image_url"],
#             "current_stock": product["units"],
#             "availability_status": availability_status,
#             "can_order": product["is_available"] and product["status"] != StockStatus.OUT_OF_STOCK,
#             "category": {
#                 "id": product["categories"]["id"],
#                 "name": product["categories"]["name"]
#             },
#             "supplier": product["suppliers"]["name"] if product["suppliers"] else None
#         })
    
#     # Cache for 30 seconds
#     redis_client.set(cache_key, sales_products, 30)
    
#     return sales_products


# @router.get("/products-by-category", response_model=List[dict])
# async def get_products_by_category(
#     request: Request,
#     current_user: dict = Depends(require_sales_staff)
# ):
#     """Get products organized by categories for order creation interface"""
#     cache_key = "sales:products:by_category"
#     cached = redis_client.get(cache_key)
#     if cached:
#         return cached
    
#     # Get all active categories
#     categories_result = supabase.table("categories").select("*").eq("is_active", True).order("name").execute()
    
#     organized_data = []
    
#     for category in categories_result.data:
#         # Get products in this category
#         products_result = supabase.table("products").select("""
#             id, sku, variant_name, price, description, image_url, units, status, is_available,
#             product_templates(name),
#             suppliers(name)
#         """).eq("category_id", category["id"]).order("product_templates(name)").execute()
        
#         # Format products
#         category_products = []
#         for product in products_result.data:
#             availability_status = "available"
#             if not product["is_available"]:
#                 availability_status = "disabled"
#             elif product["status"] == StockStatus.OUT_OF_STOCK:
#                 availability_status = "out_of_stock"
#             elif product["status"] == StockStatus.LOW_STOCK:
#                 availability_status = "low_stock"
            
#             display_name = product["product_templates"]["name"]
#             if product["variant_name"]:
#                 display_name += f" - {product['variant_name']}"
            
#             category_products.append({
#                 "id": product["id"],
#                 "display_name": display_name,
#                 "sku": product["sku"],
#                 "price": float(product["price"]),
#                 "description": product["description"],
#                 "image_url": product["image_url"],
#                 "current_stock": product["units"],
#                 "availability_status": availability_status,
#                 "can_order": product["is_available"] and product["status"] != StockStatus.OUT_OF_STOCK,
#                 "supplier": product["suppliers"]["name"] if product["suppliers"] else None
#             })
        
#         organized_data.append({
#             "category": {
#                 "id": category["id"],
#                 "name": category["name"],
#                 "description": category["description"]
#             },
#             "products": category_products,
#             "product_count": len(category_products),
#             "available_count": len([p for p in category_products if p["can_order"]])
#         })
    
#     # Cache for 1 minute
#     redis_client.set(cache_key, organized_data, 60)
    
#     return organized_data


# @router.get("/products/{product_id}/details")
# async def get_product_details_for_order(
#     product_id: str,
#     request: Request,
#     current_user: dict = Depends(require_sales_staff)
# ):
#     """Get detailed product information for order creation"""
#     # Check cache
#     cache_key = f"sales:product:details:{product_id}"
#     cached = redis_client.get(cache_key)
#     if cached:
#         return cached
    
#     result = supabase.table("products").select("""
#         id, sku, variant_name, price, description, image_url, units, 
#         low_stock_threshold, status, is_available,
#         product_templates(name, description),
#         categories(id, name),
#         suppliers(name, contact_person, phone)
#     """).eq("id", product_id).execute()
    
#     if not result.data:
#         raise HTTPException(status_code=404, detail="Product not found")
    
#     product = result.data[0]
    
#     # Determine availability
#     availability_status = "available"
#     availability_message = "In stock"
    
#     if not product["is_available"]:
#         availability_status = "disabled"
#         availability_message = "Product disabled"
#     elif product["status"] == StockStatus.OUT_OF_STOCK:
#         availability_status = "out_of_stock"
#         availability_message = "Out of stock"
#     elif product["status"] == StockStatus.LOW_STOCK:
#         availability_status = "low_stock"
#         availability_message = f"Low stock ({product['units']} remaining)"
#     else:
#         availability_message = f"{product['units']} in stock"
    
#     display_name = product["product_templates"]["name"]
#     if product["variant_name"]:
#         display_name += f" - {product['variant_name']}"
    
#     product_details = {
#         "id": product["id"],
#         "display_name": display_name,
#         "template_name": product["product_templates"]["name"],
#         "variant_name": product["variant_name"],
#         "sku": product["sku"],
#         "price": float(product["price"]),
#         "description": product["description"] or product["product_templates"]["description"],
#         "image_url": product["image_url"],
#         "current_stock": product["units"],
#         "low_stock_threshold": product["low_stock_threshold"],
#         "availability_status": availability_status,
#         "availability_message": availability_message,
#         "can_order": product["is_available"] and product["status"] != StockStatus.OUT_OF_STOCK,
#         "max_order_quantity": product["units"] if product["status"] != StockStatus.OUT_OF_STOCK else 0,
#         "category": {
#             "id": product["categories"]["id"],
#             "name": product["categories"]["name"]
#         },
#         "supplier": {
#             "name": product["suppliers"]["name"],
#             "contact_person": product["suppliers"]["contact_person"],
#             "phone": product["suppliers"]["phone"]
#         } if product["suppliers"] else None
#     }
    
#     # Cache for 2 minutes
#     redis_client.set(cache_key, product_details, 120)
    
#     return product_details

@router.get("/analytics/chef/{chef_id}")
async def get_chef_analytics(
    chef_id: str,
    request: Request,
    days: int = 30,
    current_user: dict = Depends(require_manager_up)
):
    """Get individual chef analytics"""
    from .inventory_service import InventoryService
    
    analytics_data = await InventoryService.get_individual_chef_analytics(chef_id, days)
    
    from ..core.activity_logger import log_activity
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "view", "chef_analytics", chef_id, {"days": days}, request
    )
    
    return analytics_data

@staticmethod
async def get_individual_chef_analytics(chef_id: str, days: int = 30) -> Dict[str, Any]:
    """Get individual chef performance analytics"""
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    
    # Get orders completed by this chef (from activity logs)
    chef_activities = supabase.table("activity_logs").select("*").eq("user_id", chef_id).eq("action", "order_completed").gte("created_at", start_date.isoformat()).execute()
    
    # Get order details for completed orders
    completed_orders = []
    prep_times = []
    
    for activity in chef_activities.data:
        if activity.get("resource_id"):
            order = supabase.table("orders").select("*, order_items(*)").eq("id", activity["resource_id"]).execute()
            if order.data:
                order_data = order.data[0]
                completed_orders.append(order_data)
                
                # Calculate prep time
                if order_data.get("preparing_at") and order_data.get("completed_at"):
                    prep_start = datetime.fromisoformat(order_data["preparing_at"])
                    prep_end = datetime.fromisoformat(order_data["completed_at"])
                    prep_time_minutes = (prep_end - prep_start).total_seconds() / 60
                    prep_times.append(prep_time_minutes)
    
    # Get all activities for time tracking
    all_activities = supabase.table("activity_logs").select("*").eq("user_id", chef_id).gte("created_at", start_date.isoformat()).execute()
    
    # Order type breakdown
    online_orders = len([o for o in completed_orders if o["order_type"] == "online"])
    offline_orders = len([o for o in completed_orders if o["order_type"] == "offline"])
    
    # Items handled
    total_items = sum(len(o["order_items"]) for o in completed_orders)
    
    return {
        "chef_id": chef_id,
        "period": {"start": start_date.date(), "end": end_date.date(), "days": days},
        "performance": {
            "orders_completed": len(completed_orders),
            "total_items_prepared": total_items,
            "daily_average_orders": round(len(completed_orders) / days, 2),
            "daily_average_items": round(total_items / days, 2),
            "average_prep_time_minutes": round(sum(prep_times) / len(prep_times), 2) if prep_times else 0,
            "fastest_prep_time": round(min(prep_times), 2) if prep_times else 0,
            "slowest_prep_time": round(max(prep_times), 2) if prep_times else 0
        },
        "order_breakdown": {
            "online_orders": online_orders,
            "offline_orders": offline_orders,
            "average_items_per_order": round(total_items / len(completed_orders), 2) if completed_orders else 0
        },
        "activity_summary": {
            "total_actions": len(all_activities.data),
            "actions_per_day": round(len(all_activities.data) / days, 2)
        }
    }

