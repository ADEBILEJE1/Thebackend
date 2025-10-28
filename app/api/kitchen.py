from fastapi import APIRouter, HTTPException, status, Depends, Request, Query
from typing import List, Optional, Any, Dict
from datetime import datetime, date, timedelta
from decimal import Decimal
from pydantic import BaseModel, Field, validator, EmailStr
from fastapi.responses import HTMLResponse
from fastapi import BackgroundTasks


import pytz

NIGERIA_TZ = pytz.timezone('Africa/Lagos')

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
from ..website.services import EmailService



def get_nigerian_time():
    return datetime.utcnow().replace(tzinfo=pytz.UTC).astimezone(NIGERIA_TZ)

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


def invalidate_customer_tracking_cache(order_ids: List[str]):
    """Invalidate tracking cache for customers of these orders"""
    for order_id in order_ids:
        order = supabase_admin.table("orders").select("website_customer_id").eq("id", order_id).execute()
        if order.data and order.data[0].get("website_customer_id"):
            customer_id = order.data[0]["website_customer_id"]
            redis_client.delete(f"tracking:{customer_id}")

def format_currency(amount):
    """Formats a number as Nigerian Naira currency."""
    if amount is None:
        return ""
    return f"N{Decimal(amount):,.2f}"

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
            "updated_at": get_nigerian_time().isoformat()
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









# @router.get("/queue/kitchen-batches")
# async def get_kitchen_batch_queue(current_user: dict = Depends(require_chef_staff)):
#     """Get orders grouped by batches - optimized"""
    
#     # Get all orders
#     # result = supabase_admin.table("orders").select("*").in_("status", ["confirmed", "preparing"]).not_.is_("batch_id", "null").order("batch_created_at").execute()
#     result = supabase_admin.table("orders").select("*").in_("status", ["transit", "preparing"]).not_.is_("batch_id", "null").order("batch_created_at").execute()
   
    
#     if not result.data:
#         return {"batches": []}
    
#     # Collect all IDs for batch fetching
#     order_ids = [o["id"] for o in result.data]
#     customer_ids = [o["website_customer_id"] for o in result.data if o.get("website_customer_id")]
#     address_ids = [o["delivery_address_id"] for o in result.data if o.get("delivery_address_id")]
    
#     # Batch fetch all order items
#     items_result = supabase_admin.table("order_items").select("*").in_("order_id", order_ids).execute()
#     items_by_order = {}
#     all_item_ids = []
#     for item in items_result.data:
#         order_id = item["order_id"]
#         if order_id not in items_by_order:
#             items_by_order[order_id] = []
#         items_by_order[order_id].append(item)
#         all_item_ids.append(item["id"])
    
#     # Batch fetch all options
#     options_map = {}
#     if all_item_ids:
#         options_result = supabase_admin.table("order_item_options").select("*, product_options(*)").in_("order_item_id", all_item_ids).execute()
#         for opt in options_result.data:
#             item_id = opt["order_item_id"]
#             if item_id not in options_map:
#                 options_map[item_id] = []
#             options_map[item_id].append(opt)
    
#     # Batch fetch customers
#     customers_map = {}
#     if customer_ids:
#         customers_result = supabase_admin.table("website_customers").select("id, full_name, email, phone").in_("id", customer_ids).execute()
#         for cust in customers_result.data:
#             customers_map[cust["id"]] = cust
    
#     # Batch fetch addresses
#     addresses_map = {}
#     if address_ids:
#         addresses_result = supabase_admin.table("customer_addresses").select("id, full_address, delivery_areas(name, estimated_time)").in_("id", address_ids).execute()
#         for addr in addresses_result.data:
#             addresses_map[addr["id"]] = addr
    
#     # Build batches
#     batches = {}
#     for order in result.data:
#         # Attach items and options
#         order["order_items"] = items_by_order.get(order["id"], [])
#         for item in order["order_items"]:
#             item["options"] = options_map.get(item["id"], [])
        
#         # Attach customer info
#         if order.get("website_customer_id"):
#             order["website_customers"] = customers_map.get(order["website_customer_id"])
        
#         # Attach address info
#         if order.get("delivery_address_id"):
#             order["customer_addresses"] = addresses_map.get(order["delivery_address_id"])
        
#         batch_id = order["batch_id"]
#         if batch_id not in batches:
#             batches[batch_id] = {
#                 "batch_id": batch_id,
#                 "customer_name": order.get("customer_name") or (order.get("website_customers", {}) or {}).get("full_name"),
#                 "order_placement_type": order.get("order_placement_type"),
#                 "display_number": order.get("display_number"),
#                 "orders": [],
#                 "total_items": 0,
#                 "preparing_at": order.get("preparing_at"),
#                 "customer_info": {
#                     "name": order.get("customer_name") or (order.get("website_customers", {}) or {}).get("full_name"),
#                     "phone": order.get("customer_phone") or (order.get("website_customers", {}) or {}).get("phone"),
#                     "email": order.get("customer_email") or (order.get("website_customers", {}) or {}).get("email")
#                 },
#                 "delivery_info": order.get("customer_addresses")
#             }
        
#         batches[batch_id]["orders"].append(order)
#         batches[batch_id]["total_items"] += len(order["order_items"])
    
#     return {"batches": list(batches.values())}






@router.get("/queue/kitchen-batches")
async def get_kitchen_batch_queue(current_user: dict = Depends(require_chef_staff)):
    """Get orders grouped by batches - optimized with single query"""
    
    # Single query with all joins
    result = supabase_admin.table("orders").select(
        "*,"
        "order_items(*, order_item_options(*, product_options(*))),"
        "website_customers(id, full_name, email, phone),"
        "customer_addresses(id, full_address, delivery_areas(name, estimated_time))"
    # ).in_("status", ["transit", "preparing"]).not_.is_("batch_id", "null").order("batch_created_at").execute()
    ).in_("status", ["transit", "preparing"]).not_.is_("batch_id", "null").order("status.desc", "batch_created_at").execute()
    
    if not result.data:
        return {"batches": []}
    
    # Build batches
    batches = {}
    for order in result.data:
        batch_id = order["batch_id"]
        if batch_id not in batches:
            batches[batch_id] = {
                "batch_id": batch_id,
                "customer_name": order.get("customer_name") or (order.get("website_customers", {}) or {}).get("full_name"),
                "order_placement_type": order.get("order_placement_type"),
                "display_number": order.get("display_number"),
                "orders": [],
                "total_items": 0,
                "preparing_at": order.get("preparing_at"),
                "customer_info": {
                    "name": order.get("customer_name") or (order.get("website_customers", {}) or {}).get("full_name"),
                    "phone": order.get("customer_phone") or (order.get("website_customers", {}) or {}).get("phone"),
                    "email": order.get("customer_email") or (order.get("website_customers", {}) or {}).get("email")
                },
                "delivery_info": order.get("customer_addresses")
            }
        
        batches[batch_id]["orders"].append(order)
        batches[batch_id]["total_items"] += len(order.get("order_items", []))
    
    return {"batches": list(batches.values())}






@router.post("/chef/batch-ready")
async def mark_batch_ready(
    batch_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_chef_staff)
):
    # Fetch with customer data
    orders = supabase_admin.table("orders").select(
        "*, website_customers(email, full_name)"
    ).eq("batch_id", batch_id).in_("status", ["confirmed", "preparing", "transit"]).execute()
    
    if not orders.data:
        raise HTTPException(status_code=404, detail="Batch not found or already completed")
    
    order_ids = [o["id"] for o in orders.data]
    completed_at = get_nigerian_time().isoformat()
    
    supabase_admin.table("orders").update({
        "status": "completed",
        "completed_at": completed_at,
        "updated_at": completed_at
    }).in_("id", order_ids).execute()
    
    # Send emails
    for order in orders.data:
        if order.get("website_customers"):
            background_tasks.add_task(
                EmailService.send_ready_for_delivery,
                order["website_customers"]["email"],
                order["order_number"]
            )
    
    # Invalidate caches
    for order_id in order_ids:
        invalidate_order_cache(order_id)
    invalidate_customer_tracking_cache(order_ids)
    
    # Notify
    for order in orders.data:
        await notify_order_update(
            order["id"],
            "order_completed",
            {
                "order_id": order["id"],
                "order_number": order["order_number"],
                "status": "completed"
            }
        )
    
    return {"message": f"Batch {batch_id} completed - {len(orders.data)} orders marked ready"}



@router.get("/queue/history")
async def get_kitchen_history(
    request: Request,
    current_user: dict = Depends(require_chef_staff),
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0)
):
    """Get kitchen order history (completed orders)"""
    result = supabase_admin.table("orders").select("""
        *, 
        order_items(*),
        customer_addresses(full_address, delivery_areas(name)),
        website_customers(full_name, email, phone)
    """).eq("status", "completed").order("completed_at", desc=True).range(offset, offset + limit - 1).execute()
    
    # Group by batch_id for batch orders, individual for others
    history_items = []
    batches = {}
    
    for order in result.data:
        if order.get("batch_id"):
            batch_id = order["batch_id"]
            if batch_id not in batches:
                batches[batch_id] = {
                    "type": "batch",
                    "batch_id": batch_id,
                    "orders": [],
                    "total_items": 0,
                    "completed_at": order["completed_at"],
                    "customer_info": {
                        "name": order.get("customer_name") or (order.get("website_customers", {}) or {}).get("full_name"),
                        "phone": order.get("customer_phone") or (order.get("website_customers", {}) or {}).get("phone")
                    }
                }
            
            batches[batch_id]["orders"].append(order)
            # Safety check for order_items
            order_items = order.get("order_items", [])
            if order_items:
                batches[batch_id]["total_items"] += len(order_items)
        else:
            # Individual order
            history_items.append({
                "type": "individual",
                "order": order,
                "completed_at": order["completed_at"]
            })
    
    # Combine and sort by completion time
    all_items = list(batches.values()) + history_items
    all_items.sort(key=lambda x: x.get("completed_at", ""), reverse=True)
    
    return {"history": all_items}


@router.get("/", response_model=List[dict])
async def get_orders(
    status: Optional[OrderStatus] = None,
    order_type: Optional[OrderType] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    # Only show batch orders that have been pushed to kitchen
    query = supabase_admin.table("orders").select("*, order_items(*)").not_.is_("batch_id", "null").in_("status", ["preparing", "completed"])

    if status:
        query = query.eq("status", status)
    if order_type:
        query = query.eq("order_type", order_type)
    if date_from:
        query = query.gte("created_at", date_from.isoformat())
    if date_to:
        query = query.lte("created_at", date_to.isoformat())

    result = query.order("created_at", desc=True).execute()
    return result.data

@router.get("/{order_id}")
async def get_order(
    order_id: str,
    current_user: dict = Depends(get_current_user)
):
    # Only allow access to batch orders in kitchen
    result = supabase_admin.table("orders").select("*, order_items(*)").eq("id", order_id).not_.is_("batch_id", "null").in_("status", ["preparing", "completed"]).execute()

    if result.data:
        for item in result.data[0]["order_items"]:
            options_result = supabase_admin.table("order_item_options").select("*, product_options(*)").eq("order_item_id", item["id"]).execute()
            item["options"] = options_result.data
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Order not found in kitchen queue")

    return result.data[0]

@router.patch("/{order_id}/status")
async def update_order_status(
    order_id: str,
    status_update: OrderStatusUpdate,
    current_user: dict = Depends(require_sales_staff)
):
    # Only allow updates to batch orders
    order = supabase_admin.table("orders").select("*").eq("id", order_id).not_.is_("batch_id", "null").execute()
    if not order.data:
        raise HTTPException(status_code=404, detail="Order not found in kitchen")

    current_status = order.data[0]["status"]
    new_status = status_update.status

    # Validate status transition - kitchen can only complete orders
    valid_transitions = {
        OrderStatus.PREPARING: [OrderStatus.COMPLETED],
    }

    if new_status not in valid_transitions.get(current_status, []):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot change status from {current_status} to {new_status}"
        )

    # Update status with timestamp
    update_data = {"status": new_status, "updated_at": get_nigerian_time().isoformat()}

    if new_status == OrderStatus.COMPLETED:
        update_data["completed_at"] = get_nigerian_time().isoformat()
        # Send notification to customer if online order
        if order.data[0]["order_type"] == OrderType.ONLINE and order.data[0].get("customer_email"):
            send_order_ready_notification.delay(
                order.data[0]["order_number"],
                order.data[0]["customer_email"]
            )

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
       "completed_at": get_nigerian_time().isoformat(),
       "updated_at": get_nigerian_time().isoformat()
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
        "timestamp": get_nigerian_time().isoformat()
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

    for item in order["order_items"]:
        options_result = supabase_admin.table("order_item_options").select("*, product_options(*)").eq("order_item_id", item["id"]).execute()
        item["options"] = options_result.data
    
    # Generate print-friendly format
    receipt_data = {
        "order_number": order["order_number"],
        "order_type": order["order_type"],
        "customer_name": order.get("customer_name", "Walk-in Customer"),
        "created_at": order["created_at"],
        "display_number": order.get("display_number"),  
        "order_placement_type": order.get("order_placement_type"),
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
    end_date = get_nigerian_time()
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




@router.post("/kitchen/start-batch/{batch_id}")
async def start_batch_preparation(
    batch_id: str,
    request: Request,
    current_user: dict = Depends(require_chef_staff)
):
    # orders = supabase_admin.table("orders").select("*").eq("batch_id", batch_id).eq("status", "confirmed").execute()
    orders = supabase_admin.table("orders").select("*").eq("batch_id", batch_id).eq("status", "transit").execute()
    
    if not orders.data:
        raise HTTPException(status_code=404, detail="No confirmed orders found for this batch")
    
    order_ids = [o["id"] for o in orders.data]
    
    supabase_admin.table("orders").update({
        "status": "preparing",
        "preparing_at": get_nigerian_time().isoformat()
    }).in_("id", order_ids).execute()
    
    # Clear customer tracking cache
    invalidate_customer_tracking_cache(order_ids)
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "start_preparation", "batch", None,
        {"batch_id": batch_id, "order_count": len(orders.data)},
        request
    )
    
    # Notify each order
    for order in orders.data:
        await notify_order_update(
            order["id"],
            "status_update",
            {
                "order_id": order["id"],
                "status": "preparing"
            }
        )
    
    return {"message": f"Batch {batch_id} preparation started", "orders_count": len(orders.data)}


@router.get("/{order_id}/kitchen-view")
async def get_kitchen_slip_view(
    order_id: str,
    request: Request,
    current_user: dict = Depends(require_chef_staff)
):
    """Generate printable HTML kitchen slip"""
    order_result = supabase_admin.table("orders").select("*, order_items(*)").eq("id", order_id).execute()
    
    if not order_result.data:
        raise HTTPException(status_code=404, detail="Order not found")
    
    order = order_result.data[0]
    
    # Efficiently fetch all options for all items in one query
    order_items = order.get("order_items", [])
    if order_items:
        item_ids = [item['id'] for item in order_items]
        
        options_result = supabase_admin.table("order_item_options") \
            .select("*, product_options(name)") \
            .in_("order_item_id", item_ids) \
            .execute()

        options_map = {}
        for opt in options_result.data:
            item_id = opt['order_item_id']
            if item_id not in options_map:
                options_map[item_id] = []
            options_map[item_id].append(opt)

        for item in order_items:
            item['options'] = options_map.get(item['id'], [])

    # Build items HTML
    items_html = ""
    for item in order_items:
        items_html += f'<tr><td class="main-item">{item["quantity"]}X {item["product_name"]}</td></tr>'
        
        # Add options/extras
        for option in item.get("options", []):
            if option.get("product_options"):
                items_html += f'<tr><td class="sub-item">- {option["product_options"]["name"]}</td></tr>'
        
        # Add item-specific notes
        if item.get("notes"):
            items_html += f'<tr><td class="item-notes">NOTES: {item["notes"]}</td></tr>'
            
    # Format date and time
    created_dt = datetime.fromisoformat(order['created_at'])
    order_date = created_dt.strftime('%d/%m/%Y')
    order_time = created_dt.strftime('%I:%M %p')

    html_receipt = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            @media print {{
                * {{
                    -webkit-print-color-adjust: exact !important;
                    print-color-adjust: exact !important;
                }}
                body {{
                    margin: 0;
                    padding: 20px;
                    font-family: Arial, sans-serif;
                    color: #000;
                    text-transform: uppercase;
                }}
                @page {{
                    size: 80mm auto;
                    margin: 0;
                }}
            }}
            body {{
                width: 80mm;
                margin: 0 auto;
                padding: 10mm;
                font-family: Arial, sans-serif;
                text-transform: uppercase;
            }}
            .header {{
                text-align: center;
                margin-bottom: 20px;
                border-bottom: 3px solid #000;
                padding-bottom: 15px;
            }}
            .logo {{
                width: 36mm;
                height: auto;
                margin-bottom: 10px;
            }}
            .title {{
                font-size: 24px;
                font-weight: 900;
                margin: 10px 0;
            }}
            .order-info {{
                font-size: 14px;
                font-weight: 700;
                margin: 15px 0;
                padding: 10px;
                background: #f0f0f0;
                border: 2px solid #000;
            }}
            .display-number {{
                font-size: 48px;
                font-weight: 900;
                text-align: center;
                margin: 20px 0;
                padding: 20px;
                border: 4px solid #000;
                background: #000;
                color: #fff;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin: 15px 0;
            }}
            td {{
                padding: 8px 0;
                border-bottom: 1px dashed #000;
            }}
            .main-item {{
                font-weight: 900; 
                font-size: 18px;
                border-top: 3px solid #000;
                padding-top: 12px;
            }}
            .sub-item {{
                padding-left: 25px !important; 
                font-size: 16px;
            }}
            .item-notes {{
                padding-left: 25px !important; 
                font-style: italic; 
                font-size: 14px;
            }}
            .footer {{
                text-align: center;
                margin-top: 20px;
                padding-top: 15px;
                border-top: 3px solid #000;
                font-size: 14px;
                font-weight: 700;
            }}
            .bold {{
                font-weight: 900;
                font-size: 18px;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <img src="data:image/svg+xml,%3csvg width='88' height='56' viewBox='0 0 88 56' fill='none' xmlns='http://www.w3.org/2000/svg'%3e%3cg clip-path='url(%23clip0_108_53)'%3e%3cpath d='M22.0078 27.5694C22.5293 27.0777 23.1949 27.3945 23.1062 28.0174C22.7621 30.312 22.3962 32.9016 22.5626 34.6936C22.6401 35.4802 22.3406 35.8409 21.6417 35.8628C18.2359 35.8628 9.76036 34.0817 7.43069 32.9563C5.16757 31.8636 2.83789 30.3885 1.14056 29.1647C0.441658 28.6511 0.108847 28.0174 0.253065 27.4492C0.619157 25.679 1.39572 19.1011 1.39572 13.7253C1.39572 8.34935 0.608063 3.30123 0.241972 1.18145C0.131035 0.471217 0.463846 0.110636 1.16275 0.230829C1.86165 0.351022 2.63821 0.449363 3.90289 0.46029C5.23413 0.482142 6.04397 0.361949 6.83162 0.230829C7.46397 0.121562 7.86334 0.602337 7.71912 1.46554C7.35303 4.01147 6.57648 9.68242 6.57648 15.703C6.57648 18.544 7.08679 25.6135 7.08679 25.6135C11.5021 27.9518 18.4246 30.6944 22.0078 27.5694ZM14.93 25.6353C13.0552 25.3186 11.6574 24.8158 10.1597 24.2039C9.50521 23.9309 9.16131 23.6031 9.27225 22.8382C9.63834 20.8714 10.2374 15.6702 10.2374 12.4359C10.2374 8.84106 9.64944 3.67274 9.27225 1.45462C9.16131 0.55863 9.46083 0.143416 10.1597 0.230829C11.6352 0.42751 13.5322 0.547703 15.4514 0.547703C17.526 0.547703 19.6005 0.416583 21.3422 0.198049C22.0078 0.110636 22.3629 0.580483 22.3073 1.56388C22.2075 3.15918 22.2519 4.89652 22.3073 6.30606C22.3516 7.36596 21.9745 7.61726 21.2755 7.15835C18.9792 5.56305 16.6496 5.72694 15.4625 5.72694C15.4625 5.72694 15.2074 8.64438 15.0521 10.7642C16.2724 10.8625 17.7478 10.5128 18.6464 10.0321C19.2677 9.70426 19.5451 9.9228 19.5007 10.8079C19.4674 11.4962 19.423 12.1846 19.423 12.9713C19.423 13.6597 19.423 14.2935 19.4563 14.9709C19.5007 15.8888 19.2343 16.1182 18.5687 15.7467C17.5814 15.2113 16.1282 14.7196 15.0188 14.6103C15.1297 16.7738 15.4625 20.161 15.4625 20.161C18.0585 20.6418 20.2328 20.0299 21.797 18.7516C22.4293 18.2271 22.729 18.4238 22.6844 19.3635C22.618 21.1118 22.5736 22.8599 22.6844 24.4554C22.74 25.2529 22.3962 25.5479 21.7193 25.6135C18.9128 25.8976 17.0046 25.9631 14.9411 25.6135L14.93 25.6353Z' fill='%23FF0000'/%3e%3cpath d='M35.4754 12.2503C36.8399 11.0046 38.2932 8.66633 38.2932 6.53562C38.2932 1.85901 35.2534 0.0779584 30.7051 0.00147157C29.2518 -0.0203818 26.6225 0.209078 24.892 0.165372C24.2152 0.143519 23.8603 0.646146 24.0044 1.53121C24.3039 3.94601 24.892 8.74282 24.892 13.5506C24.892 18.3584 24.3372 22.4667 24.0044 24.4882C23.8936 25.3842 24.2264 25.7775 24.892 25.5918C25.4687 25.4388 26.2343 25.2203 27.3325 25.1219C28.564 25.0126 30.2613 24.8487 31.5925 24.3898C35.6639 22.9912 39.5134 20.3252 39.5134 15.6266C39.5134 13.0807 37.4389 11.8788 35.4754 12.2394V12.2503ZM29.6623 7.22401C29.9285 5.71613 30.7384 4.59067 31.5815 4.5142C32.6909 4.41586 33.545 5.48667 33.545 8.08721C33.545 10.0103 32.3248 11.704 30.3944 12.0973C30.0949 12.1519 29.9508 12.1847 29.6511 12.2503C29.6511 10.2616 29.3295 9.03784 29.6511 7.22401H29.6623ZM31.7812 20.4671C30.8603 20.7621 30.0616 20.3252 29.7844 19.2433C29.4847 18.0743 29.7067 17.0908 29.7067 15.4955C30.0172 15.419 30.1726 15.3862 30.4831 15.3098C32.4468 14.829 33.8557 15.4518 33.8557 16.9815C33.8557 19.0249 32.8904 20.1176 31.7812 20.478V20.4671Z' fill='%23FF0000'/%3e%3cpath d='M57.0188 21.4068C56.3198 19.5711 54.9443 13.485 54.1676 9.51865C53.5797 6.49195 53.0917 3.5199 53.0584 0.733591C53.0584 0.296524 52.6923 0.0779898 52.06 0.132623C49.2089 0.394864 44.616 0.602471 40.3672 0.0342833C39.7016 -0.0422036 39.3465 0.34023 39.4019 1.07232C39.5462 2.94078 39.5019 4.83111 39.4019 6.71049C39.3576 7.56276 39.8124 7.72666 40.4337 7.16941C41.0661 6.61216 41.7982 6.10953 42.353 5.74894C42.2974 6.31712 42.2641 6.61216 42.2087 7.18034C41.7649 13.2665 41.0328 21.2538 35.73 24.9034C32.4019 27.198 27.554 27.7662 24.9247 27.3839C24.2259 27.2963 23.9152 27.6788 23.9596 28.4655C24.0706 30.2138 24.0926 32.8471 23.9262 34.4752C23.8486 35.2073 24.1149 35.5459 24.8138 35.3712C28.3637 34.4097 35.73 31.82 38.104 29.9406C41.6874 27.0998 43.6509 23.9855 44.8824 20.2487C46.7349 19.4401 47.6556 19.0466 49.5083 18.2708C49.5417 20.0191 49.5527 23.614 49.5083 24.5428C49.475 25.1876 49.8412 25.3295 50.4734 24.9689C51.3388 24.4663 52.1377 24.0183 53.5133 23.4612C54.7335 22.9584 55.4768 22.7617 56.1757 22.5978C56.919 22.4339 57.2518 21.9313 57.03 21.3851L57.0188 21.4068ZM46.0249 15.7906C46.5797 12.9278 46.99 9.64976 47.4671 6.01117C47.5892 5.33373 47.6446 5.00592 47.7666 4.35033C48.2104 6.80883 48.6542 9.16898 49.0645 11.999C49.1755 12.8294 49.2532 13.7036 49.3199 14.5558C47.9997 15.0475 47.3451 15.2989 46.0249 15.8015V15.7906Z' fill='%23FF0000'/%3e%3cpath d='M61.4683 20.9369C60.2146 21.21 59.427 21.4832 58.6949 21.7892C58.0293 22.0734 57.6631 21.8766 57.8073 21.1663C58.1734 19.0576 58.95 12.4469 58.95 8.5679C58.95 4.68892 58.1734 1.90261 57.8073 0.678824C57.6631 0.274536 58.0293 0.0669297 58.6949 0.121563C59.5046 0.187123 60.3922 0.219902 61.6901 0.219902C63.099 0.219902 64.1085 0.176196 65.0959 0.0997097C65.7505 0.0450763 66.0722 0.23083 66.061 0.613263C66.0056 2.08836 66.8709 4.50317 68.0911 6.25144C68.8678 7.33317 69.6887 8.43678 70.4652 9.46388C70.4764 9.02681 70.4874 8.80827 70.4985 8.38213C70.4985 4.78726 69.722 1.89168 69.3559 0.678824C69.2449 0.274536 69.5777 0.0669297 70.2767 0.13249C70.9756 0.19805 71.7522 0.241757 73.0168 0.252684C74.348 0.252684 75.1467 0.19805 75.9787 0.13249C76.6333 0.0778563 76.9772 0.307316 76.8663 0.777165C76.3115 2.78768 75.7236 4.56873 75.6792 9.04866C75.6459 12.7747 76.4559 18.9045 76.822 20.6857C76.9661 21.2976 76.5779 21.4832 75.9344 21.2319C75.1357 20.915 74.337 20.6309 73.0057 20.4233C71.6412 20.2157 70.7981 20.2377 70.0105 20.3142C69.4667 20.3687 69.0896 20.1392 68.9788 19.6258C68.6126 17.9648 67.5698 11.9224 65.7615 9.24534C65.1292 8.30564 64.6189 7.61727 64.1751 7.04908C64.1418 7.43151 64.1418 7.8358 64.1418 8.26195C64.1418 11.9224 64.9184 17.954 65.2846 19.6584C65.4287 20.2377 65.0405 20.62 64.3636 20.6309C63.6204 20.6309 62.8106 20.6637 61.4794 20.9478L61.4683 20.9369Z' fill='%23FF0000'/%3e%3cpath d='M14.9296 55.0718C15.2624 53.7934 15.8504 50.8869 15.8504 47.2264C15.8504 44.9756 15.6285 42.7903 15.4067 41.0529C10.2592 40.299 5.45562 38.4523 0.929385 35.9501C0.297043 35.6114 -0.0579547 35.0323 0.00860754 34.4422C0.152826 32.9671 0.141732 31.8527 0.00860754 30.2902C-0.0579547 29.5798 0.263763 29.5907 0.896104 30.17C5.77733 34.6498 11.6237 36.4964 18.9899 37.2832C25.8014 38.0153 32.269 35.1852 38.3928 31.9509C39.0251 31.5903 39.3469 31.7761 39.2802 32.4426C39.1471 33.9288 39.2027 35.0104 39.3135 36.4527C39.3579 37.0537 38.9807 37.5017 38.3484 37.6547C32.6907 39.3702 27.2992 41.0966 21.3195 41.315C21.0644 43.0853 20.887 45.2705 20.9867 47.5105C21.1531 51.1273 21.608 54.0119 21.8743 55.1265C21.9631 55.5089 21.6192 55.7056 20.9536 55.64C20.2878 55.5745 19.5891 55.5307 18.4686 55.5307C17.3259 55.5307 16.5715 55.5635 15.8393 55.6291C15.1737 55.6837 14.8076 55.487 14.9185 55.0609L14.9296 55.0718ZM1.01813 55.6291C0.385793 55.6291 0.0529823 55.2904 0.130638 54.6348C0.274857 53.3782 0.385793 51.8484 0.352512 50.5481C0.330324 49.8379 0.685323 49.7397 1.31766 50.2314C2.72657 51.2365 4.75671 52.1436 5.83281 52.2746C7.01983 52.4275 8.01827 52.2746 8.01827 51.5317C8.01827 50.8322 5.49998 49.6303 3.72499 48.035C1.27329 45.8387 0.00860754 43.7081 0.00860754 41.4135C0.00860754 38.1355 3.27016 38.6053 7.23061 40.2334C9.22747 41.0529 10.2259 41.5665 11.6681 41.8943C12.2893 42.0363 12.6222 42.3532 12.5556 42.8121C12.4003 43.8828 12.2782 45.3799 12.3337 46.5272C12.3559 47.1173 11.9676 47.1719 11.3685 46.6145C10.0373 45.4016 8.59514 44.3528 7.5967 44.025C6.48732 43.6644 5.63312 43.7626 5.63312 44.4619C5.63312 45.3253 7.56342 46.538 9.14981 47.6527C11.4018 49.2369 13.6317 50.6137 13.6317 52.3183C13.6317 54.5255 10.592 55.8695 6.12123 55.8695C4.08 55.8695 2.63781 55.64 1.01813 55.6291ZM35.6194 55.5526C34.8096 55.5526 34.3214 55.5854 33.8443 55.6291C33.1899 55.6837 32.9459 55.4543 33.101 54.9953C33.2343 54.602 33.4007 53.9791 33.4007 53.0613C33.4007 51.6519 31.6257 51.1819 29.6622 51.3567C29.8063 53.1159 30.2168 54.3616 30.4719 55.0827C30.6162 55.498 30.2722 55.6946 29.5845 55.6619C29.0076 55.6291 28.3974 55.6072 27.399 55.6072C25.9567 55.6072 25.1358 55.6291 24.5145 55.6728C23.8158 55.7165 23.5161 55.5307 23.6271 55.1374C23.9599 54.2086 24.5478 52.2199 24.5478 49.7397C24.5478 47.2593 23.9599 44.6697 23.6271 43.3803C23.5161 42.8666 23.8268 42.5936 24.5478 42.5825C26.6667 42.528 28.3197 42.1019 30.4386 41.3916C34.9981 39.8619 38.2487 40.594 38.2487 44.2435C38.2487 46.4835 37.2169 48.1989 35.5084 49.3134C37.1726 49.7177 38.1377 50.9852 38.3595 51.8484C38.6146 52.8646 39.0584 54.001 39.3579 54.7222C39.602 55.3013 39.2802 55.6619 38.5815 55.6072C37.8382 55.5526 36.9506 55.5417 35.6194 55.5526ZM30.4386 49.8379C32.2136 49.4664 33.323 48.1552 33.323 45.7733C33.323 44.0578 32.6907 43.5114 31.3593 43.9265C30.6606 44.1452 29.9837 44.921 29.8063 45.642C29.4291 47.139 29.6176 48.6361 29.6176 50.0018C29.9394 49.9362 30.1058 49.9036 30.4275 49.8379H30.4386Z' fill='%23FF0000'/%3e%3cpath d='M47.6568 55.1375C45.3271 55.1812 42.9975 55.3559 41.2558 55.5418C40.5568 55.6183 40.224 55.3342 40.3683 54.7112C40.7786 52.8429 41.5109 48.3629 41.5109 43.4459C41.5109 38.5288 40.7676 34.2347 40.3683 32.3772C40.224 31.7653 40.5568 31.2845 41.2558 31.0332C45.1053 29.6673 51.695 26.5641 54.8012 24.8268C54.9121 24.7503 54.9676 25.1438 54.9121 25.8757C54.7679 27.5912 54.8567 28.9899 54.9121 31.186C54.9343 32.0494 54.5016 32.4209 53.8026 32.2022C51.2845 31.1752 48.6221 32.6066 47.2906 33.2621C47.2906 33.2621 46.9578 36.6822 46.8137 39.4685C48.2559 38.944 49.8533 37.906 50.9184 36.9555C51.5507 36.4527 51.8281 36.4747 51.7727 37.305C51.7171 38.0699 51.695 38.8786 51.695 39.7417C51.695 40.5284 51.6838 41.3698 51.7281 42.1019C51.7837 42.8995 51.5063 43.1618 50.8407 43.0197C49.7313 42.823 48.0673 42.8777 46.7693 43.271C46.9135 46.0355 47.2906 49.9801 47.2906 50.0238C53.969 49.1387 62.2561 48.647 68.3132 45.6749C68.9457 45.3034 69.2008 45.4564 69.1675 46.3524C69.0565 48.8218 69.0898 51.9032 69.2785 54.0556C69.3672 55.0281 69.0565 55.4544 68.3576 55.3996C61.4796 54.9188 54.5459 55.0064 47.668 55.1375H47.6568ZM62.2007 42.7793C60.348 42.834 58.4954 43.0416 57.0532 43.5333C56.3876 43.7627 56.0881 43.4131 56.1989 42.5717C56.5317 40.4082 57.1197 36.3764 57.1197 33.5134C57.1197 30.312 56.5317 26.9793 56.1989 25.384C56.0881 24.7066 56.3876 24.2586 57.0865 24.0839C58.4954 23.745 60.348 23.3081 62.1896 22.9366C64.1865 22.5431 66.1167 22.2699 67.925 21.9641C68.5573 21.8984 68.8901 22.2482 68.8458 23.0566C68.7793 24.2914 68.8124 25.7774 68.8124 26.8264C68.8124 27.7442 68.4019 27.9518 67.7363 27.5694C65.5843 26.3019 63.3322 26.8045 62.1784 27.0231C62.1784 27.0231 61.9233 28.8041 61.8125 30.6726C62.955 30.5415 64.3085 29.9624 65.2182 29.5034C65.8395 29.1866 66.15 29.3723 66.1056 30.2137C66.0723 30.8365 66.0279 31.4156 66.0279 32.0931C66.0279 32.6831 66.0279 33.2293 66.0613 33.8195C66.1056 34.7263 65.7951 34.9448 65.1405 34.6609C64.2086 34.2675 62.844 33.9506 61.7679 34.049C61.8456 36.0484 62.1784 38.0591 62.1784 38.0591C64.6634 38.0591 66.6936 37.458 68.3245 36.2451C68.9124 35.7971 69.2673 36.0158 69.2119 36.9444C69.1232 38.4634 69.1232 40.2226 69.2119 41.9489C69.2562 42.8121 68.8901 43.2164 68.2468 43.129C66.4274 42.8558 64.1754 42.7247 62.1784 42.7793H62.2007Z' fill='%23FF0000'/%3e%3cpath d='M75.6454 54.1105C76.1669 49.0734 76.3887 43.8504 76.5662 38.7476C76.6995 34.8141 76.4554 31.2738 76.2002 28.564C74.9798 28.1049 73.3824 28.1269 71.4631 28.859C70.7975 29.0994 70.3539 28.706 70.387 27.8319C70.4869 25.7121 70.5534 24.6959 70.4203 23.1552C70.3539 22.3357 70.7531 21.9642 71.3854 22.1063C72.861 22.445 73.7929 22.587 75.4901 23.0241C78.4079 23.778 79.8611 24.3572 82.7787 26.1382C84.5204 27.1981 85.408 27.8536 86.8834 28.9244C87.5157 29.3835 87.9041 30.1045 87.8485 30.6727C87.7377 31.842 87.7487 33.0766 87.8485 34.6502C87.893 35.3603 87.4382 35.3384 86.7724 34.6065C84.9198 32.5741 83.3666 31.3066 82.1464 30.8149C81.8913 33.164 81.6693 36.3546 81.6693 40.0697C81.6693 46.0904 82.3018 51.8377 82.5902 54.3072C82.701 55.1376 82.3682 55.5091 81.6693 55.378C80.9372 55.236 80.2272 55.1376 79.0401 55.1158C77.8976 55.1048 77.2208 55.1922 76.5995 55.3234C75.9006 55.4654 75.5457 55.0065 75.6344 54.0886L75.6454 54.1105Z' fill='%23FF0000'/%3e%3c/g%3e%3cdefs%3e%3cclipPath id='clip0_108_53'%3e%3crect width='88' height='56' fill='white'/%3e%3c/clipPath%3e%3c/defs%3e%3c/svg%3e" alt="Logo" class="logo">
            <div class="title">KITCHEN SLIP</div>
        </div>

        <div class="display-number">#{order.get('display_number', 'N/A')}</div>

        <div class="order-info">
            <div><strong>ORDER:</strong> {order.get('order_number', '')}</div>
            <div><strong>BATCH:</strong> {order.get('batch_id', 'N/A')}</div>
            <div><strong>TYPE:</strong> {(order.get('order_placement_type') or order.get('order_type') or "").upper()}</div>
            <div><strong>CUSTOMER:</strong> {order.get('customer_name', 'WALK-IN')}</div>
            <div><strong>DATE:</strong> {order_date}</div>
            <div><strong>TIME:</strong> {order_time}</div>
        </div>

        <table>
            <tbody>
                {items_html}
            </tbody>
        </table>
        
        <div class="bold">TOTAL ITEMS: {sum(item['quantity'] for item in order_items)}</div>
        
        {f'<div style="margin-top: 15px; padding: 10px; border: 2px solid #000; background: #fffacd;"><strong>SPECIAL NOTES:</strong><br>{order.get("notes")}</div>' if order.get("notes") else ""}
        
        <div class="footer">
            <div style="margin-top: 10px;">*** KITCHEN COPY ***</div>
        </div>
    </body>
    </html>
    """
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "print", "kitchen_slip", order_id, {"order_number": order["order_number"]}, 
        request
    )
    
    return HTMLResponse(content=html_receipt)







@router.get("/kitchen/{order_id}/customer-receipt")
async def print_customer_receipt_by_order(
    order_id: str,
    request: Request,
    current_user: dict = Depends(require_chef_staff)
):
    """Generate customer receipt for a single order"""
    orders_result = supabase_admin.table("orders").select(
        "*, order_items(*), customer_addresses(full_address), website_customers(full_name, phone)"
    ).eq("id", order_id).execute()

    if not orders_result.data:
        raise HTTPException(status_code=404, detail="Order not found")

    all_receipts_html = []
    
    # Efficiently fetch options for all items across all orders in the batch
    all_order_items = [item for order in orders_result.data for item in order.get("order_items", [])]
    if all_order_items:
        all_item_ids = [item['id'] for item in all_order_items]
        options_result = supabase_admin.table("order_item_options").select("*, product_options(name)").in_("order_item_id", all_item_ids).execute()
        
        options_map = {}
        for opt in options_result.data:
            item_id = opt['order_item_id']
            if item_id not in options_map:
                options_map[item_id] = []
            options_map[item_id].append(opt)

        for item in all_order_items:
            item['options'] = options_map.get(item['id'], [])

    logo_svg_uri = "data:image/svg+xml,%3csvg width='88' height='56' viewBox='0 0 88 56' fill='none' xmlns='http://www.w3.org/2000/svg'%3e%3cg clip-path='url(%23clip0_108_53)'%3e%3cpath d='M22.0078 27.5694C22.5293 27.0777 23.1949 27.3945 23.1062 28.0174C22.7621 30.312 22.3962 32.9016 22.5626 34.6936C22.6401 35.4802 22.3406 35.8409 21.6417 35.8628C18.2359 35.8628 9.76036 34.0817 7.43069 32.9563C5.16757 31.8636 2.83789 30.3885 1.14056 29.1647C0.441658 28.6511 0.108847 28.0174 0.253065 27.4492C0.619157 25.679 1.39572 19.1011 1.39572 13.7253C1.39572 8.34935 0.608063 3.30123 0.241972 1.18145C0.131035 0.471217 0.463846 0.110636 1.16275 0.230829C1.86165 0.351022 2.63821 0.449363 3.90289 0.46029C5.23413 0.482142 6.04397 0.361949 6.83162 0.230829C7.46397 0.121562 7.86334 0.602337 7.71912 1.46554C7.35303 4.01147 6.57648 9.68242 6.57648 15.703C6.57648 18.544 7.08679 25.6135 7.08679 25.6135C11.5021 27.9518 18.4246 30.6944 22.0078 27.5694ZM14.93 25.6353C13.0552 25.3186 11.6574 24.8158 10.1597 24.2039C9.50521 23.9309 9.16131 23.6031 9.27225 22.8382C9.63834 20.8714 10.2374 15.6702 10.2374 12.4359C10.2374 8.84106 9.64944 3.67274 9.27225 1.45462C9.16131 0.55863 9.46083 0.143416 10.1597 0.230829C11.6352 0.42751 13.5322 0.547703 15.4514 0.547703C17.526 0.547703 19.6005 0.416583 21.3422 0.198049C22.0078 0.110636 22.3629 0.580483 22.3073 1.56388C22.2075 3.15918 22.2519 4.89652 22.3073 6.30606C22.3516 7.36596 21.9745 7.61726 21.2755 7.15835C18.9792 5.56305 16.6496 5.72694 15.4625 5.72694C15.4625 5.72694 15.2074 8.64438 15.0521 10.7642C16.2724 10.8625 17.7478 10.5128 18.6464 10.0321C19.2677 9.70426 19.5451 9.9228 19.5007 10.8079C19.4674 11.4962 19.423 12.1846 19.423 12.9713C19.423 13.6597 19.423 14.2935 19.4563 14.9709C19.5007 15.8888 19.2343 16.1182 18.5687 15.7467C17.5814 15.2113 16.1282 14.7196 15.0188 14.6103C15.1297 16.7738 15.4625 20.161 15.4625 20.161C18.0585 20.6418 20.2328 20.0299 21.797 18.7516C22.4293 18.2271 22.729 18.4238 22.6844 19.3635C22.618 21.1118 22.5736 22.8599 22.6844 24.4554C22.74 25.2529 22.3962 25.5479 21.7193 25.6135C18.9128 25.8976 17.0046 25.9631 14.9411 25.6135L14.93 25.6353Z' fill='%23FF0000'/%3e%3cpath d='M35.4754 12.2503C36.8399 11.0046 38.2932 8.66633 38.2932 6.53562C38.2932 1.85901 35.2534 0.0779584 30.7051 0.00147157C29.2518 -0.0203818 26.6225 0.209078 24.892 0.165372C24.2152 0.143519 23.8603 0.646146 24.0044 1.53121C24.3039 3.94601 24.892 8.74282 24.892 13.5506C24.892 18.3584 24.3372 22.4667 24.0044 24.4882C23.8936 25.3842 24.2264 25.7775 24.892 25.5918C25.4687 25.4388 26.2343 25.2203 27.3325 25.1219C28.564 25.0126 30.2613 24.8487 31.5925 24.3898C35.6639 22.9912 39.5134 20.3252 39.5134 15.6266C39.5134 13.0807 37.4389 11.8788 35.4754 12.2394V12.2503ZM29.6623 7.22401C29.9285 5.71613 30.7384 4.59067 31.5815 4.5142C32.6909 4.41586 33.545 5.48667 33.545 8.08721C33.545 10.0103 32.3248 11.704 30.3944 12.0973C30.0949 12.1519 29.9508 12.1847 29.6511 12.2503C29.6511 10.2616 29.3295 9.03784 29.6511 7.22401H29.6623ZM31.7812 20.4671C30.8603 20.7621 30.0616 20.3252 29.7844 19.2433C29.4847 18.0743 29.7067 17.0908 29.7067 15.4955C30.0172 15.419 30.1726 15.3862 30.4831 15.3098C32.4468 14.829 33.8557 15.4518 33.8557 16.9815C33.8557 19.0249 32.8904 20.1176 31.7812 20.478V20.4671Z' fill='%23FF0000'/%3e%3cpath d='M57.0188 21.4068C56.3198 19.5711 54.9443 13.485 54.1676 9.51865C53.5797 6.49195 53.0917 3.5199 53.0584 0.733591C53.0584 0.296524 52.6923 0.0779898 52.06 0.132623C49.2089 0.394864 44.616 0.602471 40.3672 0.0342833C39.7016 -0.0422036 39.3465 0.34023 39.4019 1.07232C39.5462 2.94078 39.5019 4.83111 39.4019 6.71049C39.3576 7.56276 39.8124 7.72666 40.4337 7.16941C41.0661 6.61216 41.7982 6.10953 42.353 5.74894C42.2974 6.31712 42.2641 6.61216 42.2087 7.18034C41.7649 13.2665 41.0328 21.2538 35.73 24.9034C32.4019 27.198 27.554 27.7662 24.9247 27.3839C24.2259 27.2963 23.9152 27.6788 23.9596 28.4655C24.0706 30.2138 24.0926 32.8471 23.9262 34.4752C23.8486 35.2073 24.1149 35.5459 24.8138 35.3712C28.3637 34.4097 35.73 31.82 38.104 29.9406C41.6874 27.0998 43.6509 23.9855 44.8824 20.2487C46.7349 19.4401 47.6556 19.0466 49.5083 18.2708C49.5417 20.0191 49.5527 23.614 49.5083 24.5428C49.475 25.1876 49.8412 25.3295 50.4734 24.9689C51.3388 24.4663 52.1377 24.0183 53.5133 23.4612C54.7335 22.9584 55.4768 22.7617 56.1757 22.5978C56.919 22.4339 57.2518 21.9313 57.03 21.3851L57.0188 21.4068ZM46.0249 15.7906C46.5797 12.9278 46.99 9.64976 47.4671 6.01117C47.5892 5.33373 47.6446 5.00592 47.7666 4.35033C48.2104 6.80883 48.6542 9.16898 49.0645 11.999C49.1755 12.8294 49.2532 13.7036 49.3199 14.5558C47.9997 15.0475 47.3451 15.2989 46.0249 15.8015V15.7906Z' fill='%23FF0000'/%3e%3cpath d='M61.4683 20.9369C60.2146 21.21 59.427 21.4832 58.6949 21.7892C58.0293 22.0734 57.6631 21.8766 57.8073 21.1663C58.1734 19.0576 58.95 12.4469 58.95 8.5679C58.95 4.68892 58.1734 1.90261 57.8073 0.678824C57.6631 0.274536 58.0293 0.0669297 58.6949 0.121563C59.5046 0.187123 60.3922 0.219902 61.6901 0.219902C63.099 0.219902 64.1085 0.176196 65.0959 0.0997097C65.7505 0.0450763 66.0722 0.23083 66.061 0.613263C66.0056 2.08836 66.8709 4.50317 68.0911 6.25144C68.8678 7.33317 69.6887 8.43678 70.4652 9.46388C70.4764 9.02681 70.4874 8.80827 70.4985 8.38213C70.4985 4.78726 69.722 1.89168 69.3559 0.678824C69.2449 0.274536 69.5777 0.0669297 70.2767 0.13249C70.9756 0.19805 71.7522 0.241757 73.0168 0.252684C74.348 0.252684 75.1467 0.19805 75.9787 0.13249C76.6333 0.0778563 76.9772 0.307316 76.8663 0.777165C76.3115 2.78768 75.7236 4.56873 75.6792 9.04866C75.6459 12.7747 76.4559 18.9045 76.822 20.6857C76.9661 21.2976 76.5779 21.4832 75.9344 21.2319C75.1357 20.915 74.337 20.6309 73.0057 20.4233C71.6412 20.2157 70.7981 20.2377 70.0105 20.3142C69.4667 20.3687 69.0896 20.1392 68.9788 19.6258C68.6126 17.9648 67.5698 11.9224 65.7615 9.24534C65.1292 8.30564 64.6189 7.61727 64.1751 7.04908C64.1418 7.43151 64.1418 7.8358 64.1418 8.26195C64.1418 11.9224 64.9184 17.954 65.2846 19.6584C65.4287 20.2377 65.0405 20.62 64.3636 20.6309C63.6204 20.6309 62.8106 20.6637 61.4794 20.9478L61.4683 20.9369Z' fill='%23FF0000'/%3e%3cpath d='M14.9296 55.0718C15.2624 53.7934 15.8504 50.8869 15.8504 47.2264C15.8504 44.9756 15.6285 42.7903 15.4067 41.0529C10.2592 40.299 5.45562 38.4523 0.929385 35.9501C0.297043 35.6114 -0.0579547 35.0323 0.00860754 34.4422C0.152826 32.9671 0.141732 31.8527 0.00860754 30.2902C-0.0579547 29.5798 0.263763 29.5907 0.896104 30.17C5.77733 34.6498 11.6237 36.4964 18.9899 37.2832C25.8014 38.0153 32.269 35.1852 38.3928 31.9509C39.0251 31.5903 39.3469 31.7761 39.2802 32.4426C39.1471 33.9288 39.2027 35.0104 39.3135 36.4527C39.3579 37.0537 38.9807 37.5017 38.3484 37.6547C32.6907 39.3702 27.2992 41.0966 21.3195 41.315C21.0644 43.0853 20.887 45.2705 20.9867 47.5105C21.1531 51.1273 21.608 54.0119 21.8743 55.1265C21.9631 55.5089 21.6192 55.7056 20.9536 55.64C20.2878 55.5745 19.5891 55.5307 18.4686 55.5307C17.3259 55.5307 16.5715 55.5635 15.8393 55.6291C15.1737 55.6837 14.8076 55.487 14.9185 55.0609L14.9296 55.0718ZM1.01813 55.6291C0.385793 55.6291 0.0529823 55.2904 0.130638 54.6348C0.274857 53.3782 0.385793 51.8484 0.352512 50.5481C0.330324 49.8379 0.685323 49.7397 1.31766 50.2314C2.72657 51.2365 4.75671 52.1436 5.83281 52.2746C7.01983 52.4275 8.01827 52.2746 8.01827 51.5317C8.01827 50.8322 5.49998 49.6303 3.72499 48.035C1.27329 45.8387 0.00860754 43.7081 0.00860754 41.4135C0.00860754 38.1355 3.27016 38.6053 7.23061 40.2334C9.22747 41.0529 10.2259 41.5665 11.6681 41.8943C12.2893 42.0363 12.6222 42.3532 12.5556 42.8121C12.4003 43.8828 12.2782 45.3799 12.3337 46.5272C12.3559 47.1173 11.9676 47.1719 11.3685 46.6145C10.0373 45.4016 8.59514 44.3528 7.5967 44.025C6.48732 43.6644 5.63312 43.7626 5.63312 44.4619C5.63312 45.3253 7.56342 46.538 9.14981 47.6527C11.4018 49.2369 13.6317 50.6137 13.6317 52.3183C13.6317 54.5255 10.592 55.8695 6.12123 55.8695C4.08 55.8695 2.63781 55.64 1.01813 55.6291ZM35.6194 55.5526C34.8096 55.5526 34.3214 55.5854 33.8443 55.6291C33.1899 55.6837 32.9459 55.4543 33.101 54.9953C33.2343 54.602 33.4007 53.9791 33.4007 53.0613C33.4007 51.6519 31.6257 51.1819 29.6622 51.3567C29.8063 53.1159 30.2168 54.3616 30.4719 55.0827C30.6162 55.498 30.2722 55.6946 29.5845 55.6619C29.0076 55.6291 28.3974 55.6072 27.399 55.6072C25.9567 55.6072 25.1358 55.6291 24.5145 55.6728C23.8158 55.7165 23.5161 55.5307 23.6271 55.1374C23.9599 54.2086 24.5478 52.2199 24.5478 49.7397C24.5478 47.2593 23.9599 44.6697 23.6271 43.3803C23.5161 42.8666 23.8268 42.5936 24.5478 42.5825C26.6667 42.528 28.3197 42.1019 30.4386 41.3916C34.9981 39.8619 38.2487 40.594 38.2487 44.2435C38.2487 46.4835 37.2169 48.1989 35.5084 49.3134C37.1726 49.7177 38.1377 50.9852 38.3595 51.8484C38.6146 52.8646 39.0584 54.001 39.3579 54.7222C39.602 55.3013 39.2802 55.6619 38.5815 55.6072C37.8382 55.5526 36.9506 55.5417 35.6194 55.5526ZM30.4386 49.8379C32.2136 49.4664 33.323 48.1552 33.323 45.7733C33.323 44.0578 32.6907 43.5114 31.3593 43.9265C30.6606 44.1452 29.9837 44.921 29.8063 45.642C29.4291 47.139 29.6176 48.6361 29.6176 50.0018C29.9394 49.9362 30.1058 49.9036 30.4275 49.8379H30.4386Z' fill='%23FF0000'/%3e%3cpath d='M47.6568 55.1375C45.3271 55.1812 42.9975 55.3559 41.2558 55.5418C40.5568 55.6183 40.224 55.3342 40.3683 54.7112C40.7786 52.8429 41.5109 48.3629 41.5109 43.4459C41.5109 38.5288 40.7676 34.2347 40.3683 32.3772C40.224 31.7653 40.5568 31.2845 41.2558 31.0332C45.1053 29.6673 51.695 26.5641 54.8012 24.8268C54.9121 24.7503 54.9676 25.1438 54.9121 25.8757C54.7679 27.5912 54.8567 28.9899 54.9121 31.186C54.9343 32.0494 54.5016 32.4209 53.8026 32.2022C51.2845 31.1752 48.6221 32.6066 47.2906 33.2621C47.2906 33.2621 46.9578 36.6822 46.8137 39.4685C48.2559 38.944 49.8533 37.906 50.9184 36.9555C51.5507 36.4527 51.8281 36.4747 51.7727 37.305C51.7171 38.0699 51.695 38.8786 51.695 39.7417C51.695 40.5284 51.6838 41.3698 51.7281 42.1019C51.7837 42.8995 51.5063 43.1618 50.8407 43.0197C49.7313 42.823 48.0673 42.8777 46.7693 43.271C46.9135 46.0355 47.2906 49.9801 47.2906 50.0238C53.969 49.1387 62.2561 48.647 68.3132 45.6749C68.9457 45.3034 69.2008 45.4564 69.1675 46.3524C69.0565 48.8218 69.0898 51.9032 69.2785 54.0556C69.3672 55.0281 69.0565 55.4544 68.3576 55.3996C61.4796 54.9188 54.5459 55.0064 47.668 55.1375H47.6568ZM62.2007 42.7793C60.348 42.834 58.4954 43.0416 57.0532 43.5333C56.3876 43.7627 56.0881 43.4131 56.1989 42.5717C56.5317 40.4082 57.1197 36.3764 57.1197 33.5134C57.1197 30.312 56.5317 26.9793 56.1989 25.384C56.0881 24.7066 56.3876 24.2586 57.0865 24.0839C58.4954 23.745 60.348 23.3081 62.1896 22.9366C64.1865 22.5431 66.1167 22.2699 67.925 21.9641C68.5573 21.8984 68.8901 22.2482 68.8458 23.0566C68.7793 24.2914 68.8124 25.7774 68.8124 26.8264C68.8124 27.7442 68.4019 27.9518 67.7363 27.5694C65.5843 26.3019 63.3322 26.8045 62.1784 27.0231C62.1784 27.0231 61.9233 28.8041 61.8125 30.6726C62.955 30.5415 64.3085 29.9624 65.2182 29.5034C65.8395 29.1866 66.15 29.3723 66.1056 30.2137C66.0723 30.8365 66.0279 31.4156 66.0279 32.0931C66.0279 32.6831 66.0279 33.2293 66.0613 33.8195C66.1056 34.7263 65.7951 34.9448 65.1405 34.6609C64.2086 34.2675 62.844 33.9506 61.7679 34.049C61.8456 36.0484 62.1784 38.0591 62.1784 38.0591C64.6634 38.0591 66.6936 37.458 68.3245 36.2451C68.9124 35.7971 69.2673 36.0158 69.2119 36.9444C69.1232 38.4634 69.1232 40.2226 69.2119 41.9489C69.2562 42.8121 68.8901 43.2164 68.2468 43.129C66.4274 42.8558 64.1754 42.7247 62.1784 42.7793H62.2007Z' fill='%23FF0000'/%3e%3cpath d='M75.6454 54.1105C76.1669 49.0734 76.3887 43.8504 76.5662 38.7476C76.6995 34.8141 76.4554 31.2738 76.2002 28.564C74.9798 28.1049 73.3824 28.1269 71.4631 28.859C70.7975 29.0994 70.3539 28.706 70.387 27.8319C70.4869 25.7121 70.5534 24.6959 70.4203 23.1552C70.3539 22.3357 70.7531 21.9642 71.3854 22.1063C72.861 22.445 73.7929 22.587 75.4901 23.0241C78.4079 23.778 79.8611 24.3572 82.7787 26.1382C84.5204 27.1981 85.408 27.8536 86.8834 28.9244C87.5157 29.3835 87.9041 30.1045 87.8485 30.6727C87.7377 31.842 87.7487 33.0766 87.8485 34.6502C87.893 35.3603 87.4382 35.3384 86.7724 34.6065C84.9198 32.5741 83.3666 31.3066 82.1464 30.8149C81.8913 33.164 81.6693 36.3546 81.6693 40.0697C81.6693 46.0904 82.3018 51.8377 82.5902 54.3072C82.701 55.1376 82.3682 55.5091 81.6693 55.378C80.9372 55.236 80.2272 55.1376 79.0401 55.1158C77.8976 55.1048 77.2208 55.1922 76.5995 55.3234C75.9006 55.4654 75.5457 55.0065 75.6344 54.0886L75.6454 54.1105Z' fill='%23FF0000'/%3e%3c/g%3e%3cdefs%3e%3cclipPath id='clip0_108_53'%3e%3crect width='88' height='56' fill='white'/%3e%3c/clipPath%3e%3c/defs%3e%3c/svg%3e"

    for order in orders_result.data:
        items_html = ""
        for item in order.get("order_items", []):
            item_total_price = Decimal(item.get("total_price", 0))
            
            # Main item row
            items_html += f'<tr><td class="main-item-desc">{item["quantity"]}X {item["product_name"]}</td><td class="main-item-price">{format_currency(item_total_price)}</td></tr>'
            
            # Options rows
            for option in item.get("options", []):
                opt_details = option.get("product_options")
                if opt_details:
                    items_html += f'<tr><td class="sub-item-desc">- {opt_details["name"]}</td><td class="sub-item-price"></td></tr>'


            # Notes row
            if item.get("notes"):
                items_html += f'<tr><td class="item-notes" colspan="2">NOTES: {item["notes"]}</td></tr>'

        created_dt = datetime.fromisoformat(order['created_at'])
        order_date = created_dt.strftime('%d/%m/%Y')
        order_time = created_dt.strftime('%I:%M %p')

        # OFFLINE RECEIPT
        if order['order_type'] == 'offline':
            receipt_html = f"""
                <div class="receipt-container">
                    <div class="header">
                        <img src="{logo_svg_uri}" alt="Logo" class="logo">
                        <div class="title">ORDER RECEIPT</div>
                    </div>
                    <div class="display-number">#{order.get('display_number', 'N/A')}</div>
                    <div class="order-info">
                        <div><strong>ORDER:</strong> {order.get('order_number', '')}</div>
                        <div><strong>BATCH:</strong> {order.get('batch_id', 'N/A')}</div>
                        <div><strong>TYPE:</strong> {(order.get('order_placement_type') or '').upper()}</div>
                        <div><strong>CUSTOMER:</strong> {order.get('customer_name', 'WALK-IN')}</div>
                        <div><strong>DATE:</strong> {order_date}</div>
                        <div><strong>TIME:</strong> {order_time}</div>
                    </div>
                    <table><tbody>{items_html}</tbody></table>
                    <div class="totals-section">
                        <div class="totals-row"><span>SUBTOTAL</span><span>{format_currency(order.get('subtotal'))}</span></div>
                        <div class="totals-row"><span>TAX</span><span>{format_currency(order.get('tax'))}</span></div>
                        <div class="totals-row total-final"><span>TOTAL</span><span>{format_currency(order.get('total'))}</span></div>
                    </div>
                    <div class="footer"><div>YOU'RE NOT JUST A CUSTOMER..... YOU'RE FAMILY</div></div>
                </div>
            """
        # ONLINE RECEIPT
        else:
            customer_name = order.get('website_customers', {}).get('full_name', 'N/A') if order.get('website_customers') else order.get('customer_name', 'N/A')
            customer_phone = order.get('website_customers', {}).get('phone', 'N/A') if order.get('website_customers') else order.get('customer_phone', 'N/A')
            customer_address = order.get('customer_addresses', {}).get('full_address', 'N/A') if order.get('customer_addresses') else 'N/A'
            
            receipt_html = f"""
                <div class="receipt-container">
                    <div class="header">
                        <img src="{logo_svg_uri}" alt="Logo" class="logo">
                        <div class="title">ORDER RECEIPT</div>
                    </div>
                    <div class="customer-details">
                        <div><strong>TO:</strong> {customer_name}</div>
                        <div><strong>PHONE:</strong> {customer_phone}</div>
                        <div><strong>ADDRESS:</strong> {customer_address}</div>
                    </div>
                    <div class="order-info">
                        <div><strong>ORDER:</strong> {order.get('order_number', '')}</div>
                        <div><strong>BATCH:</strong> {order.get('batch_id', 'N/A')}</div>
                        <div><strong>TYPE:</strong> {(order.get('order_placement_type') or '').upper()}</div>
                        <div><strong>DATE:</strong> {order_date}</div>
                        <div><strong>TIME:</strong> {order_time}</div>
                    </div>
                    <table><tbody>{items_html}</tbody></table>
                    <div class="totals-section">
                        <div class="totals-row"><span>SUBTOTAL</span><span>{format_currency(order.get('subtotal'))}</span></div>
                        <div class="totals-row"><span>TAX</span><span>{format_currency(order.get('tax'))}</span></div>
                        <div class="totals-row total-final"><span>TOTAL</span><span>{format_currency(order.get('total'))}</span></div>
                    </div>
                    <div class="footer"><div>YOU'RE NOT JUST A CUSTOMER..... YOU'RE FAMILY</div></div>
                </div>
            """
        all_receipts_html.append(receipt_html)

    # Combine all receipts into a single HTML document
    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            @media print {{
                * {{ -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }}
                body {{ margin: 0; padding: 0; }}
                .receipt-container {{ page-break-after: always; }}
                @page {{ size: 80mm auto; margin: 0; }}
            }}
            body {{ font-family: Arial, sans-serif; text-transform: uppercase; }}
            .receipt-container {{ width: 80mm; margin: 0 auto; padding: 10mm; box-sizing: border-box; }}
            .header {{ text-align: center; margin-bottom: 20px; border-bottom: 3px solid #000; padding-bottom: 15px; }}
            .logo {{ width: 36mm; height: auto; margin-bottom: 10px; }}
            .title {{ font-size: 24px; font-weight: 900; margin: 10px 0; }}
            .order-info {{ font-size: 14px; font-weight: 700; margin: 15px 0; padding: 10px; background: #f0f0f0; border: 2px solid #000; }}
            .display-number {{ font-size: 48px; font-weight: 900; text-align: center; margin: 20px 0; padding: 20px; border: 4px solid #000; background: #000; color: #fff; }}
            .customer-details {{ font-size: 16px; font-weight: 700; margin: 20px 0; padding: 15px; border: 3px solid #000; line-height: 1.5; }}
            table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
            td {{ padding: 8px 0; border-bottom: 1px dashed #000; vertical-align: top; }}
            .main-item-desc {{ font-weight: 900; font-size: 18px; border-top: 3px solid #000; padding-top: 12px; }}
            .main-item-price {{ font-weight: 900; font-size: 18px; border-top: 3px solid #000; padding-top: 12px; text-align: right; }}
            .sub-item-desc {{ padding-left: 25px !important; font-size: 16px; }}
            .sub-item-price {{ font-size: 16px; text-align: right; }}
            .item-notes {{ padding-left: 25px !important; font-style: italic; font-size: 14px; border-bottom: 1px dashed #000; }}
            .totals-section {{ margin-top: 20px; padding-top: 15px; border-top: 3px solid #000; }}
            .totals-row {{ display: flex; justify-content: space-between; font-size: 16px; font-weight: 700; padding: 4px 0; }}
            .total-final {{ font-size: 20px; font-weight: 900; border-top: 3px solid #000; margin-top: 5px; padding-top: 10px; }}
            .footer {{ text-align: center; margin-top: 25px; padding-top: 15px; border-top: 3px solid #000; font-size: 12px; font-weight: 700; }}
        </style>
    </head>
    <body>
        {''.join(all_receipts_html)}
    </body>
    </html>
    """
    
    return HTMLResponse(content=full_html)





@router.get("/batches/{batch_id}/details")
async def get_batch_details(
    batch_id: str,
    current_user: dict = Depends(require_chef_staff)
):
    """Get detailed information about a specific batch"""
    orders = supabase_admin.table("orders").select("*").eq("batch_id", batch_id).execute()
    
    if not orders.data:
        raise HTTPException(status_code=404, detail="Batch not found")

    # Collect IDs for batch fetching
    order_ids = [o["id"] for o in orders.data]
    customer_ids = [o["website_customer_id"] for o in orders.data if o.get("website_customer_id")]
    address_ids = [o["delivery_address_id"] for o in orders.data if o.get("delivery_address_id")]
    
    # Batch fetch items
    items_result = supabase_admin.table("order_items").select("*").in_("order_id", order_ids).execute()
    items_by_order = {}
    all_item_ids = []
    for item in items_result.data:
        oid = item["order_id"]
        if oid not in items_by_order:
            items_by_order[oid] = []
        items_by_order[oid].append(item)
        all_item_ids.append(item["id"])
    
    # Batch fetch options
    options_map = {}
    if all_item_ids:
        options_result = supabase_admin.table("order_item_options").select("*, product_options(*)").in_("order_item_id", all_item_ids).execute()
        for opt in options_result.data:
            item_id = opt["order_item_id"]
            if item_id not in options_map:
                options_map[item_id] = []
            options_map[item_id].append(opt)
    
    # Batch fetch customers
    customers_map = {}
    if customer_ids:
        customers_result = supabase_admin.table("website_customers").select("*").in_("id", customer_ids).execute()
        customers_map = {c["id"]: c for c in customers_result.data}
    
    # Batch fetch addresses
    addresses_map = {}
    if address_ids:
        addresses_result = supabase_admin.table("customer_addresses").select("*, delivery_areas(name, estimated_time)").in_("id", address_ids).execute()
        addresses_map = {a["id"]: a for a in addresses_result.data}
    
    # Build formatted orders
    formatted_orders = []
    total_items = 0
    total_amount = 0
    
    for order in orders.data:
        # Attach items with options
        order_items = items_by_order.get(order["id"], [])
        for item in order_items:
            item["options"] = options_map.get(item["id"], [])
        
        order["order_items"] = order_items
        
        # Customer info
        customer = customers_map.get(order.get("website_customer_id"))
        customer_info = {
            "name": order.get("customer_name") or (customer.get("full_name") if customer else None),
            "phone": order.get("customer_phone") or (customer.get("phone") if customer else None),
            "email": order.get("customer_email") or (customer.get("email") if customer else None)
        }
        
        # Address info
        address = addresses_map.get(order.get("delivery_address_id"))
        delivery_info = address if address else None
        
        formatted_orders.append({
            "order_id": order["id"],
            "order_number": order["order_number"],
            "display_number": order.get("display_number"),
            "status": order["status"],
            "order_type": order["order_type"],
            "order_placement_type": order.get("order_placement_type"),
            "items": order_items,
            "customer_info": customer_info,
            "delivery_info": delivery_info,
            "subtotal": order["subtotal"],
            "tax": order["tax"],
            "total": order["total"],
            "created_at": order["created_at"]
        })
        
        total_items += len(order_items)
        total_amount += float(order["total"])
    
    return {
        "batch_id": batch_id,
        "orders": formatted_orders,
        "summary": {
            "order_count": len(formatted_orders),
            "total_items": total_items,
            "total_amount": total_amount,
            "status": orders.data[0]["status"],
            "batch_created_at": orders.data[0]["batch_created_at"]
        }
    }