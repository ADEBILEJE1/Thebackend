from fastapi import APIRouter, HTTPException, Depends, Request, Query
from typing import List, Optional, Dict, Any
from decimal import Decimal
import json
from pydantic import BaseModel
from datetime import datetime
from .models import *
from .services import CustomerService, DeliveryService, CartService, AddressService
# from ..database import supabase
from ..database import supabase_admin
from ..services.redis import redis_client
from .services import MonnifyService

router = APIRouter(prefix="/website", tags=["Website"])






# @router.get("/products")
# async def get_products_for_website(
#     category_id: Optional[str] = None,
#     search: Optional[str] = None,
#     min_price: Optional[float] = None,
#     max_price: Optional[float] = None
# ):
#     """Get products for website display"""
#     cache_key = f"website:products:{category_id}:{search}:{min_price}:{max_price}"
#     cached = redis_client.get(cache_key)
#     if cached:
#         return cached
    
#     query = supabase_admin.table("products").select("""
#         id, sku, variant_name, price, description, image_url, units, status, is_available,
#         product_templates(name),
#         categories(id, name)
#     """).eq("is_available", True).neq("status", "out_of_stock")
    
#     if category_id:
#         query = query.eq("category_id", category_id)
    
#     if search:
#         query = query.or_(f"product_templates.name.ilike.%{search}%,categories.name.ilike.%{search}%")
    
#     if min_price:
#         query = query.gte("price", min_price)
    
#     if max_price:
#         query = query.lte("price", max_price)
    
#     result = query.execute()
#     sorted_data = sorted(result.data, key=lambda x: (
#         x.get("categories", {}).get("name", "") if x.get("categories") else "", 
#         x.get("product_templates", {}).get("name", "") if x.get("product_templates") else ""
#     ))
    
#     products = []
#     for product in sorted_data:
#         # Handle missing product_templates
#         template_name = ""
#         if product.get("product_templates") and product["product_templates"]:
#             template_name = product["product_templates"]["name"]
        
#         display_name = template_name
#         if product.get("variant_name"):
#             display_name += f" - {product['variant_name']}" if template_name else product["variant_name"]
        
#         # Fallback if no template name and no variant
#         if not display_name:
#             display_name = f"Product {product['id'][:8]}"
        
#         # Handle missing categories
#         category = {"id": None, "name": "Uncategorized"}
#         if product.get("categories") and product["categories"]:
#             category = product["categories"]
        
#         products.append({
#             "id": product["id"],
#             "name": display_name,
#             "price": float(product["price"]),
#             "description": product["description"],
#             "image_url": product["image_url"],
#             "available_stock": product["units"],
#             "category": category
#         })
    
#     redis_client.set(cache_key, products, 300)
#     return products

@router.get("/products")
async def get_products_for_website(
    category_id: Optional[str] = None,
    search: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None
):
    """Get products for website display"""
    cache_key = f"website:products:{category_id}:{search}:{min_price}:{max_price}"
    cached = redis_client.get(cache_key)
    if cached:
        return cached
    
    # Get products first
    query = supabase_admin.table("products").select("*").eq("is_available", True).neq("status", "out_of_stock")
    
    if category_id:
        query = query.eq("category_id", category_id)
    if min_price:
        query = query.gte("price", min_price)
    if max_price:
        query = query.lte("price", max_price)
    
    products_result = query.execute()
    
    # Manually fetch categories and templates for each product
    for product in products_result.data:
        # Fetch category
        if product["category_id"]:
            category = supabase_admin.table("categories").select("*").eq("id", product["category_id"]).execute()
            product["categories"] = category.data[0] if category.data else None
        else:
            product["categories"] = None
            
        # Fetch product template
        if product["product_template_id"]:
            template = supabase_admin.table("product_templates").select("*").eq("id", product["product_template_id"]).execute()
            product["product_templates"] = template.data[0] if template.data else None
        else:
            product["product_templates"] = None
    
    # Apply search filter after fetching related data
    if search:
        products_result.data = [
            p for p in products_result.data 
            if (p.get("product_templates") and search.lower() in p["product_templates"]["name"].lower()) or
               (p.get("categories") and search.lower() in p["categories"]["name"].lower())
        ]
    
    # Rest of your existing processing code...
    sorted_data = sorted(products_result.data, key=lambda x: (
        x.get("categories", {}).get("name", "") if x.get("categories") else "", 
        x.get("product_templates", {}).get("name", "") if x.get("product_templates") else ""
    ))
    
    products = []
    for product in sorted_data:
        template_name = ""
        if product.get("product_templates") and product["product_templates"]:
            template_name = product["product_templates"]["name"]
        
        display_name = template_name
        if product.get("variant_name"):
            display_name += f" - {product['variant_name']}" if template_name else product["variant_name"]
        
        if not display_name:
            display_name = f"Product {product['id'][:8]}"
        
        category = {"id": None, "name": "Uncategorized"}
        if product.get("categories") and product["categories"]:
            category = product["categories"]
        
        products.append({
            "id": product["id"],
            "name": display_name,
            "price": float(product["price"]),
            "description": product["description"],
            "image_url": product["image_url"],
            "available_stock": product["units"],
            "category": category
        })
    
    redis_client.set(cache_key, products, 300)
    return products







@router.get("/categories")
async def get_categories_for_website():
    """Get all active categories"""
    cached = redis_client.get("website:categories")
    if cached:
        return cached
    
    result = supabase_admin.table("categories").select("id, name, description, image_url").eq("is_active", True).order("name").execute()
    
    redis_client.set("website:categories", result.data, 600)
    
    return result.data

@router.get("/auth/session")
async def get_customer_session(session_token: str = Query(...)):
    """Get customer from session token"""
    session_data = redis_client.get(f"customer_session:{session_token}")
    
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    customer = supabase_admin.table("website_customers").select("*").eq("id", session_data["customer_id"]).execute()
    
    if not customer.data:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    return customer.data[0]




@router.post("/addresses/check-email")
async def check_email_for_address(email_data: EmailCheck):
    """Check email and handle authentication flow"""
    return await CustomerService.check_email_and_handle_auth(
        email_data.email, 
        email_data.phone, 
        email_data.full_name
    )

@router.post("/addresses/verify-and-save")
async def verify_pin_and_save_address(verify_data: PinVerifyAndAddress):
    """Verify PIN and save address"""
    is_valid = await CustomerService.verify_pin(verify_data.email, verify_data.pin)
    
    if not is_valid:
        raise HTTPException(status_code=400, detail="Invalid or expired PIN")
    
    customer = supabase_admin.table("website_customers").select("*").eq("email", verify_data.email).execute()
    session_token = await CustomerService.create_customer_session(customer.data[0]["id"])
    
    address = await AddressService.save_customer_address(
        customer.data[0]["id"],
        verify_data.address_data
    )
    
    return {
        "session_token": session_token,
        "customer": customer.data[0],
        "address": address
    }



# @router.post("/addresses")
# async def save_address(
#     address_data: AddressCreate,
#     session_token: str = Query(...)
# ):
#     """Save address with existing session"""
#     session_data = redis_client.get(f"customer_session:{session_token}")
#     if not session_data:
#         raise HTTPException(status_code=401, detail="Invalid session")
    
#     address = await AddressService.save_customer_address(
#         session_data["customer_id"],
#         address_data.dict()
#     )
    
#     return address


@router.post("/addresses")
async def save_address(
    address_data: AddressCreate,
    session_token: str = Query(...)
):
    """Save address with existing session"""
    session_data = redis_client.get(f"customer_session:{session_token}")
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    customer = supabase_admin.table("website_customers").select("*").eq("id", session_data["customer_id"]).execute()
    
    if not customer.data:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    address = await AddressService.save_customer_address(
        session_data["customer_id"],
        address_data.dict()
    )
    
    return {
        "address": address,
        "customer_phone": customer.data[0].get("phone"),
        "customer_email": customer.data[0]["email"]
    }


@router.get("/addresses")
async def get_addresses(session_token: str = Query(...)):
    """Get customer addresses"""
    session_data = redis_client.get(f"customer_session:{session_token}")
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    addresses = await AddressService.get_customer_addresses(session_data["customer_id"])
    return addresses


# Cart and Checkout
@router.post("/cart/validate")
async def validate_cart(items: List[CartItem]):
    """Validate cart items and return pricing"""
    try:
        processed_items = await CartService.validate_cart_items([item.dict() for item in items])
        totals = CartService.calculate_order_total(processed_items)
        
        return {
            "items": processed_items,
            "totals": {
                "subtotal": float(totals["subtotal"]),
                "vat": float(totals["vat"]),
                "total": float(totals["total"])
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/delivery/calculate")
async def calculate_delivery(
    latitude: float,
    longitude: float
):
    """Calculate delivery fee and time"""
    distance = DeliveryService.calculate_distance(
        DeliveryService.RESTAURANT_LAT,
        DeliveryService.RESTAURANT_LNG,
        latitude,
        longitude
    )
    
    fee = DeliveryService.calculate_delivery_fee(distance)
    time = DeliveryService.estimate_delivery_time(distance)
    
    return {
        "distance_km": round(distance, 2),
        "fee": float(fee),
        "estimated_time": time
    }



@router.post("/checkout/summary")
async def get_checkout_summary(checkout_data: CheckoutRequest):
    """Get checkout summary with all calculations"""
    import uuid
    
    order_summaries = []
    total_subtotal = Decimal('0')
    total_vat = Decimal('0')
    delivery_fees_by_address = {}
    
    for idx, order in enumerate(checkout_data.orders):
        # Validate delivery address is required
        if not order.delivery_address_id:
            raise HTTPException(
                status_code=400, 
                detail=f"Delivery address is required for order {idx + 1}"
            )
        
        # Validate UUID format
        try:
            uuid.UUID(order.delivery_address_id)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid delivery address ID format for order {idx + 1}"
            )
        
        # Validate items
        processed_items = await CartService.validate_cart_items([item.dict() for item in order.items])
        totals = CartService.calculate_order_total(processed_items)
        
        total_subtotal += totals["subtotal"]
        total_vat += totals["vat"]
        
        # Get delivery address
        address_result = supabase_admin.table("customer_addresses").select("*").eq("id", order.delivery_address_id).execute()
        
        if not address_result.data:
            raise HTTPException(
                status_code=404, 
                detail=f"Delivery address not found for order {idx + 1}"
            )
        
        address_data = address_result.data[0]
        address_key = f"{address_data['latitude']}:{address_data['longitude']}"
        
        if address_key not in delivery_fees_by_address:
            distance = DeliveryService.calculate_distance(
                DeliveryService.RESTAURANT_LAT,
                DeliveryService.RESTAURANT_LNG,
                address_data["latitude"],
                address_data["longitude"]
            )
            delivery_fees_by_address[address_key] = {
                "fee": DeliveryService.calculate_delivery_fee(distance),
                "address": address_data["full_address"]
            }
        
        order_summaries.append({
            "order_index": idx,
            "items": [
                {
                    "product_name": item["product_name"],
                    "quantity": item["quantity"],
                    "unit_price": float(item["unit_price"]),
                    "total_price": float(item["total_price"])
                }
                for item in processed_items
            ],
            "subtotal": float(totals["subtotal"]),
            "delivery_address": delivery_fees_by_address[address_key]["address"],
            "delivery_fee": float(delivery_fees_by_address[address_key]["fee"])
        })
    
    total_delivery = sum(data["fee"] for data in delivery_fees_by_address.values())
    grand_total = total_subtotal + total_vat + total_delivery
    
    return {
        "orders": order_summaries,
        "total_subtotal": float(total_subtotal),
        "total_vat": float(total_vat),
        "total_delivery": float(total_delivery),
        "grand_total": float(grand_total)
    }


@router.post("/checkout/complete")
async def complete_checkout(
    checkout_data: CheckoutRequest,
    session_token: str = Query(...)
):
    """Complete the checkout process"""
    session_data = redis_client.get(f"customer_session:{session_token}")
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    # Create orders in the system
    created_orders = []
    
    for order in checkout_data.orders:
        # Validate and process items
        processed_items = await CartService.validate_cart_items([item.dict() for item in order.items])
        totals = CartService.calculate_order_total(processed_items)
        
        # Create order
        order_data = {
            "order_number": f"WEB-{datetime.now().strftime('%Y%m%d')}-{len(created_orders)+1:03d}",
            "order_type": "online",
            "status": "pending",
            "payment_status": "pending",
            "customer_email": session_data.get("customer_email"),
            "subtotal": float(totals["subtotal"]),
            "tax": float(totals["vat"]),
            "total": float(totals["total"]),
            "website_customer_id": session_data["customer_id"]
        }
        
        created_order = supabase_admin.table("orders").insert(order_data).execute()
        order_id = created_order.data[0]["id"]
        
        # Create order items
        for item in processed_items:
            item_data = {
                "order_id": order_id,
                "product_id": item["product_id"],
                "product_name": item["product_name"],
                "quantity": item["quantity"],
                "unit_price": float(item["unit_price"]),
                "total_price": float(item["total_price"]),
                "notes": item.get("notes")
            }
            supabase_admin.table("order_items").insert(item_data).execute()
        
        created_orders.append(created_order.data[0])
    
    return {
        "message": "Orders created successfully",
        "orders": created_orders
    }



@router.post("/payment/create-account")
async def create_payment_account(
    payment_data: PaymentRequest,
    session_token: str = Query(...)
):
    """Create virtual account for payment"""
    session_data = redis_client.get(f"customer_session:{session_token}")
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    # Generate unique payment reference
    payment_reference = f"PAY-{datetime.now().strftime('%Y%m%d%H%M%S')}-{session_data['customer_id'][:8]}"
    
    try:
        # Create virtual account
        account_data = await MonnifyService.create_virtual_account(
            payment_reference=payment_reference,
            amount=payment_data.total_amount,
            customer_email=payment_data.customer_email,
            customer_name=payment_data.customer_name
        )
        
        # Store payment session
        payment_session = {
            "payment_reference": payment_reference,
            "customer_id": session_data["customer_id"],
            "orders": [order.dict() for order in payment_data.orders],
            "amount": float(payment_data.total_amount),
            "status": "pending",
            "created_at": datetime.utcnow().isoformat()
        }
        
        redis_client.set(f"payment:{payment_reference}", payment_session, 3600)  # 1 hour
        
        return account_data
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/payment/verify/{payment_reference}")
async def verify_payment(payment_reference: str):
   """Verify payment status"""
   try:
       payment_session = redis_client.get(f"payment:{payment_reference}")
       if not payment_session:
           raise HTTPException(status_code=404, detail="Payment session not found")
       
       payment_data = await MonnifyService.verify_payment(payment_reference)
       
       if payment_data["paymentStatus"] == "PAID":
           created_orders = []
           
           for order_data in payment_session["orders"]:
               processed_items = await CartService.validate_cart_items(order_data["items"])
               totals = CartService.calculate_order_total(processed_items)
               
               order_entry = {
                   "order_number": f"WEB-{datetime.now().strftime('%Y%m%d')}-{len(created_orders)+1:03d}",
                   "order_type": "online",
                   "status": "confirmed",
                   "payment_status": "paid",
                   "payment_reference": payment_reference,
                   "subtotal": float(totals["subtotal"]),
                   "tax": float(totals["vat"]),
                   "total": float(totals["total"]),
                   "website_customer_id": payment_session["customer_id"],
                   "confirmed_at": datetime.utcnow().isoformat()
               }
               
               created_order = supabase_admin.table("orders").insert(order_entry).execute()
               order_id = created_order.data[0]["id"]
               
               for item in processed_items:
                   item_data = {
                       "order_id": order_id,
                       "product_id": item["product_id"],
                       "product_name": item["product_name"],
                       "quantity": item["quantity"],
                       "unit_price": float(item["unit_price"]),
                       "total_price": float(item["total_price"])
                   }
                   supabase_admin.table("order_items").insert(item_data).execute()
               
               created_orders.append(created_order.data[0])
           
           payment_session["status"] = "completed"
           payment_session["orders_created"] = [o["id"] for o in created_orders]
           redis_client.set(f"payment:{payment_reference}", payment_session, 3600)
           
           return {
               "payment_status": "success",
               "orders": created_orders,
               "payment_details": payment_data
           }
       
       elif payment_data["paymentStatus"] == "PENDING":
           return {
               "payment_status": "pending",
               "message": "Payment is still pending"
           }
       
       else:
           return {
               "payment_status": "failed",
               "message": "Payment failed or expired"
           }
           
   except Exception as e:
       raise HTTPException(status_code=500, detail=str(e))

@router.post("/payment/webhook")
async def payment_webhook(request: Request):
    """Handle Monnify payment webhook"""
    try:
        payload = await request.json()
        
        payment_reference = payload["transactionReference"]
        payment_status = payload["paymentStatus"]
        
        # Update payment session
        payment_session = redis_client.get(f"payment:{payment_reference}")
        if payment_session:
            payment_session["webhook_status"] = payment_status
            payment_session["webhook_data"] = payload
            redis_client.set(f"payment:{payment_reference}", payment_session, 3600)
        
        return {"status": "success"}
        
    except Exception as e:
        return {"status": "error", "message": str(e)}
    
@router.get("/orders/history")
async def get_order_history(
    session_token: str = Query(...),
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0)
):
    """Get customer order history"""
    session_data = redis_client.get(f"customer_session:{session_token}")
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    # Get orders with items
    orders = supabase_admin.table("orders").select("""
        id, order_number, status, payment_status, total, created_at,
        order_items(product_name, quantity, unit_price, total_price)
    """).eq("website_customer_id", session_data["customer_id"]).order(
        "created_at", desc=True
    ).range(offset, offset + limit - 1).execute()
    
    return {
        "orders": orders.data,
        "total_count": len(orders.data),
        "limit": limit,
        "offset": offset
    }

@router.get("/orders/{order_id}")
async def get_order_details(
    order_id: str,
    session_token: str = Query(...)
):
    """Get specific order details"""
    session_data = redis_client.get(f"customer_session:{session_token}")
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    order = supabase_admin.table("orders").select("""
        *, order_items(*), customer_addresses(*)
    """).eq("id", order_id).eq("website_customer_id", session_data["customer_id"]).execute()
    
    if not order.data:
        raise HTTPException(status_code=404, detail="Order not found")
    
    return order.data[0]


@router.get("/orders/{order_id}/tracking")
async def get_order_tracking(
    order_id: str,
    session_token: str = Query(...)
):
    """Get order tracking status"""
    session_data = redis_client.get(f"customer_session:{session_token}")
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    # Get order
    order = supabase_admin.table("orders").select("*").eq("id", order_id).eq("website_customer_id", session_data["customer_id"]).execute()
    
    if not order.data:
        raise HTTPException(status_code=404, detail="Order not found")
    
    order_status = order.data[0]["status"]
    
    tracking_stages = {
        "payment_confirmation": order_status in ["confirmed", "preparing", "completed"],
        "processed": order_status == "completed",
        "out_for_delivery": order_status == "completed"
    }
    
    return {
        "order_number": order.data[0]["order_number"],
        "current_status": order_status,
        "tracking_stages": tracking_stages,
        "estimated_delivery": "30-45 minutes" if order_status == "completed" else None
    }



@router.get("/search/suggestions")
async def get_search_suggestions(q: str = Query(min_length=2)):
    cache_key = f"search:suggestions:{q}"
    cached = redis_client.get(cache_key)
    if cached:
        return cached
    
    # Product name suggestions
    products = supabase_admin.table("products").select(
        "product_templates(name), price"
    ).ilike("product_templates.name", f"{q}%").limit(3).execute()
    
    # If query is numeric, also search by price
    if q.isdigit():
        price = int(q)
        price_products = supabase_admin.table("products").select(
            "product_templates(name), price"
        ).eq("price", price).limit(3).execute()
        
        # Combine results
        all_products = products.data + price_products.data
    else:
        all_products = products.data
    
    # Categories
    categories = supabase_admin.table("categories").select("name").ilike("name", f"{q}%").limit(3).execute()
    
    # Filter out products with null templates
    product_list = []
    for p in all_products:
        if p.get("product_templates") and p["product_templates"]:
            product_list.append({
                "name": p["product_templates"]["name"], 
                "price": float(p["price"])
            })
    
    result = {
        "products": product_list,
        "categories": [c["name"] for c in categories.data]
    }
    
    redis_client.set(cache_key, result, 300)
    return result

@router.get("/banners")
async def get_website_banners():
    """Get active banners for website display"""
    cache_key = "website:banners"
    cached = redis_client.get(cache_key)
    if cached:
        return cached
    
    result = supabase_admin.table("banners").select("*").eq("is_active", True).order("display_order").order("created_at", desc=True).execute()
    
    # Cache for 2 minutes
    redis_client.set(cache_key, result.data, 120)
    return result.data

@router.patch("/addresses/{address_id}")
async def update_address(
    address_id: str,
    update_data: AddressUpdate,
    session_token: str = Query(...)
):
    """Update existing address"""
    session_data = redis_client.get(f"customer_session:{session_token}")
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    try:
        updated_address = await AddressService.update_customer_address(
            address_id, 
            session_data["customer_id"], 
            update_data.dict(exclude_unset=True)
        )
        return updated_address
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.delete("/addresses/{address_id}")
async def delete_address(
    address_id: str,
    session_token: str = Query(...)
):
    """Delete address"""
    session_data = redis_client.get(f"customer_session:{session_token}")
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    success = await AddressService.delete_customer_address(address_id, session_data["customer_id"])
    if not success:
        raise HTTPException(status_code=404, detail="Address not found")
    
    return {"message": "Address deleted successfully"}

@router.patch("/addresses/{address_id}/set-default")
async def set_default_address(
    address_id: str,
    session_token: str = Query(...)
):
    """Set address as default"""
    session_data = redis_client.get(f"customer_session:{session_token}")
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    try:
        updated_address = await AddressService.set_default_address(address_id, session_data["customer_id"])
        return updated_address
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))