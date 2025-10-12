from fastapi import APIRouter, HTTPException, Depends, Request, Query
from typing import List, Optional, Dict, Any
from decimal import Decimal
import json
import uuid
import requests
from uuid import uuid4
from pydantic import BaseModel
from datetime import datetime, timedelta
from fastapi import BackgroundTasks

from .models import *
from .services import CustomerService, DeliveryService, CartService, AddressService
# from ..database import supabase
from ..database import supabase, supabase_admin
from ..services.redis import redis_client
from .services import MonnifyService
from .services import CartService
from ..api.sales_service import SalesService
from ..config import settings
from .services import CustomerService, DeliveryService, CartService, AddressService

router = APIRouter(prefix="/website", tags=["Website"])









# @router.get("/products")
# async def get_products_for_website(
#     category_id: Optional[str] = None,
#     min_price: Optional[float] = None,
#     max_price: Optional[float] = None,
#     limit: int = Query(50, le=100),
#     offset: int = Query(0, ge=0)
# ):
#     cache_key = f"website:products:{category_id}:{min_price}:{max_price}:{limit}:{offset}"
    
#     cached = redis_client.get(cache_key)
#     if cached:
#         return cached

#     query = supabase_admin.table("products").select(
#         "id, name, variant_name, price, description, image_url, units, low_stock_threshold, has_options, category_id, categories(id, name), product_options(id, name, display_order)"
#     ).eq("is_available", True).eq("product_type", "main").neq("status", "out_of_stock")

#     if category_id:
#         query = query.eq("category_id", category_id)
#     if min_price:
#         query = query.gte("price", min_price)
#     if max_price:
#         query = query.lte("price", max_price)
    
#     query = query.range(offset, offset + limit - 1)
#     products_result = query.execute()
    
#     if not products_result.data:
#         redis_client.set(cache_key, [], 300)
#         return []
    
#     # Batch fetch extras
#     product_ids = [p["id"] for p in products_result.data]
#     extras_result = supabase_admin.table("products").select("*").in_("main_product_id", product_ids).eq("is_available", True).execute()
    
#     # Map extras by main_product_id
#     extras_map = {}
#     for extra in extras_result.data:
#         if extra["main_product_id"] not in extras_map:
#             extras_map[extra["main_product_id"]] = []
#         extras_map[extra["main_product_id"]].append(extra)
    
#     products = []
#     for product in products_result.data:
#         display_name = product["name"]
#         if product.get("variant_name"):
#             display_name += f" - {product['variant_name']}"
        
#         category = product.get("categories", {})
#         if not category:
#             category = {"id": product.get("category_id"), "name": "Uncategorized"}
        
#         formatted_options = [
#             {
#                 "id": opt["id"],
#                 "name": opt["name"]
#             }
#             for opt in sorted(product.get("product_options") or [], 
#                             key=lambda x: (x.get("display_order", 999), x.get("name", "")))
#         ]
        
#         # Format extras
#         formatted_extras = []
#         for extra in extras_map.get(product["id"], []):
#             extra_display_name = extra["name"]
#             if extra.get("variant_name"):
#                 extra_display_name += f" - {extra['variant_name']}"
            
#             formatted_extras.append({
#                 "id": extra["id"],
#                 "name": extra_display_name,
#                 "price": float(extra["price"]),
#                 "description": extra["description"],
#                 "image_url": extra["image_url"],
#                 "available_stock": extra["units"],
#                 "low_stock_threshold": extra["low_stock_threshold"],
#                 "status": extra["status"]
#             })
        
#         products.append({
#             "id": product["id"],
#             "name": display_name,
#             "price": float(product["price"]),
#             "description": product["description"],
#             "image_url": product["image_url"],
#             "available_stock": product["units"],
#             "low_stock_threshold": product["low_stock_threshold"],
#             "has_options": product.get("has_options", False),
#             "options": formatted_options,
#             "extras": formatted_extras,
#             "category": category
#         })
    
#     sorted_data = sorted(products, key=lambda x: (x["category"]["name"], x["name"]))
    
#     redis_client.set(cache_key, sorted_data, 300)
#     return sorted_data



@router.get("/products")
async def get_products_for_website(
    category_id: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0)
):
    cache_key = f"website:products:{category_id}:{min_price}:{max_price}:{limit}:{offset}"
    cached = redis_client.get(cache_key)
    if cached:
        return cached

    query = supabase_admin.table("products").select("*").eq("is_available", True).eq("product_type", "main")

    if category_id:
        query = query.eq("category_id", category_id)
    if min_price:
        query = query.gte("price", min_price)
    if max_price:
        query = query.lte("price", max_price)
    
    main_products = query.range(offset, offset + limit - 1).execute().data
    
    if not main_products:
        redis_client.set(cache_key, [], 300)
        return []
    
    main_product_ids = [p["id"] for p in main_products]
    category_ids = list(set([p["category_id"] for p in main_products if p.get("category_id")]))
    
    # Batch fetch categories
    categories_result = supabase_admin.table("categories").select("id, name").in_("id", category_ids).execute()
    categories_map = {c["id"]: c for c in categories_result.data}
    
    # Batch fetch extras
    extras_result = supabase_admin.table("products").select("*").in_("main_product_id", main_product_ids).eq("is_available", True).execute()
    extras_map = {}
    for extra in extras_result.data:
        main_id = extra["main_product_id"]
        if main_id not in extras_map:
            extras_map[main_id] = []
        extras_map[main_id].append(extra)
    
    # Batch fetch options
    options_result = supabase_admin.table("product_options").select("*").in_("product_id", main_product_ids).execute()
    options_map = {}
    for opt in options_result.data:
        pid = opt["product_id"]
        if pid not in options_map:
            options_map[pid] = []
        options_map[pid].append(opt)
    
    # Format response
    result = []
    for product in main_products:
        display_name = product["name"]
        if product.get("variant_name"):
            display_name += f" - {product['variant_name']}"
        
        category = categories_map.get(product.get("category_id"), {"id": None, "name": "Uncategorized"})
        
        options = [
            {"id": o["id"], "name": o["name"]}
            for o in sorted(options_map.get(product["id"], []), 
                          key=lambda x: (x.get("display_order", 999), x.get("name", "")))
        ]
        
        extras = []
        for extra in extras_map.get(product["id"], []):
            extra_name = extra["name"]
            if extra.get("variant_name"):
                extra_name += f" - {extra['variant_name']}"
            extras.append({
                "id": extra["id"],
                "name": extra_name,
                "price": float(extra["price"]),
                "description": extra["description"],
                "image_url": extra["image_url"],
                "available_stock": extra["units"],
                "low_stock_threshold": extra["low_stock_threshold"]
            })
        
        result.append({
            "id": product["id"],
            "name": display_name,
            "price": float(product["price"]),
            "description": product["description"],
            "image_url": product["image_url"],
            "available_stock": product["units"],
            "low_stock_threshold": product["low_stock_threshold"],
            "has_options": product.get("has_options", False),
            "options": options,
            "extras": extras,
            "category": category
        })
    
    # result.sort(key=lambda x: (x["category"]["name"], x["name"]))
    
    redis_client.set(cache_key, result, 300)
    return result



# CREATE INDEX IF NOT EXISTS idx_products_available ON products(is_available, product_type, status);
# CREATE INDEX IF NOT EXISTS idx_products_main_product_id ON products(main_product_id);
# CREATE INDEX IF NOT EXISTS idx_product_options_product_id ON product_options(product_id);


@router.get("/products/{product_id}/current-stock")
async def get_current_stock(product_id: str):
    """Get real-time stock for quantity validation"""
    cache_key = f"product_stock:{product_id}"
    cached = redis_client.get(cache_key)
    if cached:
        return cached
    
    product = supabase_admin.table("products").select("units, low_stock_threshold, status").eq("id", product_id).eq("is_available", True).execute()
    
    if not product.data:
        raise HTTPException(status_code=404, detail="Product not found")
    
    result = {
        "available_stock": product.data[0]["units"],
        "low_stock_threshold": product.data[0]["low_stock_threshold"],
        "is_out_of_stock": product.data[0]["status"] == "out_of_stock"
    }
    
    redis_client.set(cache_key, result, 30)
    return result


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
    print(f"📥 Received data: {verify_data.dict()}")
    
    is_valid = await CustomerService.verify_pin(verify_data.email, verify_data.pin)
    
    if not is_valid:
        print(f"❌ Invalid PIN for {verify_data.email}")
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
                "vat": float(totals["tax"]),
                "total": float(totals["total"])
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))




@router.get("/delivery-areas")
async def get_delivery_areas():
    """Get active delivery areas for customer selection"""
    cached = redis_client.get("website:delivery_areas")
    if cached:
        return cached
    
    result = supabase_admin.table("delivery_areas").select("id, name, delivery_fee, estimated_time").eq("is_active", True).order("name").execute()
    
    redis_client.set("website:delivery_areas", result.data, 300)
    return result.data

@router.post("/delivery/calculate-by-area")
async def calculate_delivery_by_area(area_id: str):
    """Calculate delivery fee and time by area ID"""
    area = supabase_admin.table("delivery_areas").select("*").eq("id", area_id).eq("is_active", True).execute()
    
    if not area.data:
        raise HTTPException(status_code=404, detail="Area not found")
    
    return {
        "area_name": area.data[0]["name"],
        "fee": float(area.data[0]["delivery_fee"]),
        "estimated_time": area.data[0]["estimated_time"]
    }




# @router.post("/checkout/summary")
# async def get_checkout_summary(checkout_data: CheckoutRequest):
#     """Get checkout summary with area-based delivery"""
#     order_summaries = []
#     total_subtotal = Decimal('0')
#     total_vat = Decimal('0')
#     delivery_fees_by_area = {}
    
#     for idx, order in enumerate(checkout_data.orders):
#         if not order.delivery_address_id:
#             raise HTTPException(status_code=400, detail=f"Delivery address required for order {idx + 1}")
        
#         processed_items = await CartService.validate_cart_items([item.dict() for item in order.items])
#         totals = CartService.calculate_order_total(processed_items)
        
#         total_subtotal += totals["subtotal"]
#         total_vat += totals["tax"]
        
#         # Get address with area details
#         address_result = supabase_admin.table("customer_addresses").select("*, delivery_areas(delivery_fee)").eq("id", order.delivery_address_id).execute()
        
#         if not address_result.data:
#             raise HTTPException(status_code=404, detail=f"Address not found for order {idx + 1}")
        
#         address_data = address_result.data[0]
#         area_id = address_data["area_id"]
        
#         if area_id not in delivery_fees_by_area:
#             delivery_fees_by_area[area_id] = {
#                 "fee": Decimal(str(address_data["delivery_areas"]["delivery_fee"])),
#                 "address": address_data["full_address"]
#             }
        
#         order_summaries.append({
#             "order_index": idx,
#             "items": [
#                 {
#                     "product_name": item["product_name"],
#                     "quantity": item["quantity"],
#                     "unit_price": float(item["unit_price"]),
#                     "total_price": float(item["total_price"])
#                 }
#                 for item in processed_items
#             ],
#             "subtotal": float(totals["subtotal"]),
#             "delivery_address": delivery_fees_by_area[area_id]["address"],
#             "delivery_fee": float(delivery_fees_by_area[area_id]["fee"])
#         })
    
#     total_delivery = sum(data["fee"] for data in delivery_fees_by_area.values())
#     grand_total = total_subtotal + total_vat + total_delivery
    
#     return {
#         "orders": order_summaries,
#         "total_subtotal": float(total_subtotal),
#         "total_vat": float(total_vat),
#         "total_delivery": float(total_delivery),
#         "grand_total": float(grand_total)
#     }




@router.post("/checkout/summary")
async def get_checkout_summary(checkout_data: CheckoutRequest):
    """Get checkout summary with area-based delivery"""
    try:
        # Use shared calculation
        totals = await CartService.calculate_checkout_total(
            [order.dict() for order in checkout_data.orders]
        )
        
        # Get order details for display
        order_summaries = []
        for idx, order in enumerate(checkout_data.orders):
            processed_items = await CartService.validate_cart_items([item.dict() for item in order.items])
            order_totals = CartService.calculate_order_total(processed_items)
            
            address = supabase_admin.table("customer_addresses").select("*, delivery_areas(delivery_fee)").eq("id", order.delivery_address_id).execute()
            
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
                "subtotal": float(order_totals["subtotal"]),
                "delivery_address": address.data[0]["full_address"],
                "delivery_fee": float(address.data[0]["delivery_areas"]["delivery_fee"])
            })
        
        return {
            "orders": order_summaries,
            "total_subtotal": totals["subtotal_float"],  # Use float version
            "total_vat": totals["vat_float"],
            "total_delivery": totals["delivery_float"],
            "grand_total": totals["total_float"]
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))




@router.post("/checkout/complete")
async def complete_checkout(
    checkout_data: CheckoutRequest,
    session_token: str = Query(...)
):
    """Complete the checkout process"""
    session_data = redis_client.get(f"customer_session:{session_token}")
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    batch_id = CartService.generate_batch_id()
    batch_created_at = datetime.utcnow().isoformat()
    
    created_orders = []
    all_items = []  # Collect all items for stock deduction
    
    for order in checkout_data.orders:
        processed_items = await CartService.validate_cart_items([item.dict() for item in order.items])
        totals = CartService.calculate_order_total(processed_items)
        all_items.extend(processed_items)  # Add to collection
        
        # Get delivery fee from address area
        address = supabase_admin.table("customer_addresses").select("*, delivery_areas(delivery_fee)").eq("id", order.delivery_address_id).execute()
        delivery_fee = float(address.data[0]["delivery_areas"]["delivery_fee"]) if address.data else 0
        
        order_data = {
            "order_number": f"TEMP-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "order_type": "online",
            "status": "pending",
            "payment_status": "pending",
            "customer_email": session_data.get("customer_email"),
            "subtotal": float(totals["subtotal"]),
            "tax": float(totals["vat"]),
            "delivery_fee": delivery_fee,
            "total": float(totals["total"]) + delivery_fee,
            "website_customer_id": session_data["customer_id"],
            "delivery_address_id": order.delivery_address_id,
            "batch_id": batch_id,
            "batch_created_at": batch_created_at
        }
        
        created_order = supabase_admin.table("orders").insert(order_data).execute()
        order_id = created_order.data[0]["id"]

        datetime_str = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        order_number = f"LEBANST-{datetime_str}-{str(order_id)[-6:].zfill(6)}"
        updated_order = supabase_admin.table("orders").update({"order_number": order_number}).eq("id", order_id).execute()

        created_orders.append(updated_order.data[0])
        
        for item in processed_items:
            item_data = {
                "order_id": order_id,
                "product_id": item["product_id"],
                "product_name": item["product_name"],
                "quantity": item["quantity"],
                "unit_price": float(item["unit_price"]),
                "total_price": float(item["total_price"]),
                "notes": item.get("notes"),
                "is_extra": item.get("is_extra", False)
            }
            result = supabase_admin.table("order_items").insert(item_data).execute()
            order_item_id = result.data[0]["id"]
            
            # Insert multiple options
            for option_id in item.get("option_ids", []):
                supabase_admin.table("order_item_options").insert({
                    "id": str(uuid.uuid4()),
                    "order_item_id": order_item_id,
                    "option_id": option_id
                }).execute()
        
        created_orders.append(updated_order.data[0])
    
    # Deduct stock once for all orders
    await SalesService.deduct_stock_immediately(all_items, session_data["customer_id"])
    
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
    
    # ========== USE SAME CALCULATION AS CHECKOUT ==========
    try:
        calculated_totals = await CartService.calculate_checkout_total(
            [order.dict() for order in payment_data.orders]
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Validate client sent correct total
    if abs(Decimal(str(calculated_totals["total"])) - Decimal(str(payment_data.total_amount))) > Decimal('0.01'):
        raise HTTPException(
            status_code=400, 
            detail=f"Price mismatch. Expected: {calculated_totals['total']}, Got: {payment_data.total_amount}"
        )
    # ========== END VALIDATION ==========
    
    # payment_reference = f"tranx-{datetime.now().strftime('%Y%m%d%H%M%S')}-{str(uuid4())[:6]}"
    payment_reference = f"tranx-{str(uuid4())}"
    
    try:
        account_data = await MonnifyService.create_virtual_account(
            amount=payment_data.total_amount,
            customer_email=payment_data.customer_email,
            customer_name=payment_data.customer_name,
            customer_phone=payment_data.customer_phone,
            payment_reference=payment_reference
        )
        
        payment_session = {
            "payment_reference": payment_reference,
            "customer_id": session_data["customer_id"],
            "orders": [order.dict() for order in payment_data.orders],
            "amount": float(payment_data.total_amount),
            "status": "pending",
            "created_at": datetime.utcnow().isoformat()
        }
        
        redis_client.set(f"payment:{account_data['account_reference']}", payment_session, 3600)
        
        return {
            **account_data,  
            "payment_reference": payment_reference
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))





@router.get("/payment/verify/{account_reference}")  
async def verify_payment(account_reference: str):  
    """Verify payment status"""
    try:
        payment_session = redis_client.get(f"payment:{account_reference}")
        if not payment_session:
            raise HTTPException(status_code=404, detail="Payment session not found")
        
        # ========== DOUBLE PROCESSING CHECK ==========
        if payment_session.get("status") == "completed":
            existing_orders = payment_session.get("orders_created", [])
            
            if existing_orders:
                orders_data = []
                for order_id in existing_orders:
                    order = supabase_admin.table("orders").select("*").eq("id", order_id).execute()
                    if order.data:
                        orders_data.append(order.data[0])
                
                return {
                    "payment_status": "success",
                    "message": "Payment already processed",
                    "orders": orders_data
                }
        # ========== END CHECK ==========
        
        # Verify with Monnify
        if payment_session.get("webhook_status") == "PAID":
            payment_data = await MonnifyService.verify_payment(
                payment_session.get("transaction_reference") or payment_session["payment_reference"]
            )
        else:
            # payment_data = await MonnifyService.verify_payment(payment_session["payment_reference"])
            payment_data = await MonnifyService.verify_payment(account_reference)
            print(f"📊 Full Monnify Response: {payment_data}")
        
        if payment_data["paymentStatus"] == "PAID":

            existing_orders = supabase_admin.table("orders").select("*").eq(
                "payment_reference", payment_session["payment_reference"]
            ).execute()
            
            if existing_orders.data:
                print("✅ Orders already exist for this payment")
                return {
                    "payment_status": "success",
                    "message": "Payment already processed",
                    "orders": existing_orders.data
                }
            # ========== LOCK TO PREVENT RACE CONDITIONS ==========
            processing_lock = f"processing:{account_reference}"
            
            lock_acquired = redis_client.client.set(processing_lock, "locked", ex=60, nx=True)
            
            if not lock_acquired:
                return {
                    "payment_status": "processing",
                    "message": "Payment is being processed, please wait"
                }
            # ========== END LOCK ==========
            
            try:
                created_orders = []
                all_items = []


                batch_id = CartService.generate_batch_id()
                batch_created_at = datetime.utcnow().isoformat()
               
                for order_data in payment_session["orders"]:
                    processed_items = await CartService.validate_cart_items(order_data["items"])
                    totals = CartService.calculate_order_total(processed_items)
                    all_items.extend(processed_items)

                    for item in processed_items:
                        item["option_ids"] = [opt["option_id"] for opt in item.get("options", [])]
                        
                    address = supabase_admin.table("customer_addresses").select("*, delivery_areas(delivery_fee)").eq("id", order_data["delivery_address_id"]).execute()
                    delivery_fee = float(address.data[0]["delivery_areas"]["delivery_fee"]) if address.data else 0
                   
                    order_entry = {
                        # "order_number": f"WEB-{datetime.now().strftime('%Y%m%d')}-{len(created_orders)+1:03d}",
                        "order_number": f"TEMP-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                        "order_type": "online",
                        "status": "confirmed",
                        "payment_status": "paid",
                        "batch_id": batch_id,  
                        "batch_created_at": batch_created_at, 
                        "payment_reference": payment_session["payment_reference"],
                        "monnify_transaction_ref": payment_data.get("transactionReference"),
                        "subtotal": float(totals["subtotal"]),
                        "tax": float(totals["tax"]),
                        "delivery_fee": delivery_fee,
                        "total": float(totals["total"]) + delivery_fee,
                        "website_customer_id": payment_session["customer_id"],
                        "delivery_address_id": order_data["delivery_address_id"],
                        "confirmed_at": datetime.utcnow().isoformat()
                    }
                   
                    created_order = supabase_admin.table("orders").insert(order_entry).execute()
                    order_id = created_order.data[0]["id"]

                    datetime_str = datetime.utcnow().strftime("%Y%m%d%H%M%S")
                    order_number = f"LEBANST-{datetime_str}-{str(order_id)[-6:].zfill(6)}"

                    updated_order = supabase_admin.table("orders").update({
                        "order_number": order_number
                    }).eq("id", order_id).execute()
                   
                    for item in processed_items:
                        item_data = {
                            "order_id": order_id,
                            "product_id": item["product_id"],
                            "product_name": item["product_name"],
                            "quantity": item["quantity"],
                            "unit_price": float(item["unit_price"]),
                            "total_price": float(item["total_price"]),
                            "notes": item.get("notes"),
                            "is_extra": item.get("is_extra", False)
                        }
                        result = supabase_admin.table("order_items").insert(item_data).execute()
                        order_item_id = result.data[0]["id"]
                        
                        for option_id in item.get("option_ids", []):
                            supabase_admin.table("order_item_options").insert({
                                "id": str(uuid.uuid4()),
                                "order_item_id": order_item_id,
                                "option_id": option_id
                            }).execute()
                   
                    created_orders.append(updated_order.data[0])

                await SalesService.deduct_stock_immediately(all_items, payment_session["customer_id"])
               
                # Mark as completed
                payment_session["status"] = "completed"
                payment_session["orders_created"] = [o["id"] for o in created_orders]
                payment_session["completed_at"] = datetime.utcnow().isoformat()
                redis_client.set(f"payment:{account_reference}", payment_session, 86400)
               
                return {
                    "payment_status": "success",
                    "orders": created_orders,
                    "tracking_references": [o["order_number"] for o in created_orders],
                    "payment_details": payment_data
                }
            
            finally:
                redis_client.delete(processing_lock)
       
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




@router.post("/payment/bypass-create")
async def bypass_payment_create(
    payment_data: PaymentRequest,
    session_token: str = Query(...)
):
    """Bypass payment for testing - auto-complete orders"""
    session_data = redis_client.get(f"customer_session:{session_token}")
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")

    if isinstance(session_data, bytes):
        import json
        session_data = json.loads(session_data.decode("utf-8"))

    payment_reference = f"BYPASS-{datetime.now().strftime('%Y%m%d%H%M%S')}-{session_data['customer_id'][:8]}"
    batch_id = CartService.generate_batch_id()
    batch_created_at = datetime.utcnow().isoformat()

    created_orders = []
    all_items = []  # Collect all items outside loop

    for order_data in payment_data.orders:
        processed_items = await CartService.validate_cart_items([item.dict() for item in order_data.items])
        totals = CartService.calculate_order_total(processed_items)
        all_items.extend(processed_items)  # Collect items

        # Get delivery fee from address area
        address = supabase_admin.table("customer_addresses").select("*, delivery_areas(delivery_fee)").eq("id", order_data.delivery_address_id).execute()
        delivery_fee = float(address.data[0]["delivery_areas"]["delivery_fee"]) if address.data else 0

        order_entry = {
            "batch_id": batch_id,
            "batch_created_at": batch_created_at,
            "order_type": "online",
            "status": "confirmed",
            "payment_status": "paid",
            "payment_reference": payment_reference,
            "subtotal": float(totals["subtotal"]),
            "tax": float(totals["vat"]),
            "delivery_fee": delivery_fee,
            "total": float(totals["total"]) + delivery_fee,
            "website_customer_id": session_data["customer_id"],
            "delivery_address_id": order_data.delivery_address_id,
            "confirmed_at": datetime.utcnow().isoformat()
        }

        created_order = supabase_admin.table("orders").insert(order_entry).execute()
        order_id = created_order.data[0]["id"]

        today = datetime.utcnow().strftime("%Y%m%d")
        order_number = f"WEB-{today}-{str(order_id).zfill(3)}"

        updated_order = (
            supabase_admin.table("orders")
            .update({"order_number": order_number})
            .eq("id", order_id)
            .execute()
        )

        for item in processed_items:
            item_data = {
                "order_id": order_id,
                "product_id": item["product_id"],
                "product_name": item["product_name"],
                "quantity": item["quantity"],
                "unit_price": float(item["unit_price"]),
                "total_price": float(item["total_price"]),
                "notes": item.get("notes"),
                "is_extra": item.get("is_extra", False)
            }
            result = supabase_admin.table("order_items").insert(item_data).execute()
            order_item_id = result.data[0]["id"]
            
            # Insert multiple options
            for option_id in item.get("option_ids", []):
                supabase_admin.table("order_item_options").insert({
                    "id": str(uuid.uuid4()),
                    "order_item_id": order_item_id,
                    "option_id": option_id
                }).execute()

        created_orders.append(updated_order.data[0])

    # Deduct stock once after all orders created
    await SalesService.deduct_stock_immediately(all_items, session_data["customer_id"])

    return {
        "payment_status": "success",
        "payment_reference": payment_reference,
        "orders": created_orders,
        "message": "Payment bypassed - orders created successfully",
    }



# @router.post("/payment/webhook")
# async def payment_webhook(request: Request):
#     payload = await request.json()
    
#     payment_reference = payload.get("accountReference")  
#     payment_status = payload["paymentStatus"]
    
#     payment_session = redis_client.get(f"payment:{payment_reference}")
#     if payment_session:
#         payment_session["webhook_status"] = payment_status
#         payment_session["webhook_data"] = payload
#         redis_client.set(f"payment:{payment_reference}", payment_session, 3600)
    
#     return {"status": "success"}



@router.post("/payment/webhook")
async def payment_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle Monnify payment webhook"""
    
    # ========== 1. IP WHITELIST ==========
    client_ip = request.client.host
    
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    
    MONNIFY_WEBHOOK_IP = settings.MONNIFY_WEBHOOK_IP
    if client_ip != MONNIFY_WEBHOOK_IP:
        print(f"⚠️ UNAUTHORIZED WEBHOOK from {client_ip}")
        return {"status": "error", "message": "Unauthorized"}
    
    # ========== 2. PARSE PAYLOAD ==========
    try:
        payload = await request.json()
    except:
        return {"status": "error", "message": "Invalid payload"}
    
    # ========== 3. HASH VALIDATION ==========
    if not MonnifyService.verify_transaction_hash(payload):
        print(f"⚠️ INVALID HASH: {payload}")
        return {"status": "error", "message": "Invalid hash"}
    
    # ========== 4. DUPLICATE CHECK ==========
    transaction_reference = payload.get("transactionReference")
    account_reference = payload.get("accountReference")
    
    duplicate_key = f"webhook_processed:{transaction_reference}"
    if redis_client.get(duplicate_key):
        print(f"ℹ️ Duplicate webhook ignored: {transaction_reference}")
        return {"status": "success", "message": "Already processed"}
    
    redis_client.set(duplicate_key, "processing", 600)
    
    # ========== 5. QUICK RESPONSE ==========
    background_tasks.add_task(
        MonnifyService.process_webhook_payment,
        payload,
        account_reference,
        transaction_reference
    )
    
    return {"status": "success"}
    



@router.get("/orders/history")
async def get_order_history(
    session_token: str = Query(...),
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0)
):
    session_data = redis_client.get(f"customer_session:{session_token}")
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    orders = supabase_admin.table("orders").select("""
        *, 
        customer_addresses(full_address, delivery_areas(name))
    """).eq("website_customer_id", session_data["customer_id"]).in_("status", ["completed", "cancelled"]).order("completed_at", desc=True).range(offset, offset + limit - 1).execute()
    
    # Format items with options and extras
    for order in orders.data:
        items_result = supabase_admin.table("order_items").select("*").eq("order_id", order["id"]).execute()
        
        formatted_items = []
        for item in items_result.data:
            # Fetch options for this item
            options_result = supabase_admin.table("order_item_options").select(
                "*, product_options(id, name)"
            ).eq("order_item_id", item["id"]).execute()
            
            formatted_options = [
                {
                    "option_id": opt["product_options"]["id"],
                    "option_name": opt["product_options"]["name"]
                }
                for opt in options_result.data
            ]
            
            formatted_items.append({
                **item,
                "options": formatted_options
            })
        
        # Separate main items and extras
        main_items = [item for item in formatted_items if not item.get("is_extra")]
        extras = [item for item in formatted_items if item.get("is_extra")]
        
        order["items"] = main_items
        order["extras"] = extras
        order["delivery_fee"] = float(order.get("delivery_fee", 0))
    
    return {
        "orders": orders.data,
        "total_count": len(orders.data),
        "limit": limit,
        "offset": offset
    }



# @router.get("/orders/tracking")
# async def get_all_orders_tracking(session_token: str = Query(...)):
#     """Get tracking status for all customer orders"""
#     session_data = redis_client.get(f"customer_session:{session_token}")
#     if not session_data:
#         raise HTTPException(status_code=401, detail="Invalid session")
    
    
#     orders = supabase_admin.table("orders").select("""
#         *, 
#         customer_addresses(full_address, delivery_areas(name, estimated_time))
#     """).eq("website_customer_id", session_data["customer_id"]).order("created_at", desc=True).execute()
    
#     tracking_orders = []
#     for order_data in orders.data:
#         # Fetch order items
#         order_items = supabase_admin.table("order_items").select("*").eq("order_id", order_data["id"]).execute()
        
#         # Format items with options
#         formatted_items = []
#         for item in order_items.data:
#             options_result = supabase_admin.table("order_item_options").select(
#                 "*, product_options(id, name)"
#             ).eq("order_item_id", item["id"]).execute()
            
#             formatted_options = [
#                 {
#                     "option_id": opt["product_options"]["id"],
#                     "option_name": opt["product_options"]["name"]
#                 }
#                 for opt in options_result.data
#             ]
            
#             formatted_items.append({
#                 **item,
#                 "options": formatted_options
#             })
        
#         # Separate main items and extras
#         main_items = [item for item in formatted_items if not item.get("is_extra")]
#         extras = [item for item in formatted_items if item.get("is_extra")]
        
#         order_status = order_data["status"]
#         tracking_stages = {
#             "payment_confirmation": order_status in ["confirmed", "preparing", "out_for_delivery", "completed"],
#             "processed": order_status in ["preparing", "out_for_delivery", "completed"],
#             "out_for_delivery": order_status in ["out_for_delivery", "completed"]
#         }
        
#         # Get delivery info
#         delivery_info = None
#         delivery_estimate = None
        
#         if order_data.get("customer_addresses"):
#             delivery_info = {
#                 "address": order_data["customer_addresses"]["full_address"],
#                 "estimated_time": order_data["customer_addresses"]["delivery_areas"]["estimated_time"]
#             }
            
#             # Calculate delivery estimate
#             delivery_estimate = DeliveryService.calculate_delivery_estimate(
#                 formatted_items,
#                 order_data["customer_addresses"]["delivery_areas"]["estimated_time"]
#             )
        
#         tracking_orders.append({
#             "order": {
#                 "id": order_data["id"],
#                 "order_number": order_data["order_number"],
#                 "status": order_status,
#                 "total": float(order_data["total"]),
#                 "delivery_fee": float(order_data.get("delivery_fee", 0)),
#                 "created_at": order_data["created_at"],
#                 "monnify_transaction_ref": order_data.get("monnify_transaction_ref"),
#                 "items": main_items,
#                 "extras": extras
#             },
#             "delivery_info": delivery_info,
#             "delivery_estimate": delivery_estimate,
#             "tracking_stages": tracking_stages,
#             "current_stage": (
#                 "out_for_delivery" if order_status == "completed" else
#                 "processed" if order_status == "preparing" else
#                 "payment_confirmation" if order_status == "confirmed" else
#                 "pending"
#             )
#         })
    
#     return {"orders": tracking_orders}


@router.get("/orders/tracking")
async def get_all_orders_tracking(session_token: str = Query(...)):
    """Get tracking status for all customer orders with caching"""
    session_data = redis_client.get(f"customer_session:{session_token}")
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    # Check cache with customer-specific key
    cache_key = f"tracking:{session_data['customer_id']}"
    cached = redis_client.get(cache_key)
    if cached:
        return cached
    
    # Fetch orders with related data
    thirty_mins_ago = (datetime.utcnow() - timedelta(minutes=30)).isoformat()

    orders = supabase_admin.table("orders").select("""
        *, 
        customer_addresses(full_address, delivery_areas(name, estimated_time))
    """).eq("website_customer_id", session_data["customer_id"]).or_(
        f"status.neq.completed,completed_at.gte.{thirty_mins_ago}"
    ).order("created_at", desc=True).execute()
        
    tracking_orders = []
    
    for order_data in orders.data:
        # Fetch order items
        order_items_result = supabase_admin.table("order_items").select("*").eq("order_id", order_data["id"]).execute()
        
        # Format items with options
        formatted_items = []
        for item in order_items_result.data:
            options_result = supabase_admin.table("order_item_options").select(
                "*, product_options(id, name)"
            ).eq("order_item_id", item["id"]).execute()
            
            formatted_options = [
                {
                    "option_id": opt["product_options"]["id"],
                    "option_name": opt["product_options"]["name"]
                }
                for opt in options_result.data
            ]
            
            formatted_items.append({
                **item,
                "options": formatted_options
            })
        
        # Separate main items and extras
        main_items = [item for item in formatted_items if not item.get("is_extra")]
        extras = [item for item in formatted_items if item.get("is_extra")]
        
        order_status = order_data["status"]
        
        # Define tracking stages based on status
        tracking_stages = {
            "payment_confirmation": order_status in ["confirmed", "preparing", "out_for_delivery", "completed"],
            "processed": order_status in ["preparing", "out_for_delivery", "completed"],
            "out_for_delivery": order_status in ["out_for_delivery", "completed"],
            "completed": order_status == "completed"
        }
        
        # Determine current stage
        if order_status == "completed":
            current_stage = "completed"
        elif order_status == "out_for_delivery":
            current_stage = "out_for_delivery"
        elif order_status == "preparing":
            current_stage = "processed"
        elif order_status == "confirmed":
            current_stage = "payment_confirmation"
        else:
            current_stage = "pending"
        
        # Get delivery info
        delivery_info = None
        delivery_estimate = None
        
        if order_data.get("customer_addresses"):
            delivery_info = {
                "address": order_data["customer_addresses"]["full_address"],
                "estimated_time": order_data["customer_addresses"]["delivery_areas"]["estimated_time"]
            }
            
            # Calculate delivery estimate
            delivery_estimate = DeliveryService.calculate_delivery_estimate(
                formatted_items,
                order_data["customer_addresses"]["delivery_areas"]["estimated_time"]
            )
        
        tracking_orders.append({
            "order": {
                "id": order_data["id"],
                "order_number": order_data["order_number"],
                "status": order_status,
                "subtotal": float(order_data.get("subtotal", 0)),
                "tax": float(order_data.get("tax", 0)),
                "total": float(order_data["total"]),
                "delivery_fee": float(order_data.get("delivery_fee", 0)),
                "created_at": order_data["created_at"],
                "confirmed_at": order_data.get("confirmed_at"),
                "preparing_at": order_data.get("preparing_at"),
                "completed_at": order_data.get("completed_at"),
                "monnify_transaction_ref": order_data.get("monnify_transaction_ref"),
                "payment_reference": order_data.get("payment_reference"),
                "items": main_items,
                "extras": extras
            },
            "delivery_info": delivery_info,
            "delivery_estimate": delivery_estimate,
            "tracking_stages": tracking_stages,
            "current_stage": current_stage
        })
    
    result = {"orders": tracking_orders}
    
    # Cache for 30 seconds - short cache for near real-time updates
    redis_client.set(cache_key, result, 30)
    
    return result




@router.get("/search/suggestions")
async def get_search_suggestions(q: str = Query(min_length=2)):
    cache_key = f"search:suggestions:{q}"
    cached = redis_client.get(cache_key)
    if cached:
        return cached
    
    # Single optimized query with joins
    products = supabase_admin.table("products").select("""
        *, 
        categories(*),
        extras:products!main_product_id(*)
    """).eq("is_available", True).neq("status", "out_of_stock").eq("product_type", "main").limit(50).execute()

    # Filter products by search term
    filtered_products = [
        p for p in products.data 
        if q.lower() in p["name"].lower() or 
        (p.get("categories") and q.lower() in p["categories"]["name"].lower())
    ]

    
    def get_relevance_score(product, query):
        score = 0
        name = product["name"].lower()
        query_lower = query.lower()
        
        
        if name == query_lower:
            score += 100
        
        elif name.startswith(query_lower):
            score += 50
       
        elif f" {query_lower} " in f" {name} ":
            score += 40
        
        elif query_lower in name:
            score += 30
        
       
        if product.get("categories") and query_lower in product["categories"]["name"].lower():
            score += 10
        
        return score

    
    sorted_products = sorted(filtered_products, 
        key=lambda p: get_relevance_score(p, q), reverse=True)[:10]
    
    
    result_products = []
    for product in sorted_products:
        display_name = product["name"]
        if product.get("variant_name"):
            display_name += f" - {product['variant_name']}"
        
        category = {"id": None, "name": "Uncategorized"}
        if product.get("categories"):
            category = product["categories"]
        
        
        formatted_extras = []
        for extra in product.get("extras", []):
            extra_display_name = extra["name"]
            if extra.get("variant_name"):
                extra_display_name += f" - {extra['variant_name']}"
            
            formatted_extras.append({
                "id": extra["id"],
                "name": extra_display_name,
                "price": float(extra["price"]),
                "description": extra["description"],
                "image_url": extra["image_url"],
                "available_stock": extra["units"],
                "low_stock_threshold": extra["low_stock_threshold"],
                "status": extra["status"]
            })
        
        result_products.append({
            "id": product["id"],
            "name": display_name,
            "price": float(product["price"]),
            "description": product["description"],
            "image_url": product["image_url"],
            "available_stock": product["units"],
            "low_stock_threshold": product["low_stock_threshold"],
            "category": category,
            "extras": formatted_extras,
            "status": product["status"]
        })
    
    redis_client.set(cache_key, result_products, 60)
    return result_products


@router.get("/banners")
async def get_website_banners():
    """Get active banners for website display"""
    cache_key = "website:banners"
    cached = redis_client.get(cache_key)
    if cached:
        return cached
    
    result = supabase_admin.table("banners").select("*").eq("is_active", True).order("display_order").order("created_at", desc=True).execute()
    
    
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
    

@router.get("/payment/check-transactions/{account_reference}")
async def check_transactions(account_reference: str):
    access_token = await MonnifyService.get_access_token()
    
    response = requests.get(
        f"{settings.MONNIFY_BASE_URL}/api/v2/bank-transfer/reserved-accounts/{account_reference}/transactions",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30
    )
    
    return response.json()