from fastapi import APIRouter, HTTPException, status, Depends, Request, BackgroundTasks, Query
from typing import List, Optional,  Dict, Any
from datetime import datetime, date, timedelta
from decimal import Decimal
import random
import uuid
from collections import defaultdict
from fastapi import Security, HTTPException, Depends
from fastapi.security import APIKeyHeader

import pytz
NIGERIA_TZ = pytz.timezone('Africa/Lagos')

from ..config import settings
from .sales_service import SalesService
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, validator, EmailStr
from ..models.user import UserRole
from ..core.permissions import (
    get_current_user,
    require_super_admin,
    require_manager_up,
    require_staff,
    require_sales_staff
)
from ..core.activity_logger import log_activity
from ..core.rate_limiter import default_limiter
from ..services.redis import redis_client
from ..database import supabase, supabase_admin
from ..api.websocket import notify_order_update
from ..website.services import CartService




class SalesTargetCreate(BaseModel):
    period: str = Field(..., pattern="^(daily|weekly|monthly)$")
    orders_target: int = Field(..., gt=0)
    revenue_target: Decimal = Field(..., gt=0)

class DateRangeFilter(BaseModel):
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    days: Optional[int] = Field(None, ge=1, le=365)

class OfflineOrderCreate(BaseModel):
    items: List[Dict[str, Any]]
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    payment_method: str = Field(..., pattern="^(cash|card|transfer)$")
    order_placement_type: str = Field(..., pattern="^(dine_in|takeaway)$")
    notes: Optional[str] = None

class OrderConfirm(BaseModel):
    payment_confirmed: bool

class RefundRequest(BaseModel):
    order_id: str
    items: List[Dict[str, Any]] 
    refund_reason: str
    notes: Optional[str] = None



router = APIRouter(prefix="/sales", tags=["Sales Dashboard"])


def format_currency(amount):
    """Helper function to format a number as Nigerian Naira currency."""
    if amount is None:
        return ""
    return f"N{Decimal(amount):,.2f}"
    

def get_nigerian_time():
    return datetime.utcnow().replace(tzinfo=pytz.UTC).astimezone(NIGERIA_TZ)



# Main Sales Dashboard
@router.get("/dashboard")
async def get_sales_dashboard(
    request: Request,
    current_user: dict = Depends(require_sales_staff)
):
    """Get unified sales dashboard - same view for all sales staff"""
    await default_limiter.check_rate_limit(request, current_user["id"])
    
    dashboard_data = await SalesService.get_sales_dashboard_overview(current_user["role"])
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "view", "sales_dashboard", None, None, request
    )
    
    return dashboard_data









# @router.get("/products")
# async def get_products_for_website(
#     category_id: Optional[str] = None,
#     search: Optional[str] = None,
#     min_price: Optional[float] = None,
#     max_price: Optional[float] = None
# ):
#     cache_key = f"website:products:{category_id}:{search}:{min_price}:{max_price}"
#     cached = redis_client.get(cache_key)
#     if cached:
#         return cached

#     query = supabase_admin.table("products").select("*, categories(*)").eq("is_available", True).eq("product_type", "main")

#     if category_id:
#         query = query.eq("category_id", category_id)
#     if min_price:
#         query = query.gte("price", min_price)
#     if max_price:
#         query = query.lte("price", max_price)
    
#     products_result = query.execute()
    
#     if not products_result.data:
#         redis_client.set(cache_key, [], 300)
#         return []
    
#     # Batch fetch extras and options
#     product_ids = [p["id"] for p in products_result.data]
    
#     extras_result = supabase_admin.table("products").select("*").in_("main_product_id", product_ids).eq("is_available", True).execute()
#     options_result = supabase_admin.table("product_options").select("*").in_("product_id", product_ids).execute()
    
#     # Map extras by main_product_id
#     extras_map = {}
#     for extra in extras_result.data:
#         if extra["main_product_id"] not in extras_map:
#             extras_map[extra["main_product_id"]] = []
#         extras_map[extra["main_product_id"]].append(extra)
    
#     # Map options by product_id
#     options_map = {}
#     for opt in options_result.data:
#         if opt["product_id"] not in options_map:
#             options_map[opt["product_id"]] = []
#         options_map[opt["product_id"]].append(opt)
    
#     # Apply search filter
#     if search:
#         search_lower = search.lower()
#         products_result.data = [
#             p for p in products_result.data 
#             if search_lower in p["name"].lower() or
#                (p.get("categories") and search_lower in p["categories"]["name"].lower())
#         ]
    
#     # Format response
#     products = []
#     for product in products_result.data:
#         display_name = product["name"]
#         if product.get("variant_name"):
#             display_name += f" - {product['variant_name']}"
        
#         category = product.get("categories") or {"id": None, "name": "Uncategorized"}
        
#         # Format extras
#         formatted_extras = []
#         for extra in extras_map.get(product["id"], []):
#             extra_name = extra["name"]
#             if extra.get("variant_name"):
#                 extra_name += f" - {extra['variant_name']}"
#             formatted_extras.append({
#                 "id": extra["id"],
#                 "name": extra_name,
#                 "price": float(extra["price"]),
#                 "description": extra["description"],
#                 "image_url": extra["image_url"],
#                 "available_stock": extra["units"],
#                 "low_stock_threshold": extra["low_stock_threshold"]
#             })
        
#         # Format options
#         formatted_options = []
#         for opt in sorted(options_map.get(product["id"], []), 
#                          key=lambda x: (x.get("display_order", 999), x.get("name", ""))):
#             formatted_options.append({
#                 "id": opt["id"],
#                 "name": opt["name"],
#                 "price_modifier": float(opt.get("price_modifier", 0))
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
    search: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None
):
    cache_key = f"website:products:{category_id}:{search}:{min_price}:{max_price}"
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
    
    products_result = query.execute()
    
    if not products_result.data:
        redis_client.set(cache_key, [], 300)
        return []
    
    # Batch fetch all related data
    product_ids = [p["id"] for p in products_result.data]
    category_ids = list(set([p["category_id"] for p in products_result.data if p.get("category_id")]))
    
    categories_result = supabase_admin.table("categories").select("id, name").in_("id", category_ids).execute()
    extras_result = supabase_admin.table("products").select("*").in_("main_product_id", product_ids).eq("is_available", True).execute()
    options_result = supabase_admin.table("product_options").select("*").in_("product_id", product_ids).execute()
    
    # Map related data
    categories_map = {c["id"]: c for c in categories_result.data}
    extras_map = {}
    for extra in extras_result.data:
        if extra["main_product_id"] not in extras_map:
            extras_map[extra["main_product_id"]] = []
        extras_map[extra["main_product_id"]].append(extra)
    
    options_map = {}
    for opt in options_result.data:
        if opt["product_id"] not in options_map:
            options_map[opt["product_id"]] = []
        options_map[opt["product_id"]].append(opt)
    
    # Apply search filter
    if search:
        search_lower = search.lower()
        products_result.data = [
            p for p in products_result.data 
            if search_lower in p["name"].lower() or
               (p.get("category_id") and search_lower in categories_map.get(p["category_id"], {}).get("name", "").lower())
        ]
    
    # Format response
    products = []
    for product in products_result.data:
        display_name = product["name"]
        if product.get("variant_name"):
            display_name += f" - {product['variant_name']}"
        
        category = categories_map.get(product.get("category_id"), {"id": None, "name": "Uncategorized"})
        
        # Format extras
        formatted_extras = []
        for extra in extras_map.get(product["id"], []):
            extra_name = extra["name"]
            if extra.get("variant_name"):
                extra_name += f" - {extra['variant_name']}"
            formatted_extras.append({
                "id": extra["id"],
                "name": extra_name,
                "price": float(extra["price"]),
                "description": extra["description"],
                "image_url": extra["image_url"],
                "available_stock": extra["units"],
                "low_stock_threshold": extra["low_stock_threshold"]
            })
        
        # Format options
        formatted_options = []
        for opt in sorted(options_map.get(product["id"], []), 
                         key=lambda x: (x.get("display_order", 999), x.get("name", ""))):
            formatted_options.append({
                "id": opt["id"],
                "name": opt["name"],
                "price_modifier": float(opt.get("price_modifier", 0))
            })
        
        products.append({
            "id": product["id"],
            "name": display_name,
            "price": float(product["price"]),
            "description": product["description"],
            "image_url": product["image_url"],
            "available_stock": product["units"],
            "low_stock_threshold": product["low_stock_threshold"],
            "has_options": product.get("has_options", False),
            "options": formatted_options,
            "extras": formatted_extras,
            "category": category
        })
    
    redis_client.set(cache_key, products, 300)
    return products



#     -- Products indexes for sales queries
# CREATE INDEX IF NOT EXISTS idx_products_available_type ON products(is_available, product_type) WHERE is_available = true;
# CREATE INDEX IF NOT EXISTS idx_products_main_product_available ON products(main_product_id, is_available) WHERE is_available = true;
# CREATE INDEX IF NOT EXISTS idx_products_category_available ON products(category_id, is_available) WHERE is_available = true;
# CREATE INDEX IF NOT EXISTS idx_products_price ON products(price);

# -- Product options index
# CREATE INDEX IF NOT EXISTS idx_product_options_product_display ON product_options(product_id, display_order);

# -- Categories index
# CREATE INDEX IF NOT EXISTS idx_categories_active ON categories(is_active) WHERE is_active = true;




@router.get("/products/search")
async def search_products_for_sales(
    search: str = Query(..., min_length=2),
    current_user: dict = Depends(require_sales_staff)
):
    """
    Search for products for sales orders. Optimized for speed.
    Returns data in the same format as the main /sales/products endpoint.
    """
    cache_key = f"sales:products:search:{search.lower().strip()}"
    cached = redis_client.get(cache_key)
    if cached:
        return cached

    search_term = f"%{search.lower().strip()}%"
    
    
    query = supabase_admin.table("products").select("*") \
        .eq("is_available", True) \
        .eq("product_type", "main") \
        .ilike("name", search_term)
    
    products_result = query.limit(50).execute() 
    
    if not products_result.data:
        redis_client.set(cache_key, [], 300)
        return []
    
    
    product_ids = [p["id"] for p in products_result.data]
    category_ids = list(set([p["category_id"] for p in products_result.data if p.get("category_id")]))
    
    categories_result = supabase_admin.table("categories").select("id, name").in_("id", category_ids).execute()
    extras_result = supabase_admin.table("products").select("*").in_("main_product_id", product_ids).eq("is_available", True).execute()
    options_result = supabase_admin.table("product_options").select("*").in_("product_id", product_ids).execute()
    
    # Map related data for quick lookups
    categories_map = {c["id"]: c for c in categories_result.data}
    extras_map = defaultdict(list)
    for extra in extras_result.data:
        extras_map[extra["main_product_id"]].append(extra)
    
    options_map = defaultdict(list)
    for opt in options_result.data:
        options_map[opt["product_id"]].append(opt)
    
    # Format response to match the existing /sales/products endpoint
    products = []
    for product in products_result.data:
        display_name = product["name"]
        if product.get("variant_name"):
            display_name += f" - {product['variant_name']}"
        
        category = categories_map.get(product.get("category_id"), {"id": None, "name": "Uncategorized"})
        
        formatted_extras = []
        for extra in extras_map.get(product["id"], []):
            extra_name = extra["name"]
            if extra.get("variant_name"):
                extra_name += f" - {extra['variant_name']}"
            formatted_extras.append({
                "id": extra["id"],
                "name": extra_name,
                "price": float(extra["price"]),
                "description": extra["description"],
                "image_url": extra["image_url"],
                "available_stock": extra["units"],
                "low_stock_threshold": extra["low_stock_threshold"]
            })
        
        formatted_options = []
        for opt in sorted(options_map.get(product["id"], []), 
                         key=lambda x: (x.get("display_order", 999), x.get("name", ""))):
            formatted_options.append({
                "id": opt["id"],
                "name": opt["name"],
                "price_modifier": float(opt.get("price_modifier", 0))
            })
        
        products.append({
            "id": product["id"],
            "name": display_name,
            "price": float(product["price"]),
            "description": product["description"],
            "image_url": product["image_url"],
            "available_stock": product["units"],
            "low_stock_threshold": product["low_stock_threshold"],
            "has_options": product.get("has_options", False),
            "options": formatted_options,
            "extras": formatted_extras,
            "category": category
        })
    
    redis_client.set(cache_key, products, 300)
    return products


@router.get("/categories")
async def get_categories_for_orders(
    current_user: dict = Depends(require_sales_staff)
):
    """Get categories for order creation"""
    cached = redis_client.get("sales:categories")
    if cached:
        return cached
    
    result = supabase_admin.table("categories").select("*").eq("is_active", True).order("name").execute()
    
    redis_client.set("sales:categories", result.data, 300)
    return result.data


# Revenue Analytics
@router.get("/analytics/revenue")
async def get_revenue_analytics(
    request: Request,
    days: int = 30,
    current_user: dict = Depends(require_sales_staff)
):
    """Get unified revenue analytics"""
    if days > 365:
        raise HTTPException(status_code=400, detail="Maximum 365 days allowed")
    
    revenue_data = await SalesService.get_revenue_analytics(days=days)
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "view", "revenue_analytics", None, {"days": days}, request
    )
    
    return revenue_data

# Staff Performance (Manager+ only)
@router.get("/analytics/performance")
async def get_staff_performance(
    request: Request,
    days: int = 30,
    staff_id: Optional[str] = None,
    current_user: dict = Depends(require_manager_up)
):
    """Get sales staff performance metrics"""
    if days > 365:
        raise HTTPException(status_code=400, detail="Maximum 365 days allowed")
    
    performance_data = await SalesService.get_staff_performance(
        days=days,
        user_id=staff_id
    )
    
    # Log activity
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "view", "staff_performance", staff_id, {"days": days}, request
    )
    
    return performance_data

# Customer Analytics
@router.get("/analytics/customers")
async def get_customer_analytics(
    request: Request,
    days: int = 30,
    current_user: dict = Depends(require_manager_up)
):
    """Get customer behavior and analytics"""
    if days > 365:
        raise HTTPException(status_code=400, detail="Maximum 365 days allowed")
    
    customer_data = await SalesService.get_customer_analytics(days=days)
    
    return customer_data

# Product Sales Analysis with Inventory Integration
@router.get("/analytics/products-inventory")
async def get_products_with_inventory_analysis(
    request: Request,
    days: int = 30,
    current_user: dict = Depends(require_sales_staff)
):
    """Get product sales performance integrated with current inventory levels"""
    if days > 365:
        raise HTTPException(status_code=400, detail="Maximum 365 days allowed")
    
    # Get integrated product analysis
    product_data = await SalesService.get_product_sales_analysis(days=days)
    
    # Log activity
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "view", "products_inventory_analysis", None, {"days": days}, request
    )
    
    return product_data

# Quick Stock Alerts for Sales Staff
@router.get("/alerts/stock")
async def get_sales_stock_alerts(
    request: Request,
    current_user: dict = Depends(require_sales_staff)
):
    """Get critical stock alerts relevant to sales staff"""
    cache_key = "sales:stock:alerts"
    cached = redis_client.get(cache_key)
    if cached:
        return cached
    
    # Get products that are selling but have stock issues
    product_data = await SalesService.get_product_sales_analysis(days=7)  # Last 7 days
    
    # Extract critical alerts
    critical_alerts = []
    
    # Out of stock bestsellers
    for item in product_data["inventory_insights"]["unavailable_bestsellers"]:
        critical_alerts.append({
            "type": "out_of_stock_bestseller",
            "priority": "critical",
            "product_name": item["product_name"],
            "message": f"{item['product_name']} is out of stock but sold {item['quantity_sold']} units in 7 days",
            "daily_sales": item["daily_average_sales"],
            "recommended_action": "Stop taking orders, inform customers"
        })
    
    # Low stock high sellers
    for item in product_data["inventory_insights"]["critical_reorder_needed"]:
        if item["reorder_urgency"] == "critical":
            critical_alerts.append({
                "type": "critical_reorder",
                "priority": "high",
                "product_name": item["product_name"],
                "message": f"{item['product_name']} has only {item['current_stock']} units left",
                "stock_coverage": item["stock_coverage_days"],
                "recommended_action": f"Limit sales to {int(item['daily_average_sales'] * 2)} per day"
            })
    
    alerts_data = {
        "critical_alerts": critical_alerts,
        "summary": {
            "total_alerts": len(critical_alerts),
            "out_of_stock_bestsellers": len([a for a in critical_alerts if a["type"] == "out_of_stock_bestseller"]),
            "critical_reorders": len([a for a in critical_alerts if a["type"] == "critical_reorder"])
        },
        "recommendations": product_data["sales_recommendations"]["immediate_actions"][:5],
        "timestamp": get_nigerian_time().isoformat()
    }
    
    # Cache for 2 minutes
    redis_client.set(cache_key, alerts_data, 120)
    
    return alerts_data

# Live Sales Metrics
@router.get("/live")
async def get_live_sales_metrics(
    request: Request,
    current_user: dict = Depends(require_sales_staff)
):
    """Get real-time sales metrics for live dashboard"""
    live_data = await SalesService.get_live_metrics()
    
    return live_data




@router.get("/financial-report")
async def get_financial_report(
    request: Request,
    start_date: date = Query(...),
    end_date: date = Query(...),
    current_user: dict = Depends(require_manager_up)
):
    """Generate comprehensive financial report"""
    if (end_date - start_date).days > 365:
        raise HTTPException(status_code=400, detail="Maximum 365 days range allowed")
    
    if start_date > end_date:
        raise HTTPException(status_code=400, detail="Start date must be before end date")
    
    financial_data = await SalesService.generate_financial_report(start_date, end_date)
    
    # Log activity
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "generate", "financial_report", None, 
        {"start_date": str(start_date), "end_date": str(end_date)}, 
        request
    )
    
    return financial_data


# Sales Targets Management
@router.get("/targets")
async def get_sales_targets(
    request: Request,
    period: str = "monthly",  # daily, weekly, monthly
    current_user: dict = Depends(require_manager_up)
):
    """Get sales targets and progress"""
    if period not in ["daily", "weekly", "monthly"]:
        raise HTTPException(status_code=400, detail="Period must be daily, weekly, or monthly")
    
    # Get current period dates
    today = date.today()
    if period == "daily":
        start_date = today
        end_date = today
    elif period == "weekly":
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=6)
    else:  # monthly
        start_date = today.replace(day=1)
        next_month = start_date.replace(month=start_date.month + 1) if start_date.month < 12 else start_date.replace(year=start_date.year + 1, month=1)
        end_date = next_month - timedelta(days=1)
    
    # Get sales targets from database (you'd need a targets table)
    # For now, using placeholder values
    targets = {
        "daily": {"orders": 50, "revenue": 2000},
        "weekly": {"orders": 300, "revenue": 12000},
        "monthly": {"orders": 1200, "revenue": 48000}
    }
    
    current_target = targets[period]
    
    # Get actual performance
    orders_result = supabase_admin.table("orders").select("*").gte("created_at", start_date.isoformat()).lte("created_at", f"{end_date.isoformat()}T23:59:59").neq("status", "cancelled").execute()
    
    orders = orders_result.data
    actual_orders = len(orders)
    actual_revenue = sum(float(o["total"]) for o in orders)
    
    # Calculate progress
    order_progress = (actual_orders / current_target["orders"] * 100) if current_target["orders"] > 0 else 0
    revenue_progress = (actual_revenue / current_target["revenue"] * 100) if current_target["revenue"] > 0 else 0
    
    return {
        "period": period,
        "date_range": {"start": start_date, "end": end_date},
        "targets": current_target,
        "actual": {
            "orders": actual_orders,
            "revenue": round(actual_revenue, 2)
        },
        "progress": {
            "orders_percent": round(order_progress, 2),
            "revenue_percent": round(revenue_progress, 2),
            "on_track": order_progress >= 75 and revenue_progress >= 75
        }
    }

@router.post("/targets")
async def set_sales_targets(
    request: Request,
    period: str,
    orders_target: int,
    revenue_target: float,
    current_user: dict = Depends(require_manager_up)
):
    """Set sales targets for specified period"""
    if period not in ["daily", "weekly", "monthly"]:
        raise HTTPException(status_code=400, detail="Period must be daily, weekly, or monthly")
    
    if orders_target <= 0 or revenue_target <= 0:
        raise HTTPException(status_code=400, detail="Targets must be positive values")
    
    # Store targets (you'd implement a targets table)
    # For now, just return success message
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "update", "sales_targets", None, 
        {"period": period, "orders": orders_target, "revenue": revenue_target}, 
        request
    )
    
    return {
        "message": f"{period.title()} sales targets updated successfully",
        "targets": {
            "period": period,
            "orders": orders_target,
            "revenue": revenue_target
        }
    }

# Peak Hours Analysis
@router.get("/analytics/peak-hours")
async def get_peak_hours_analysis(
    request: Request,
    days: int = 7,
    current_user: dict = Depends(require_sales_staff)
):
    """Analyze peak sales hours and patterns"""
    if days > 90:
        raise HTTPException(status_code=400, detail="Maximum 90 days allowed")
    
    end_date = get_nigerian_time()
    start_date = end_date - timedelta(days=days)
    
    # Get orders in date range
    orders_result = supabase.table("orders").select("*").gte("created_at", start_date.isoformat()).neq("status", "cancelled").execute()
    
    orders = orders_result.data
    
    # Analyze by hour
    hourly_data = {}
    daily_data = {}
    
    for order in orders:
        order_datetime = datetime.fromisoformat(order["created_at"])
        hour = order_datetime.hour
        day_name = order_datetime.strftime("%A")
        
        if hour not in hourly_data:
            hourly_data[hour] = {"orders": 0, "revenue": 0}
        if day_name not in daily_data:
            daily_data[day_name] = {"orders": 0, "revenue": 0}
        
        hourly_data[hour]["orders"] += 1
        hourly_data[hour]["revenue"] += float(order["total"])
        
        daily_data[day_name]["orders"] += 1
        daily_data[day_name]["revenue"] += float(order["total"])
    
    # Find peak hours
    peak_hour_orders = max(hourly_data.items(), key=lambda x: x[1]["orders"])[0] if hourly_data else 0
    peak_hour_revenue = max(hourly_data.items(), key=lambda x: x[1]["revenue"])[0] if hourly_data else 0
    
    # Convert to lists
    hourly_breakdown = [
        {"hour": hour, **data, "revenue": round(data["revenue"], 2)}
        for hour, data in sorted(hourly_data.items())
    ]
    
    daily_breakdown = [
        {"day": day, **data, "revenue": round(data["revenue"], 2)}
        for day, data in daily_data.items()
    ]
    
    return {
        "period": {"days": days, "start": start_date.date(), "end": end_date.date()},
        "peak_analysis": {
            "peak_hour_by_orders": peak_hour_orders,
            "peak_hour_by_revenue": peak_hour_revenue,
            "busiest_day": max(daily_data.items(), key=lambda x: x[1]["orders"])[0] if daily_data else None,
            "highest_revenue_day": max(daily_data.items(), key=lambda x: x[1]["revenue"])[0] if daily_data else None
        },
        "hourly_breakdown": hourly_breakdown,
        "daily_breakdown": daily_breakdown
    }

# Order Completion Rate Analysis
@router.get("/analytics/completion-rates")
async def get_completion_rates(
    request: Request,
    days: int = 30,
    current_user: dict = Depends(require_sales_staff)
):
    """Analyze order completion and cancellation rates"""
    if days > 365:
        raise HTTPException(status_code=400, detail="Maximum 365 days allowed")
    
    end_date = get_nigerian_time()
    start_date = end_date - timedelta(days=days)
    
    # Get orders with status breakdown
    orders_result = supabase_admin.table("orders").select("*").gte("created_at", start_date.isoformat()).execute()
    
    orders = orders_result.data
    
    # Status breakdown
    status_counts = {}
    for order in orders:
        status = order["status"]
        if status not in status_counts:
            status_counts[status] = 0
        status_counts[status] += 1
    
    total_orders = len(orders)
    
    # Calculate rates
    completion_rate = (status_counts.get("completed", 0) / total_orders * 100) if total_orders > 0 else 0
    cancellation_rate = (status_counts.get("cancelled", 0) / total_orders * 100) if total_orders > 0 else 0
    
    # Daily completion trends
    daily_completion = {}
    for order in orders:
        order_date = order["created_at"][:10]
        if order_date not in daily_completion:
            daily_completion[order_date] = {"total": 0, "completed": 0, "cancelled": 0}
        
        daily_completion[order_date]["total"] += 1
        if order["status"] == "completed":
            daily_completion[order_date]["completed"] += 1
        elif order["status"] == "cancelled":
            daily_completion[order_date]["cancelled"] += 1
    
    daily_trends = [
        {
            "date": date,
            **data,
            "completion_rate": round((data["completed"] / data["total"] * 100), 2) if data["total"] > 0 else 0,
            "cancellation_rate": round((data["cancelled"] / data["total"] * 100), 2) if data["total"] > 0 else 0
        }
        for date, data in sorted(daily_completion.items())
    ]
    
    return {
        "period": {"days": days, "start": start_date.date(), "end": end_date.date()},
        "overall_rates": {
            "completion_rate": round(completion_rate, 2),
            "cancellation_rate": round(cancellation_rate, 2),
            "total_orders": total_orders
        },
        "status_breakdown": status_counts,
        "daily_trends": daily_trends,
        "recommendations": [
            "Investigate high cancellation days" if cancellation_rate > 15 else "Cancellation rate is healthy",
            "Excellent completion rate" if completion_rate > 85 else "Focus on reducing order cancellations"
        ]
    }

@router.get("/online-orders")
async def get_online_orders(
    request: Request,
    current_user: dict = Depends(require_sales_staff)
):
    """Get confirmed online orders waiting to be pushed to kitchen"""
    result = supabase_admin.table("orders").select("*, order_items(*)").eq("order_type", "online").eq("status", "confirmed").order("confirmed_at").execute()
    
    return result.data

@router.post("/online-orders/{order_id}/push-to-kitchen")
async def push_order_to_kitchen(
    order_id: str,
    request: Request,
    current_user: dict = Depends(require_sales_staff)
):
    """Push confirmed online order to kitchen"""
    order = supabase_admin.table("orders").select("*, order_items(*)").eq("id", order_id).eq("status", "confirmed").execute()

    if not order.data:
        raise HTTPException(status_code=404, detail="Order not found or already processed")

    # Fetch options for each item
    for item in order.data[0]["order_items"]:
        options_result = supabase_admin.table("order_item_options").select("*, product_options(*)").eq("order_item_id", item["id"]).execute()
        item["options"] = options_result.data
    
    supabase_admin.table("orders").update({
        "status": "transit",
        # "preparing_at": get_nigerian_time().isoformat()
    }).eq("id", order_id).execute()
    
    
    from ..api.websocket import notify_order_update
    await notify_order_update(order_id, "new_order", order.data[0])
    
    # Enhanced logging
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "push_to_kitchen", "order", order_id, 
        {
            "order_number": order.data[0]["order_number"],
            "order_total": order.data[0]["total"],
            "items_count": len(order.data[0]["order_items"])
        }, 
        request
    )
    
    return {"message": "Order pushed to kitchen successfully"}


@router.get("/analytics/staff/{staff_id}")
async def get_staff_analytics(
    staff_id: str,
    request: Request,
    days: int = 30,
    current_user: dict = Depends(require_manager_up)
):
    """Get individual staff performance analytics"""
    if days > 365:
        raise HTTPException(status_code=400, detail="Maximum 365 days allowed")
    
    analytics_data = await SalesService.get_individual_staff_analytics(staff_id, days)
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "view", "staff_analytics", staff_id, {"days": days}, request
    )
    
    return analytics_data

@router.get("/analytics/all-staff")
async def get_all_staff_analytics(
    request: Request,
    days: int = 30,
    current_user: dict = Depends(require_manager_up)
):
    """Get analytics for all sales staff"""
    if days > 365:
        raise HTTPException(status_code=400, detail="Maximum 365 days allowed")
    
    # Get all sales staff
    staff_result = supabase.table("profiles").select("*").eq("role", "sales").eq("is_active", True).execute()
    
    all_staff_analytics = []
    for staff in staff_result.data:
        staff_analytics = await SalesService.get_individual_staff_analytics(staff["id"], days)
        staff_analytics["staff_email"] = staff["email"]
        all_staff_analytics.append(staff_analytics)
    
    # Sort by revenue
    all_staff_analytics.sort(key=lambda x: x["performance"]["total_revenue"], reverse=True)
    
    return {
        "period": {"days": days},
        "staff_analytics": all_staff_analytics,
        "team_totals": {
            "total_revenue": sum(s["performance"]["total_revenue"] for s in all_staff_analytics),
            "total_orders": sum(s["performance"]["total_orders"] for s in all_staff_analytics),
            "top_performer": all_staff_analytics[0]["staff_email"] if all_staff_analytics else None
        }
    }



@router.get("/products/{product_id}/current-stock")
async def get_current_stock_for_sales(
    product_id: str,
    current_user: dict = Depends(require_sales_staff)
):
    """Get real-time stock for sales order validation for frontend"""
    cache_key = f"sales_stock:{product_id}"
    cached = redis_client.get(cache_key)
    if cached:
        return cached
    
    product = supabase.table("products").select("units, status, low_stock_threshold").eq("id", product_id).eq("is_available", True).execute()
    
    if not product.data:
        raise HTTPException(status_code=404, detail="Product not found")
    
    result = {
        "available_stock": product.data[0]["units"],
        "low_stock_threshold": product.data[0]["low_stock_threshold"],
        "is_out_of_stock": product.data[0]["status"] == "out_of_stock",
        "is_low_stock": product.data[0]["status"] == "low_stock"
    }
    
    redis_client.set(cache_key, result, 15)
    return result



@router.post("/orders/validate-stock")
async def validate_stock_before_order(
    items: List[Dict[str, Any]],
    current_user: dict = Depends(require_sales_staff)
):
    """Live stock validation before creating order"""
    stock_issues = []
    warnings = []
    
    for item in items:
        product = supabase.table("products").select("name, units, status, low_stock_threshold").eq("id", item["product_id"]).execute()
        
        if not product.data:
            stock_issues.append(f"Product {item['product_id']} not found")
            continue
            
        product_data = product.data[0]
        
        if product_data["status"] == "out_of_stock":
            stock_issues.append(f"{product_data['name']} is out of stock")
        elif product_data["units"] < item["quantity"]:
            stock_issues.append(f"{product_data['name']} - only {product_data['units']} available, requested {item['quantity']}")
        elif product_data["status"] == "low_stock":
            warnings.append(f"{product_data['name']} is low stock ({product_data['units']} remaining)")
    
    return {
        "valid": len(stock_issues) == 0,
        "issues": stock_issues,
        "warnings": warnings
    }


@router.post("/orders/validate-cart")
async def validate_sales_cart(
    items: List[Dict[str, Any]],
    current_user: dict = Depends(require_sales_staff)
):
    """Validate cart items for sales order for frontend"""
    stock_validation = await validate_stock_before_order(items, current_user)
    
    try:
        processed_items = await SalesService.validate_sales_cart_items(items)
        totals = CartService.calculate_order_total(processed_items)
        
        return {
            "items": processed_items,
            "totals": {
                "subtotal": float(totals["subtotal"]),
                "tax": float(totals["tax"]),
                "total": float(totals["total"])
            },
            "stock_warnings": stock_validation["warnings"],
            "stock_valid": stock_validation["valid"],
            "stock_issues": stock_validation["issues"]
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    


# In sales.py - Update create_offline_order endpoint

@router.post("/orders")
async def create_offline_order(
    order_data: OfflineOrderCreate,
    request: Request,
    current_user: dict = Depends(require_sales_staff)
):
    """Create offline order with new tax system"""
    stock_validation = await validate_stock_before_order(order_data.items, current_user)
    if not stock_validation["valid"]:
        raise HTTPException(status_code=400, detail={
            "message": "Stock validation failed", 
            "issues": stock_validation["issues"]
        })
    
    # processed_items = await SalesService.validate_sales_cart_items(order_data.items)
    # totals = CartService.calculate_order_total(processed_items)

    processed_items = await SalesService.validate_sales_cart_items(order_data.items)

    subtotal = sum(item["total_price"] for item in processed_items)
    tax = sum(Decimal(str(item.get("tax_per_unit", 0))) * item["quantity"] for item in processed_items)
    total = subtotal + tax

    totals = {"subtotal": subtotal, "tax": tax, "total": total}
    
    total_prep_time = sum(
        item["preparation_time_minutes"] * item["quantity"] 
        for item in processed_items
    )
    
    batch_id = SalesService.generate_batch_id()
    batch_created_at = get_nigerian_time().isoformat()
    display_number = SalesService.get_next_display_number()
    order_number = f"ORD-{get_nigerian_time().strftime('%Y%m%d')}-{random.randint(100, 999):03d}"
    
    order_entry = {
        "order_number": f"TEMP-{get_nigerian_time().strftime('%Y%m%d%H%M%S')}",
        "display_number": display_number,
        "order_type": "offline",
        "order_placement_type": order_data.order_placement_type,
        "status": "pending",
        "payment_status": "pending",
        "payment_method": order_data.payment_method,
        "customer_name": order_data.customer_name,
        "customer_phone": order_data.customer_phone,
        "subtotal": float(totals["subtotal"]),
        "tax": float(totals["tax"]), 
        "total": float(totals["total"]),
        "estimated_prep_time_minutes": total_prep_time,
        "notes": order_data.notes,
        "created_by": current_user["id"],
        "batch_id": batch_id,
        "batch_created_at": batch_created_at
    }
    
    created_order = supabase_admin.table("orders").insert(order_entry).execute()
    order_id = created_order.data[0]["id"]

    # Generate final order number
    datetime_str = get_nigerian_time().strftime("%Y%m%d%H%M%S")
    order_number = f"LEBANST-POS-{datetime_str}-{str(order_id)[-6:].zfill(6)}"

    # Update with final order number
    supabase_admin.table("orders").update({"order_number": order_number}).eq("id", order_id).execute()

   
    
    for item in processed_items:
        item_data = {
            "order_id": order_id,
            "product_id": item["product_id"],
            "product_name": item["product_name"],
            "quantity": item["quantity"],
            "unit_price": float(item["unit_price"]),
            "tax_per_unit": float(item["tax_per_unit"]),
            "total_price": float(item["total_price"]),
            "preparation_time_minutes": item["preparation_time_minutes"],
            "notes": item.get("notes"),
            "is_extra": item.get("is_extra", False)
        }
        result = supabase_admin.table("order_items").insert(item_data).execute()
        order_item_id = result.data[0]["id"]
        
        # Insert multiple options
        for option_id in item.get("option_ids", []):
            try:
                supabase_admin.table("order_item_options").insert({
                    "id": str(uuid.uuid4()),
                    "order_item_id": order_item_id,
                    "option_id": option_id
                }).execute()
            except Exception as e:
                print(f"Failed to insert option {option_id}: {e}")
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "create", "offline_order", order_id, 
        {
            "order_number": order_number, 
            "total": float(totals["total"]),
            "prep_time_minutes": total_prep_time
        }, 
        request
    )
    
    return created_order.data[0]

@router.post("/orders/{order_id}/confirm")
async def confirm_order_payment(
    order_id: str,
    confirm_data: OrderConfirm,
    request: Request,
    current_user: dict = Depends(require_sales_staff)
):
    """Confirm payment and send to kitchen"""
    if not confirm_data.payment_confirmed:
        raise HTTPException(status_code=400, detail="Payment must be confirmed")
    
    # Get order
    order = supabase_admin.table("orders").select("*, order_items(*)").eq("id", order_id).eq("status", "pending").execute()
    
    if not order.data:
        raise HTTPException(status_code=404, detail="Pending order not found")
    
    # Update order status
    supabase_admin.table("orders").update({
        # "status": "confirmed",
        "status": "transit",  
        "payment_status": "paid",
        "preparing_at": get_nigerian_time().isoformat()
    }).eq("id", order_id).execute()
    
    # Deduct stock immediately with real-time updates
    await SalesService.deduct_stock_immediately(order.data[0]["order_items"], current_user["id"])
    
    # Notify kitchen
    from ..api.websocket import notify_order_update
    await notify_order_update(order_id, "new_order", order.data[0])
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "confirm_payment", "order", order_id, 
        {"order_number": order.data[0]["order_number"]}, 
        request
    )
    
    # Return confirmation with receipt data
    return {
        "message": "Order confirmed and sent to kitchen",
        "receipt": {
            "order_number": order.data[0]["order_number"],
            "customer_name": order.data[0].get("customer_name", "Walk-in Customer"),
            "payment_method": order.data[0].get("payment_method"),
            "items": order.data[0]["order_items"],
            "subtotal": order.data[0]["subtotal"],
            "tax": order.data[0]["tax"],
            "total": order.data[0]["total"],
            "created_at": order.data[0]["created_at"]
        }
    }






@router.get("/orders/{order_id}/print")
async def print_sales_receipt(
    order_id: str,
    request: Request,
    current_user: dict = Depends(require_sales_staff)
):
    """Generate printable sales receipt with tax breakdown"""
    order = supabase_admin.table("orders").select("*, order_items(*)").eq("id", order_id).execute()
    
    if not order.data:
        raise HTTPException(status_code=404, detail="Order not found")
    
    order_data = order.data[0]
    
    # Calculate tax breakdown for receipt
    total_tax = sum(
        float(item.get("tax_per_unit", 0)) * item["quantity"] 
        for item in order_data["order_items"]
    )
    
    receipt_data = {
        "order_number": order_data["order_number"],
        "batch_id": order_data.get("batch_id"),
        "display_number": order_data.get("display_number"),
        "customer_name": order_data.get("customer_name", "Walk-in Customer"),
        "payment_method": order_data.get("payment_method"),
        "created_at": order_data["created_at"],
        "items": order_data["order_items"],
        "subtotal": order_data["subtotal"],
        "tax": order_data.get("tax", total_tax),  # Use calculated tax if not stored
        "total": order_data["total"],
        "estimated_prep_time": order_data.get("estimated_prep_time_minutes", 0)
    }
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "print", "sales_receipt", order_id, 
        {"order_number": order_data["order_number"]}, 
        request
    )
    
    return receipt_data



@router.get("/orders/pending")
async def get_pending_orders(
    current_user: dict = Depends(require_sales_staff)
):
    """Get all pending orders"""
    result = supabase_admin.table("orders").select("*, order_items(*)").eq("status", "pending").order("created_at", desc=True).execute()
    return result.data


@router.patch("/orders/{order_id}")
async def modify_pending_order(
    order_id: str,
    items: List[Dict[str, Any]],
    request: Request,
    current_user: dict = Depends(require_sales_staff)
):
    """Modify pending order items"""
    order = supabase_admin.table("orders").select("*").eq("id", order_id).eq("status", "pending").execute()
    
    if not order.data:
        raise HTTPException(status_code=404, detail="Pending order not found")
    
    processed_items = await SalesService.validate_sales_cart_items(items)
    totals = CartService.calculate_order_total(processed_items)
    
    # Delete existing items and their options
    existing_items = supabase.table("order_items").select("id").eq("order_id", order_id).execute()
    for item in existing_items.data:
        supabase_admin.table("order_item_options").delete().eq("order_item_id", item["id"]).execute()
    
    supabase_admin.table("order_items").delete().eq("order_id", order_id).execute()
    
    # Create new items with options
    for item in processed_items:
        item_data = {
            "order_id": order_id,
            "product_id": item["product_id"],
            "product_name": item["product_name"],
            "quantity": item["quantity"],
            "unit_price": float(item["unit_price"]),
            "tax_per_unit": float(item["tax_per_unit"]),
            "total_price": float(item["total_price"]),
            "preparation_time_minutes": item["preparation_time_minutes"],
            "notes": item.get("notes")
        }
        result = supabase_admin.table("order_items").insert(item_data).execute()
        order_item_id = result.data[0]["id"]
        
        for option_id in item.get("option_ids", []):
            supabase_admin.table("order_item_options").insert({
                "id": str(uuid.uuid4()),
                "order_item_id": order_item_id,
                "option_id": option_id
            }).execute()
    
    supabase_admin.table("orders").update({
        "subtotal": float(totals["subtotal"]),
        "tax": float(totals["tax"]),
        "total": float(totals["total"])
    }).eq("id", order_id).execute()
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "modify", "pending_order", order_id, None, request
    )
    
    return {"message": "Order modified successfully"}


@router.delete("/orders/{order_id}")
async def delete_pending_order(
    order_id: str,
    request: Request,
    current_user: dict = Depends(require_sales_staff)
):
    """Delete pending order"""
    order = supabase.table("orders").select("*").eq("id", order_id).eq("status", "pending").execute()
    
    if not order.data:
        raise HTTPException(status_code=404, detail="Pending order not found")
    
    supabase.table("order_items").delete().eq("order_id", order_id).execute()
    supabase.table("orders").delete().eq("id", order_id).execute()
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "delete", "pending_order", order_id, None, request
    )
    
    return {"message": "Order deleted successfully"}

@router.post("/orders/{order_id}/recall")
async def recall_confirmed_order(
    order_id: str,
    request: Request,
    current_user: dict = Depends(require_manager_up)
):
    """Recall order from kitchen and restore stock"""
    order = supabase.table("orders").select("*, order_items(*)").eq("id", order_id).eq("status", "preparing").execute()
    
    if not order.data:
        raise HTTPException(status_code=404, detail="Preparing order not found")
    
    # Restore stock using service
    await SalesService.restore_stock_immediately(order.data[0]["order_items"], current_user["id"])
    
    # Cancel order
    supabase.table("orders").update({
        "status": "cancelled",
        "notes": f"Recalled by {current_user['email']}"
    }).eq("id", order_id).execute()
    
    # Notify kitchen
    from ..api.websocket import notify_order_update
    await notify_order_update(order_id, "order_cancelled", order.data[0])
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "recall", "order", order_id, 
        {"order_number": order.data[0]["order_number"]}, 
        request
    )
    
    return {"message": "Order recalled and stock restored"}




@router.get("/batches")
async def get_order_batches(current_user: dict = Depends(require_sales_staff)):
    """Get order batches waiting for kitchen push - only confirmed status"""
    result = supabase_admin.table("orders").select("*, order_items(*)").eq("status", "confirmed").eq("order_type", "online").not_.is_("batch_id", "null").order("batch_created_at").execute()
    
    # Group by batch_id
    batches = {}
    for order in result.data:
        batch_id = order["batch_id"]
        if batch_id not in batches:
            batches[batch_id] = {
                "batch_id": batch_id,
                "customer_name": order.get("customer_name"),
                "customer_phone": order.get("customer_phone"),
                "orders": [],
                "total_items": 0,
                "total_amount": 0,
                "batch_created_at": order["batch_created_at"]
            }
        
        batches[batch_id]["orders"].append(order)
        batches[batch_id]["total_items"] += len(order["order_items"])
        batches[batch_id]["total_amount"] += float(order["total"])
    
    return list(batches.values())








# @router.get("/batches/{batch_id}/details")
# async def get_batch_details(
#     batch_id: str,
#     current_user: dict = Depends(require_sales_staff)
# ):
#     """Get detailed information about a specific batch"""
#     orders = supabase_admin.table("orders").select("""
#         *, 
#         order_items(*),
#         customer_addresses(full_address, delivery_areas(name, estimated_time)),
#         website_customers(full_name, email, phone)
#     """).eq("batch_id", batch_id).execute()
    
#     if not orders.data:
#         raise HTTPException(status_code=404, detail="Batch not found")

#     # Fetch options for each item
#     for order in orders.data:
#         if "order_items" not in order or order["order_items"] is None:
#             order["order_items"] = []
        
#         for item in order.get("order_items", []):
#             options_result = supabase_admin.table("order_item_options").select("*, product_options(*)").eq("order_item_id", item["id"]).execute()
#             item["options"] = options_result.data
    
#     # Extract customer info
#     first_order = orders.data[0]
    
#     # For online orders, fetch customer directly if join failed
#     customer_info = {}
#     if first_order.get("website_customer_id"):
#         customer = supabase_admin.table("website_customers").select("*").eq("id", first_order["website_customer_id"]).execute()
#         if customer.data:
#             customer_info = {
#                 "name": customer.data[0].get("full_name"),
#                 "phone": customer.data[0].get("phone"),
#                 "email": customer.data[0].get("email")
#             }
#     else:
#         # Offline order
#         customer_info = {
#             "name": first_order.get("customer_name") or "N/A",
#             "phone": first_order.get("customer_phone") or "N/A",
#             "email": first_order.get("customer_email") or "N/A"
#         }
    
#     delivery_info = first_order.get("customer_addresses")
    
#     # Calculate totals correctly
#     total_items = sum(len(order.get("order_items", [])) for order in orders.data)
#     total_amount = sum(float(order["total"]) for order in orders.data)
    
#     return {
#         "batch_id": batch_id,
#         "orders": orders.data,
#         "customer_info": customer_info,
#         "delivery_info": delivery_info,
#         "summary": {
#             "order_count": len(orders.data),
#             "total_items": total_items,
#             "total_amount": total_amount,
#             "status": orders.data[0]["status"] if orders.data else None,
#             "batch_created_at": orders.data[0]["batch_created_at"] if orders.data else None
#         }
#     }




@router.get("/batches/{batch_id}/details")
async def get_batch_details(
    batch_id: str,
    current_user: dict = Depends(require_sales_staff)
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




@router.post("/batches/{batch_id}/push-to-kitchen")
async def push_batch_to_kitchen(
    batch_id: str,
    request: Request,
    current_user: dict = Depends(require_sales_staff)
):
    """Push entire batch to kitchen"""
    orders = supabase_admin.table("orders").select("*, order_items(*)").eq("batch_id", batch_id).eq("status", "confirmed").execute()

    if not orders.data:
        raise HTTPException(status_code=404, detail="No confirmed orders found for this batch")

    # Fetch options for all items in all orders
    for order in orders.data:
        for item in order["order_items"]:
            options_result = supabase_admin.table("order_item_options").select("*, product_options(*)").eq("order_item_id", item["id"]).execute()
            item["options"] = options_result.data

    order_ids = [o["id"] for o in orders.data]
    
    # Update all orders to preparing
    supabase.table("orders").update({
        "status": "transit",
        # "preparing_at": get_nigerian_time().isoformat()
    }).in_("id", order_ids).execute()
    
    
    
    # Notify kitchen
    # await notify_order_update(batch_id, "new_batch", {"batch_id": batch_id, "orders": orders.data})
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "push_batch_to_kitchen", "batch", None,
        {"order_count": len(orders.data)}, 
        request,
        batch_id=batch_id
    )
    
    return {"message": f"Batch {batch_id} pushed to kitchen", "orders_count": len(orders.data)}



@router.get("/batches/history")
async def get_batch_history(
    current_user: dict = Depends(require_sales_staff),
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0)
):
    """Get processed batch history"""
    result = supabase_admin.table("orders").select("""
        *, 
        order_items(*),
        customer_addresses(full_address, delivery_areas(name)),
        website_customers(full_name, email, phone)
    """).not_.is_("batch_id", "null").in_("status", ["preparing", "completed"]).order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    
    # Group by batch_id
    batches = {}
    for order in result.data:
        batch_id = order["batch_id"]
        if batch_id not in batches:
            batches[batch_id] = {
                "batch_id": batch_id,
                "orders": [],
                "total_items": 0,
                "status": order["status"],
                "pushed_at": order["preparing_at"],
                "completed_at": order.get("completed_at"),
                "customer_info": {
                    "name": order.get("customer_name") or (order.get("website_customers", {}) or {}).get("full_name"),
                    "phone": order.get("customer_phone") or (order.get("website_customers", {}) or {}).get("phone")
                }
            }
        
        batches[batch_id]["orders"].append(order)
        batches[batch_id]["total_items"] += len(order.get("order_items") or [])
    
    return {"batches": list(batches.values())}


@router.post("/orders/{order_id}/refund")
async def process_refund(
    order_id: str,
    refund_data: RefundRequest,
    request: Request,
    current_user: dict = Depends(require_manager_up)  # Manager+ only for refunds
):
    """Process partial or full refund and restore inventory"""
    
    # Get original order
    order = supabase_admin.table("orders").select("*, order_items(*)").eq("id", order_id).eq("status", "completed").execute()
    
    if not order.data:
        raise HTTPException(status_code=404, detail="Completed order not found")
    
    order_data = order.data[0]
    original_items = {item["product_id"]: item for item in order_data["order_items"]}
    
    # Validate refund items
    refund_amount = Decimal('0')
    processed_refunds = []
    
    for refund_item in refund_data.items:
        product_id = refund_item["product_id"]
        refund_qty = refund_item["quantity"]
        
        if product_id not in original_items:
            raise HTTPException(status_code=400, detail=f"Product {product_id} not in original order")
        
        original_item = original_items[product_id]
        if refund_qty > original_item["quantity"]:
            raise HTTPException(status_code=400, detail=f"Cannot refund {refund_qty} of {original_item['product_name']}, only {original_item['quantity']} ordered")
        
        # Calculate refund amount
        unit_price = Decimal(str(original_item["unit_price"]))
        item_refund = unit_price * refund_qty
        refund_amount += item_refund
        
        processed_refunds.append({
            "product_id": product_id,
            "product_name": original_item["product_name"],
            "quantity": refund_qty,
            "unit_price": unit_price,
            "refund_amount": item_refund,
            "reason": refund_item.get("reason", "")
        })
    
    # Create refund record
    refund_record = {
        "order_id": order_id,
        "refund_amount": float(refund_amount),
        "refund_reason": refund_data.refund_reason,
        "notes": refund_data.notes,
        "processed_by": current_user["id"],
        "refund_items": processed_refunds
    }
    
    refund_result = supabase_admin.table("refunds").insert(refund_record).execute()
    refund_id = refund_result.data[0]["id"]
    
    # Restore inventory
    for refund_item in processed_refunds:
        product = supabase.table("products").select("*").eq("id", refund_item["product_id"]).execute()
        
        if product.data:
            current_units = product.data[0]["units"]
            low_threshold = product.data[0]["low_stock_threshold"]
            new_units = current_units + refund_item["quantity"]
            
            # Update status based on new stock
            if new_units > low_threshold:
                new_status = "in_stock"
            elif new_units > 0:
                new_status = "low_stock"
            else:
                new_status = "out_of_stock"
            
            supabase.table("products").update({
                "units": new_units,
                "status": new_status,
                "updated_by": current_user["id"],
                "updated_at": get_nigerian_time().isoformat()
            }).eq("id", refund_item["product_id"]).execute()
            
            # Log stock restoration
            supabase_admin.table("stock_entries").insert({
                "product_id": refund_item["product_id"],
                "quantity": refund_item["quantity"],
                "entry_type": "add",
                "notes": f"Refund restoration - Refund ID: {refund_id}",
                "entered_by": current_user["id"]
            }).execute()
    
    # Clear inventory caches
    redis_client.delete_pattern("products:list:*")
    redis_client.delete_pattern("inventory:dashboard:*")
    redis_client.delete_pattern("sales:products:*")
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "process_refund", "order", order_id,
        {
            "refund_amount": float(refund_amount),
            "items_count": len(processed_refunds),
            "refund_reason": refund_data.refund_reason
        },
        request
    )
    
    return {
        "message": "Refund processed successfully",
        "refund_id": refund_id,
        "refund_amount": float(refund_amount),
        "items_refunded": processed_refunds
    }

@router.get("/orders/{order_id}/refund-history")
async def get_refund_history(
    order_id: str,
    current_user: dict = Depends(require_sales_staff)
):
    """Get refund history for an order"""
    
    refunds = supabase_admin.table("refunds").select("*, profiles(email)").eq("order_id", order_id).order("created_at", desc=True).execute()
    
    return refunds.data

@router.get("/refunds/summary")
async def get_refunds_summary(
    request: Request,
    days: int = 30,
    current_user: dict = Depends(require_manager_up)
):
    """Get refunds summary and analytics"""
    
    end_date = get_nigerian_time()
    start_date = end_date - timedelta(days=days)
    
    refunds = supabase_admin.table("refunds").select("*").gte("created_at", start_date.isoformat()).execute()
    
    total_refunds = len(refunds.data)
    total_refund_amount = sum(float(r["refund_amount"]) for r in refunds.data)
    
    # Group by reason
    refund_reasons = {}
    for refund in refunds.data:
        reason = refund["refund_reason"]
        if reason not in refund_reasons:
            refund_reasons[reason] = {"count": 0, "amount": 0}
        refund_reasons[reason]["count"] += 1
        refund_reasons[reason]["amount"] += float(refund["refund_amount"])
    
    return {
        "period": {"start": start_date.date(), "end": end_date.date(), "days": days},
        "summary": {
            "total_refunds": total_refunds,
            "total_refund_amount": round(total_refund_amount, 2),
            "average_refund": round(total_refund_amount / total_refunds, 2) if total_refunds > 0 else 0
        },
        "refund_reasons": [
            {"reason": k, **v, "amount": round(v["amount"], 2)}
            for k, v in refund_reasons.items()
        ]
    }




API_KEY_NAME = "X-API-KEY"
API_KEY = settings.SPREADSHEET_API_KEY  

api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

async def get_api_key(api_key_header: str = Security(api_key_header)):
    if api_key_header == API_KEY:
        return api_key_header
    else:
        raise HTTPException(status_code=403, detail="Could not validate credentials")





@router.get("/sales/reports/all-orders", dependencies=[Depends(get_api_key)])
async def get_spreadsheet_orders():
    
    
    # Fetch orders first
    orders_result = supabase_admin.table("orders").select("*").order("created_at", desc=True).limit(5000).execute()
    
    if not orders_result.data:
        return []
    
    # Get all related IDs
    order_ids = [o["id"] for o in orders_result.data]
    customer_ids = [o["website_customer_id"] for o in orders_result.data if o.get("website_customer_id")]
    address_ids = [o["customer_address_id"] for o in orders_result.data if o.get("customer_address_id")]
    
    # Batch fetch related data
    items_result = supabase_admin.table("order_items").select("*").in_("order_id", order_ids).execute()
    customers_result = supabase_admin.table("website_customers").select("*").in_("id", customer_ids).execute() if customer_ids else None
    addresses_result = supabase_admin.table("customer_addresses").select("*, delivery_areas(name)").in_("id", address_ids).execute() if address_ids else None
    
    # Create lookup maps
    items_map = {}
    for item in items_result.data:
        oid = item["order_id"]
        if oid not in items_map:
            items_map[oid] = []
        items_map[oid].append(item)
    
    customers_map = {c["id"]: c for c in (customers_result.data if customers_result else [])}
    addresses_map = {a["id"]: a for a in (addresses_result.data if addresses_result else [])}
    
    # Build flattened data
    flattened_data = []
    for order in orders_result.data:
        items = items_map.get(order["id"], [])
        customer = customers_map.get(order.get("website_customer_id"), {})
        address = addresses_map.get(order.get("customer_address_id"), {})
        delivery_area = address.get("delivery_areas", {}) if address else {}
        
        flattened_data.append({
            "order_id": order.get("id"),
            "order_number": order.get("order_number"),
            "display_number": order.get("display_number"),
            "order_type": order.get("order_type"),
            "status": order.get("status"),
            "created_at": order.get("created_at"),
            "completed_at": order.get("completed_at"),
            "full_name": customer.get("full_name") or order.get("customer_name"),
            "email": customer.get("email"),
            "phone": customer.get("phone"),
            "full_address": address.get("full_address"),
            "delivery_area": delivery_area.get("name") if isinstance(delivery_area, dict) else None,
            "product_names": ", ".join([i.get("product_name", "") for i in items]),
            "product_quantities": ", ".join([str(i.get("quantity", 0)) for i in items]),
            "payment_status": order.get("payment_status"),
            "payment_method": order.get("payment_method"),
            "subtotal": order.get("subtotal"),
            "tax": order.get("tax"),
            "delivery_fee": order.get("delivery_fee"),
            "total_price": order.get("total"),
            "notes": order.get("notes"),
            "batch_id": order.get("batch_id"),
        })
    
    return flattened_data






@router.get("/orders/{batch_id}/customer-receipt")
async def print_batch_customer_receipt(
    batch_id: str,
    request: Request,
    current_user: dict = Depends(require_sales_staff)
):
    """Generate printable receipt for batch"""
    orders_result = supabase_admin.table("orders").select("*, order_items(*)").eq("batch_id", batch_id).execute()
    
    if not orders_result.data:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    first_order = orders_result.data[0]
    
    # Fetch options for all items
    all_items = []
    for order in orders_result.data:
        for item in order.get("order_items", []):
            all_items.append(item)
    
    if all_items:
        item_ids = [item['id'] for item in all_items]
        options_result = supabase_admin.table("order_item_options").select("*, product_options(*)").in_("order_item_id", item_ids).execute()
        
        options_map = {}
        for opt in options_result.data:
            if opt['order_item_id'] not in options_map:
                options_map[opt['order_item_id']] = []
            options_map[opt['order_item_id']].append(opt)
        
        for item in all_items:
            item['options'] = options_map.get(item['id'], [])
    
    # Build items HTML
    items_html = ""
    for item in all_items:
        item_total_price = Decimal(item.get("total_price", 0))
        items_html += f'<tr><td class="main-item-desc">{item["quantity"]}X {item["product_name"]}</td><td class="main-item-price">{format_currency(item_total_price)}</td></tr>'
        
        for option in item.get("options", []):
            opt_details = option.get("product_options")
            if opt_details and isinstance(opt_details, dict):
                price_mod = Decimal(opt_details.get("price_modifier", 0))
                option_name = opt_details.get("name", "Option")
                items_html += f'<tr><td class="sub-item-desc">- {option_name}</td><td class="sub-item-price">{format_currency(price_mod) if price_mod > 0 else ""}</td></tr>'
        
        if item.get("notes"):
            items_html += f'<tr><td class="item-notes" colspan="2">NOTES: {item["notes"]}</td></tr>'
    
    # Calculate totals
    total_amount = sum(float(o["total"]) for o in orders_result.data)
    total_tax = sum(float(o.get("tax", 0)) for o in orders_result.data)
    subtotal = total_amount - total_tax
    
    created_dt = datetime.fromisoformat(first_order['created_at'])
    order_day = created_dt.strftime('%A').upper()
    order_time = created_dt.strftime('%I:%M %p')

    logo_svg_uri = "data:image/svg+xml,%3csvg width='88' height='56' viewBox='0 0 88 56' fill='none' xmlns='http://www.w3.org/2000/svg'%3e%3cg clip-path='url(%23clip0_108_53)'%3e%3cpath d='M22.0078 27.5694C22.5293 27.0777 23.1949 27.3945 23.1062 28.0174C22.7621 30.312 22.3962 32.9016 22.5626 34.6936C22.6401 35.4802 22.3406 35.8409 21.6417 35.8628C18.2359 35.8628 9.76036 34.0817 7.43069 32.9563C5.16757 31.8636 2.83789 30.3885 1.14056 29.1647C0.441658 28.6511 0.108847 28.0174 0.253065 27.4492C0.619157 25.679 1.39572 19.1011 1.39572 13.7253C1.39572 8.34935 0.608063 3.30123 0.241972 1.18145C0.131035 0.471217 0.463846 0.110636 1.16275 0.230829C1.86165 0.351022 2.63821 0.449363 3.90289 0.46029C5.23413 0.482142 6.04397 0.361949 6.83162 0.230829C7.46397 0.121562 7.86334 0.602337 7.71912 1.46554C7.35303 4.01147 6.57648 9.68242 6.57648 15.703C6.57648 18.544 7.08679 25.6135 7.08679 25.6135C11.5021 27.9518 18.4246 30.6944 22.0078 27.5694ZM14.93 25.6353C13.0552 25.3186 11.6574 24.8158 10.1597 24.2039C9.50521 23.9309 9.16131 23.6031 9.27225 22.8382C9.63834 20.8714 10.2374 15.6702 10.2374 12.4359C10.2374 8.84106 9.64944 3.67274 9.27225 1.45462C9.16131 0.55863 9.46083 0.143416 10.1597 0.230829C11.6352 0.42751 13.5322 0.547703 15.4514 0.547703C17.526 0.547703 19.6005 0.416583 21.3422 0.198049C22.0078 0.110636 22.3629 0.580483 22.3073 1.56388C22.2075 3.15918 22.2519 4.89652 22.3073 6.30606C22.3516 7.36596 21.9745 7.61726 21.2755 7.15835C18.9792 5.56305 16.6496 5.72694 15.4625 5.72694C15.4625 5.72694 15.2074 8.64438 15.0521 10.7642C16.2724 10.8625 17.7478 10.5128 18.6464 10.0321C19.2677 9.70426 19.5451 9.9228 19.5007 10.8079C19.4674 11.4962 19.423 12.1846 19.423 12.9713C19.423 13.6597 19.423 14.2935 19.4563 14.9709C19.5007 15.8888 19.2343 16.1182 18.5687 15.7467C17.5814 15.2113 16.1282 14.7196 15.0188 14.6103C15.1297 16.7738 15.4625 20.161 15.4625 20.161C18.0585 20.6418 20.2328 20.0299 21.797 18.7516C22.4293 18.2271 22.729 18.4238 22.6844 19.3635C22.618 21.1118 22.5736 22.8599 22.6844 24.4554C22.74 25.2529 22.3962 25.5479 21.7193 25.6135C18.9128 25.8976 17.0046 25.9631 14.9411 25.6135L14.93 25.6353Z' fill='%23FF0000'/%3e%3cpath d='M35.4754 12.2503C36.8399 11.0046 38.2932 8.66633 38.2932 6.53562C38.2932 1.85901 35.2534 0.0779584 30.7051 0.00147157C29.2518 -0.0203818 26.6225 0.209078 24.892 0.165372C24.2152 0.143519 23.8603 0.646146 24.0044 1.53121C24.3039 3.94601 24.892 8.74282 24.892 13.5506C24.892 18.3584 24.3372 22.4667 24.0044 24.4882C23.8936 25.3842 24.2264 25.7775 24.892 25.5918C25.4687 25.4388 26.2343 25.2203 27.3325 25.1219C28.564 25.0126 30.2613 24.8487 31.5925 24.3898C35.6639 22.9912 39.5134 20.3252 39.5134 15.6266C39.5134 13.0807 37.4389 11.8788 35.4754 12.2394V12.2503ZM29.6623 7.22401C29.9285 5.71613 30.7384 4.59067 31.5815 4.5142C32.6909 4.41586 33.545 5.48667 33.545 8.08721C33.545 10.0103 32.3248 11.704 30.3944 12.0973C30.0949 12.1519 29.9508 12.1847 29.6511 12.2503C29.6511 10.2616 29.3295 9.03784 29.6511 7.22401H29.6623ZM31.7812 20.4671C30.8603 20.7621 30.0616 20.3252 29.7844 19.2433C29.4847 18.0743 29.7067 17.0908 29.7067 15.4955C30.0172 15.419 30.1726 15.3862 30.4831 15.3098C32.4468 14.829 33.8557 15.4518 33.8557 16.9815C33.8557 19.0249 32.8904 20.1176 31.7812 20.478V20.4671Z' fill='%23FF0000'/%3e%3cpath d='M57.0188 21.4068C56.3198 19.5711 54.9443 13.485 54.1676 9.51865C53.5797 6.49195 53.0917 3.5199 53.0584 0.733591C53.0584 0.296524 52.6923 0.0779898 52.06 0.132623C49.2089 0.394864 44.616 0.602471 40.3672 0.0342833C39.7016 -0.0422036 39.3465 0.34023 39.4019 1.07232C39.5462 2.94078 39.5019 4.83111 39.4019 6.71049C39.3576 7.56276 39.8124 7.72666 40.4337 7.16941C41.0661 6.61216 41.7982 6.10953 42.353 5.74894C42.2974 6.31712 42.2641 6.61216 42.2087 7.18034C41.7649 13.2665 41.0328 21.2538 35.73 24.9034C32.4019 27.198 27.554 27.7662 24.9247 27.3839C24.2259 27.2963 23.9152 27.6788 23.9596 28.4655C24.0706 30.2138 24.0926 32.8471 23.9262 34.4752C23.8486 35.2073 24.1149 35.5459 24.8138 35.3712C28.3637 34.4097 35.73 31.82 38.104 29.9406C41.6874 27.0998 43.6509 23.9855 44.8824 20.2487C46.7349 19.4401 47.6556 19.0466 49.5083 18.2708C49.5417 20.0191 49.5527 23.614 49.5083 24.5428C49.475 25.1876 49.8412 25.3295 50.4734 24.9689C51.3388 24.4663 52.1377 24.0183 53.5133 23.4612C54.7335 22.9584 55.4768 22.7617 56.1757 22.5978C56.919 22.4339 57.2518 21.9313 57.03 21.3851L57.0188 21.4068ZM46.0249 15.7906C46.5797 12.9278 46.99 9.64976 47.4671 6.01117C47.5892 5.33373 47.6446 5.00592 47.7666 4.35033C48.2104 6.80883 48.6542 9.16898 49.0645 11.999C49.1755 12.8294 49.2532 13.7036 49.3199 14.5558C47.9997 15.0475 47.3451 15.2989 46.0249 15.8015V15.7906Z' fill='%23FF0000'/%3e%3cpath d='M61.4683 20.9369C60.2146 21.21 59.427 21.4832 58.6949 21.7892C58.0293 22.0734 57.6631 21.8766 57.8073 21.1663C58.1734 19.0576 58.95 12.4469 58.95 8.5679C58.95 4.68892 58.1734 1.90261 57.8073 0.678824C57.6631 0.274536 58.0293 0.0669297 58.6949 0.121563C59.5046 0.187123 60.3922 0.219902 61.6901 0.219902C63.099 0.219902 64.1085 0.176196 65.0959 0.0997097C65.7505 0.0450763 66.0722 0.23083 66.061 0.613263C66.0056 2.08836 66.8709 4.50317 68.0911 6.25144C68.8678 7.33317 69.6887 8.43678 70.4652 9.46388C70.4764 9.02681 70.4874 8.80827 70.4985 8.38213C70.4985 4.78726 69.722 1.89168 69.3559 0.678824C69.2449 0.274536 69.5777 0.0669297 70.2767 0.13249C70.9756 0.19805 71.7522 0.241757 73.0168 0.252684C74.348 0.252684 75.1467 0.19805 75.9787 0.13249C76.6333 0.0778563 76.9772 0.307316 76.8663 0.777165C76.3115 2.78768 75.7236 4.56873 75.6792 9.04866C75.6459 12.7747 76.4559 18.9045 76.822 20.6857C76.9661 21.2976 76.5779 21.4832 75.9344 21.2319C75.1357 20.915 74.337 20.6309 73.0057 20.4233C71.6412 20.2157 70.7981 20.2377 70.0105 20.3142C69.4667 20.3687 69.0896 20.1392 68.9788 19.6258C68.6126 17.9648 67.5698 11.9224 65.7615 9.24534C65.1292 8.30564 64.6189 7.61727 64.1751 7.04908C64.1418 7.43151 64.1418 7.8358 64.1418 8.26195C64.1418 11.9224 64.9184 17.954 65.2846 19.6584C65.4287 20.2377 65.0405 20.62 64.3636 20.6309C63.6204 20.6309 62.8106 20.6637 61.4794 20.9478L61.4683 20.9369Z' fill='%23FF0000'/%3e%3cpath d='M14.9296 55.0718C15.2624 53.7934 15.8504 50.8869 15.8504 47.2264C15.8504 44.9756 15.6285 42.7903 15.4067 41.0529C10.2592 40.299 5.45562 38.4523 0.929385 35.9501C0.297043 35.6114 -0.0579547 35.0323 0.00860754 34.4422C0.152826 32.9671 0.141732 31.8527 0.00860754 30.2902C-0.0579547 29.5798 0.263763 29.5907 0.896104 30.17C5.77733 34.6498 11.6237 36.4964 18.9899 37.2832C25.8014 38.0153 32.269 35.1852 38.3928 31.9509C39.0251 31.5903 39.3469 31.7761 39.2802 32.4426C39.1471 33.9288 39.2027 35.0104 39.3135 36.4527C39.3579 37.0537 38.9807 37.5017 38.3484 37.6547C32.6907 39.3702 27.2992 41.0966 21.3195 41.315C21.0644 43.0853 20.887 45.2705 20.9867 47.5105C21.1531 51.1273 21.608 54.0119 21.8743 55.1265C21.9631 55.5089 21.6192 55.7056 20.9536 55.64C20.2878 55.5745 19.5891 55.5307 18.4686 55.5307C17.3259 55.5307 16.5715 55.5635 15.8393 55.6291C15.1737 55.6837 14.8076 55.487 14.9185 55.0609L14.9296 55.0718ZM1.01813 55.6291C0.385793 55.6291 0.0529823 55.2904 0.130638 54.6348C0.274857 53.3782 0.385793 51.8484 0.352512 50.5481C0.330324 49.8379 0.685323 49.7397 1.31766 50.2314C2.72657 51.2365 4.75671 52.1436 5.83281 52.2746C7.01983 52.4275 8.01827 52.2746 8.01827 51.5317C8.01827 50.8322 5.49998 49.6303 3.72499 48.035C1.27329 45.8387 0.00860754 43.7081 0.00860754 41.4135C0.00860754 38.1355 3.27016 38.6053 7.23061 40.2334C9.22747 41.0529 10.2259 41.5665 11.6681 41.8943C12.2893 42.0363 12.6222 42.3532 12.5556 42.8121C12.4003 43.8828 12.2782 45.3799 12.3337 46.5272C12.3559 47.1173 11.9676 47.1719 11.3685 46.6145C10.0373 45.4016 8.59514 44.3528 7.5967 44.025C6.48732 43.6644 5.63312 43.7626 5.63312 44.4619C5.63312 45.3253 7.56342 46.538 9.14981 47.6527C11.4018 49.2369 13.6317 50.6137 13.6317 52.3183C13.6317 54.5255 10.592 55.8695 6.12123 55.8695C4.08 55.8695 2.63781 55.64 1.01813 55.6291ZM35.6194 55.5526C34.8096 55.5526 34.3214 55.5854 33.8443 55.6291C33.1899 55.6837 32.9459 55.4543 33.101 54.9953C33.2343 54.602 33.4007 53.9791 33.4007 53.0613C33.4007 51.6519 31.6257 51.1819 29.6622 51.3567C29.8063 53.1159 30.2168 54.3616 30.4719 55.0827C30.6162 55.498 30.2722 55.6946 29.5845 55.6619C29.0076 55.6291 28.3974 55.6072 27.399 55.6072C25.9567 55.6072 25.1358 55.6291 24.5145 55.6728C23.8158 55.7165 23.5161 55.5307 23.6271 55.1374C23.9599 54.2086 24.5478 52.2199 24.5478 49.7397C24.5478 47.2593 23.9599 44.6697 23.6271 43.3803C23.5161 42.8666 23.8268 42.5936 24.5478 42.5825C26.6667 42.528 28.3197 42.1019 30.4386 41.3916C34.9981 39.8619 38.2487 40.594 38.2487 44.2435C38.2487 46.4835 37.2169 48.1989 35.5084 49.3134C37.1726 49.7177 38.1377 50.9852 38.3595 51.8484C38.6146 52.8646 39.0584 54.001 39.3579 54.7222C39.602 55.3013 39.2802 55.6619 38.5815 55.6072C37.8382 55.5526 36.9506 55.5417 35.6194 55.5526ZM30.4386 49.8379C32.2136 49.4664 33.323 48.1552 33.323 45.7733C33.323 44.0578 32.6907 43.5114 31.3593 43.9265C30.6606 44.1452 29.9837 44.921 29.8063 45.642C29.4291 47.139 29.6176 48.6361 29.6176 50.0018C29.9394 49.9362 30.1058 49.9036 30.4275 49.8379H30.4386Z' fill='%23FF0000'/%3e%3cpath d='M47.6568 55.1375C45.3271 55.1812 42.9975 55.3559 41.2558 55.5418C40.5568 55.6183 40.224 55.3342 40.3683 54.7112C40.7786 52.8429 41.5109 48.3629 41.5109 43.4459C41.5109 38.5288 40.7676 34.2347 40.3683 32.3772C40.224 31.7653 40.5568 31.2845 41.2558 31.0332C45.1053 29.6673 51.695 26.5641 54.8012 24.8268C54.9121 24.7503 54.9676 25.1438 54.9121 25.8757C54.7679 27.5912 54.8567 28.9899 54.9121 31.186C54.9343 32.0494 54.5016 32.4209 53.8026 32.2022C51.2845 31.1752 48.6221 32.6066 47.2906 33.2621C47.2906 33.2621 46.9578 36.6822 46.8137 39.4685C48.2559 38.944 49.8533 37.906 50.9184 36.9555C51.5507 36.4527 51.8281 36.4747 51.7727 37.305C51.7171 38.0699 51.695 38.8786 51.695 39.7417C51.695 40.5284 51.6838 41.3698 51.7281 42.1019C51.7837 42.8995 51.5063 43.1618 50.8407 43.0197C49.7313 42.823 48.0673 42.8777 46.7693 43.271C46.9135 46.0355 47.2906 49.9801 47.2906 50.0238C53.969 49.1387 62.2561 48.647 68.3132 45.6749C68.9457 45.3034 69.2008 45.4564 69.1675 46.3524C69.0565 48.8218 69.0898 51.9032 69.2785 54.0556C69.3672 55.0281 69.0565 55.4544 68.3576 55.3996C61.4796 54.9188 54.5459 55.0064 47.668 55.1375H47.6568ZM62.2007 42.7793C60.348 42.834 58.4954 43.0416 57.0532 43.5333C56.3876 43.7627 56.0881 43.4131 56.1989 42.5717C56.5317 40.4082 57.1197 36.3764 57.1197 33.5134C57.1197 30.312 56.5317 26.9793 56.1989 25.384C56.0881 24.7066 56.3876 24.2586 57.0865 24.0839C58.4954 23.745 60.348 23.3081 62.1896 22.9366C64.1865 22.5431 66.1167 22.2699 67.925 21.9641C68.5573 21.8984 68.8901 22.2482 68.8458 23.0566C68.7793 24.2914 68.8124 25.7774 68.8124 26.8264C68.8124 27.7442 68.4019 27.9518 67.7363 27.5694C65.5843 26.3019 63.3322 26.8045 62.1784 27.0231C62.1784 27.0231 61.9233 28.8041 61.8125 30.6726C62.955 30.5415 64.3085 29.9624 65.2182 29.5034C65.8395 29.1866 66.15 29.3723 66.1056 30.2137C66.0723 30.8365 66.0279 31.4156 66.0279 32.0931C66.0279 32.6831 66.0279 33.2293 66.0613 33.8195C66.1056 34.7263 65.7951 34.9448 65.1405 34.6609C64.2086 34.2675 62.844 33.9506 61.7679 34.049C61.8456 36.0484 62.1784 38.0591 62.1784 38.0591C64.6634 38.0591 66.6936 37.458 68.3245 36.2451C68.9124 35.7971 69.2673 36.0158 69.2119 36.9444C69.1232 38.4634 69.1232 40.2226 69.2119 41.9489C69.2562 42.8121 68.8901 43.2164 68.2468 43.129C66.4274 42.8558 64.1754 42.7247 62.1784 42.7793H62.2007Z' fill='%23FF0000'/%3e%3cpath d='M75.6454 54.1105C76.1669 49.0734 76.3887 43.8504 76.5662 38.7476C76.6995 34.8141 76.4554 31.2738 76.2002 28.564C74.9798 28.1049 73.3824 28.1269 71.4631 28.859C70.7975 29.0994 70.3539 28.706 70.387 27.8319C70.4869 25.7121 70.5534 24.6959 70.4203 23.1552C70.3539 22.3357 70.7531 21.9642 71.3854 22.1063C72.861 22.445 73.7929 22.587 75.4901 23.0241C78.4079 23.778 79.8611 24.3572 82.7787 26.1382C84.5204 27.1981 85.408 27.8536 86.8834 28.9244C87.5157 29.3835 87.9041 30.1045 87.8485 30.6727C87.7377 31.842 87.7487 33.0766 87.8485 34.6502C87.893 35.3603 87.4382 35.3384 86.7724 34.6065C84.9198 32.5741 83.3666 31.3066 82.1464 30.8149C81.8913 33.164 81.6693 36.3546 81.6693 40.0697C81.6693 46.0904 82.3018 51.8377 82.5902 54.3072C82.701 55.1376 82.3682 55.5091 81.6693 55.378C80.9372 55.236 80.2272 55.1376 79.0401 55.1158C77.8976 55.1048 77.2208 55.1922 76.5995 55.3234C75.9006 55.4654 75.5457 55.0065 75.6344 54.0886L75.6454 54.1105Z' fill='%23FF0000'/%3e%3c/g%3e%3cdefs%3e%3cclipPath id='clip0_108_53'%3e%3crect width='88' height='56' fill='white'/%3e%3c/clipPath%3e%3c/defs%3e%3c/svg%3e"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            @media print {{
                * {{ -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }}
                body {{ margin: 0; padding: 20px; font-family: Arial, sans-serif; color: #000; text-transform: uppercase; }}
                @page {{ size: 80mm auto; margin: 0; }}
            }}
            body {{ width: 80mm; margin: 0 auto; padding: 10mm; font-family: Arial, sans-serif; text-transform: uppercase; }}
            .header {{ text-align: center; margin-bottom: 20px; border-bottom: 3px solid #000; padding-bottom: 15px; }}
            .logo {{ width: 36mm; height: auto; margin-bottom: 10px; }}
            .title {{ font-size: 24px; font-weight: 900; margin: 10px 0; }}
            .order-info {{ font-size: 14px; font-weight: 700; margin: 15px 0; padding: 10px; background: #f0f0f0; border: 2px solid #000; }}
            .display-number {{ font-size: 48px; font-weight: 900; text-align: center; margin: 20px 0; padding: 20px; border: 4px solid #000; background: #000; color: #fff; }}
            table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
            td {{ padding: 8px 0; border-bottom: 1px dashed #000; }}
            .main-item-desc {{ font-weight: 900; font-size: 18px; border-top: 3px solid #000; padding-top: 12px; }}
            .main-item-price {{ font-weight: 900; font-size: 18px; border-top: 3px solid #000; padding-top: 12px; text-align: right; }}
            .sub-item-desc {{ padding-left: 25px !important; font-size: 16px; }}
            .sub-item-price {{ font-size: 16px; text-align: right; }}
            .item-notes {{ padding-left: 25px !important; font-style: italic; font-size: 14px; }}
            .totals-section {{ margin-top: 20px; padding-top: 15px; border-top: 3px solid #000; }}
            .totals-row {{ display: flex; justify-content: space-between; font-size: 16px; font-weight: 700; padding: 4px 0; }}
            .total-final {{ font-size: 20px; font-weight: 900; border-top: 3px solid #000; margin-top: 5px; padding-top: 10px; }}
            .footer {{ text-align: center; margin-top: 25px; padding-top: 15px; border-top: 3px solid #000; font-size: 12px; font-weight: 700; }}
        </style>
    </head>
    <body>
        <div class="header">
            <img src="{logo_svg_uri}" alt="Logo" class="logo">
            <div class="title">CUSTOMER RECEIPT</div>
        </div>
        <div class="display-number">#{order.get('display_number', 'N/A')}</div>
        <div class="order-info">
            <div><strong>ORDER:</strong> {order.get('order_number', '')}</div>
            <div><strong>BATCH:</strong> {order.get('batch_id', 'N/A')}</div>
            <div><strong>TYPE:</strong> {order.get('order_placement_type', '').upper()}</div>
            <div><strong>CUSTOMER:</strong> {order.get('customer_name', 'WALK-IN')}</div>
            <div><strong>DAY:</strong> {order_day}</div>
            <div><strong>TIME:</strong> {order_time}</div>
        </div>
        <table><tbody>{items_html}</tbody></table>
        <div class="totals-section">
            <div class="totals-row"><span>SUBTOTAL</span><span>{format_currency(order.get('subtotal'))}</span></div>
            <div class="totals-row"><span>TAX</span><span>{format_currency(order.get('tax'))}</span></div>
            <div class="totals-row total-final"><span>TOTAL</span><span>{format_currency(order.get('total'))}</span></div>
        </div>
        <div class="footer"><div>COOKING WITH LOVE FOR YOU</div></div>
    </body>
    </html>
    """

    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "print", "batch_receipt", None, {"batch_id": batch_id}, 
        request
    )

    return HTMLResponse(content=html_content)



@router.get("/getorders/{order_id}/customer-receipt")
async def print_order_customer_receipt(
    order_id: str,
    request: Request,
    current_user: dict = Depends(require_sales_staff)
):
    """Generate printable receipt for single order"""
    order_result = supabase_admin.table("orders").select("*, order_items(*)").eq("id", order_id).execute()
    
    if not order_result.data:
        raise HTTPException(status_code=404, detail="Order not found")
    
    order = order_result.data[0]
    
    # Fetch options
    if order.get("order_items"):
        item_ids = [item['id'] for item in order["order_items"]]
        options_result = supabase_admin.table("order_item_options").select("*, product_options(*)").in_("order_item_id", item_ids).execute()
        
        options_map = {}
        for opt in options_result.data:
            item_id = opt['order_item_id']
            if item_id not in options_map:
                options_map[item_id] = []
            options_map[item_id].append(opt)
        
        for item in order["order_items"]:
            item['options'] = options_map.get(item['id'], [])
    
    # Build items HTML
    items_html = ""
    for item in order.get("order_items", []):
        items_html += f'<tr><td class="main-item-desc">{item["quantity"]}X {item["product_name"]}</td><td class="main-item-price">{format_currency(item["total_price"])}</td></tr>'
        
        for option in item.get("options", []):
            if option.get("product_options"):
                items_html += f'<tr><td class="sub-item-desc">- {option["product_options"]["name"]}</td><td class="sub-item-price"></td></tr>'
        
        if item.get("notes"):
            items_html += f'<tr><td class="item-notes" colspan="2">NOTES: {item["notes"]}</td></tr>'
    
    created_dt = datetime.fromisoformat(order['created_at'])
    order_day = created_dt.strftime('%A').upper()
    order_time = created_dt.strftime('%I:%M %p')

    logo_svg_uri = "data:image/svg+xml,%3csvg width='88' height='56' viewBox='0 0 88 56' fill='none' xmlns='http://www.w3.org/2000/svg'%3e%3cg clip-path='url(%23clip0_108_53)'%3e%3cpath d='M22.0078 27.5694C22.5293 27.0777 23.1949 27.3945 23.1062 28.0174C22.7621 30.312 22.3962 32.9016 22.5626 34.6936C22.6401 35.4802 22.3406 35.8409 21.6417 35.8628C18.2359 35.8628 9.76036 34.0817 7.43069 32.9563C5.16757 31.8636 2.83789 30.3885 1.14056 29.1647C0.441658 28.6511 0.108847 28.0174 0.253065 27.4492C0.619157 25.679 1.39572 19.1011 1.39572 13.7253C1.39572 8.34935 0.608063 3.30123 0.241972 1.18145C0.131035 0.471217 0.463846 0.110636 1.16275 0.230829C1.86165 0.351022 2.63821 0.449363 3.90289 0.46029C5.23413 0.482142 6.04397 0.361949 6.83162 0.230829C7.46397 0.121562 7.86334 0.602337 7.71912 1.46554C7.35303 4.01147 6.57648 9.68242 6.57648 15.703C6.57648 18.544 7.08679 25.6135 7.08679 25.6135C11.5021 27.9518 18.4246 30.6944 22.0078 27.5694ZM14.93 25.6353C13.0552 25.3186 11.6574 24.8158 10.1597 24.2039C9.50521 23.9309 9.16131 23.6031 9.27225 22.8382C9.63834 20.8714 10.2374 15.6702 10.2374 12.4359C10.2374 8.84106 9.64944 3.67274 9.27225 1.45462C9.16131 0.55863 9.46083 0.143416 10.1597 0.230829C11.6352 0.42751 13.5322 0.547703 15.4514 0.547703C17.526 0.547703 19.6005 0.416583 21.3422 0.198049C22.0078 0.110636 22.3629 0.580483 22.3073 1.56388C22.2075 3.15918 22.2519 4.89652 22.3073 6.30606C22.3516 7.36596 21.9745 7.61726 21.2755 7.15835C18.9792 5.56305 16.6496 5.72694 15.4625 5.72694C15.4625 5.72694 15.2074 8.64438 15.0521 10.7642C16.2724 10.8625 17.7478 10.5128 18.6464 10.0321C19.2677 9.70426 19.5451 9.9228 19.5007 10.8079C19.4674 11.4962 19.423 12.1846 19.423 12.9713C19.423 13.6597 19.423 14.2935 19.4563 14.9709C19.5007 15.8888 19.2343 16.1182 18.5687 15.7467C17.5814 15.2113 16.1282 14.7196 15.0188 14.6103C15.1297 16.7738 15.4625 20.161 15.4625 20.161C18.0585 20.6418 20.2328 20.0299 21.797 18.7516C22.4293 18.2271 22.729 18.4238 22.6844 19.3635C22.618 21.1118 22.5736 22.8599 22.6844 24.4554C22.74 25.2529 22.3962 25.5479 21.7193 25.6135C18.9128 25.8976 17.0046 25.9631 14.9411 25.6135L14.93 25.6353Z' fill='%23FF0000'/%3e%3cpath d='M35.4754 12.2503C36.8399 11.0046 38.2932 8.66633 38.2932 6.53562C38.2932 1.85901 35.2534 0.0779584 30.7051 0.00147157C29.2518 -0.0203818 26.6225 0.209078 24.892 0.165372C24.2152 0.143519 23.8603 0.646146 24.0044 1.53121C24.3039 3.94601 24.892 8.74282 24.892 13.5506C24.892 18.3584 24.3372 22.4667 24.0044 24.4882C23.8936 25.3842 24.2264 25.7775 24.892 25.5918C25.4687 25.4388 26.2343 25.2203 27.3325 25.1219C28.564 25.0126 30.2613 24.8487 31.5925 24.3898C35.6639 22.9912 39.5134 20.3252 39.5134 15.6266C39.5134 13.0807 37.4389 11.8788 35.4754 12.2394V12.2503ZM29.6623 7.22401C29.9285 5.71613 30.7384 4.59067 31.5815 4.5142C32.6909 4.41586 33.545 5.48667 33.545 8.08721C33.545 10.0103 32.3248 11.704 30.3944 12.0973C30.0949 12.1519 29.9508 12.1847 29.6511 12.2503C29.6511 10.2616 29.3295 9.03784 29.6511 7.22401H29.6623ZM31.7812 20.4671C30.8603 20.7621 30.0616 20.3252 29.7844 19.2433C29.4847 18.0743 29.7067 17.0908 29.7067 15.4955C30.0172 15.419 30.1726 15.3862 30.4831 15.3098C32.4468 14.829 33.8557 15.4518 33.8557 16.9815C33.8557 19.0249 32.8904 20.1176 31.7812 20.478V20.4671Z' fill='%23FF0000'/%3e%3cpath d='M57.0188 21.4068C56.3198 19.5711 54.9443 13.485 54.1676 9.51865C53.5797 6.49195 53.0917 3.5199 53.0584 0.733591C53.0584 0.296524 52.6923 0.0779898 52.06 0.132623C49.2089 0.394864 44.616 0.602471 40.3672 0.0342833C39.7016 -0.0422036 39.3465 0.34023 39.4019 1.07232C39.5462 2.94078 39.5019 4.83111 39.4019 6.71049C39.3576 7.56276 39.8124 7.72666 40.4337 7.16941C41.0661 6.61216 41.7982 6.10953 42.353 5.74894C42.2974 6.31712 42.2641 6.61216 42.2087 7.18034C41.7649 13.2665 41.0328 21.2538 35.73 24.9034C32.4019 27.198 27.554 27.7662 24.9247 27.3839C24.2259 27.2963 23.9152 27.6788 23.9596 28.4655C24.0706 30.2138 24.0926 32.8471 23.9262 34.4752C23.8486 35.2073 24.1149 35.5459 24.8138 35.3712C28.3637 34.4097 35.73 31.82 38.104 29.9406C41.6874 27.0998 43.6509 23.9855 44.8824 20.2487C46.7349 19.4401 47.6556 19.0466 49.5083 18.2708C49.5417 20.0191 49.5527 23.614 49.5083 24.5428C49.475 25.1876 49.8412 25.3295 50.4734 24.9689C51.3388 24.4663 52.1377 24.0183 53.5133 23.4612C54.7335 22.9584 55.4768 22.7617 56.1757 22.5978C56.919 22.4339 57.2518 21.9313 57.03 21.3851L57.0188 21.4068ZM46.0249 15.7906C46.5797 12.9278 46.99 9.64976 47.4671 6.01117C47.5892 5.33373 47.6446 5.00592 47.7666 4.35033C48.2104 6.80883 48.6542 9.16898 49.0645 11.999C49.1755 12.8294 49.2532 13.7036 49.3199 14.5558C47.9997 15.0475 47.3451 15.2989 46.0249 15.8015V15.7906Z' fill='%23FF0000'/%3e%3cpath d='M61.4683 20.9369C60.2146 21.21 59.427 21.4832 58.6949 21.7892C58.0293 22.0734 57.6631 21.8766 57.8073 21.1663C58.1734 19.0576 58.95 12.4469 58.95 8.5679C58.95 4.68892 58.1734 1.90261 57.8073 0.678824C57.6631 0.274536 58.0293 0.0669297 58.6949 0.121563C59.5046 0.187123 60.3922 0.219902 61.6901 0.219902C63.099 0.219902 64.1085 0.176196 65.0959 0.0997097C65.7505 0.0450763 66.0722 0.23083 66.061 0.613263C66.0056 2.08836 66.8709 4.50317 68.0911 6.25144C68.8678 7.33317 69.6887 8.43678 70.4652 9.46388C70.4764 9.02681 70.4874 8.80827 70.4985 8.38213C70.4985 4.78726 69.722 1.89168 69.3559 0.678824C69.2449 0.274536 69.5777 0.0669297 70.2767 0.13249C70.9756 0.19805 71.7522 0.241757 73.0168 0.252684C74.348 0.252684 75.1467 0.19805 75.9787 0.13249C76.6333 0.0778563 76.9772 0.307316 76.8663 0.777165C76.3115 2.78768 75.7236 4.56873 75.6792 9.04866C75.6459 12.7747 76.4559 18.9045 76.822 20.6857C76.9661 21.2976 76.5779 21.4832 75.9344 21.2319C75.1357 20.915 74.337 20.6309 73.0057 20.4233C71.6412 20.2157 70.7981 20.2377 70.0105 20.3142C69.4667 20.3687 69.0896 20.1392 68.9788 19.6258C68.6126 17.9648 67.5698 11.9224 65.7615 9.24534C65.1292 8.30564 64.6189 7.61727 64.1751 7.04908C64.1418 7.43151 64.1418 7.8358 64.1418 8.26195C64.1418 11.9224 64.9184 17.954 65.2846 19.6584C65.4287 20.2377 65.0405 20.62 64.3636 20.6309C63.6204 20.6309 62.8106 20.6637 61.4794 20.9478L61.4683 20.9369Z' fill='%23FF0000'/%3e%3cpath d='M14.9296 55.0718C15.2624 53.7934 15.8504 50.8869 15.8504 47.2264C15.8504 44.9756 15.6285 42.7903 15.4067 41.0529C10.2592 40.299 5.45562 38.4523 0.929385 35.9501C0.297043 35.6114 -0.0579547 35.0323 0.00860754 34.4422C0.152826 32.9671 0.141732 31.8527 0.00860754 30.2902C-0.0579547 29.5798 0.263763 29.5907 0.896104 30.17C5.77733 34.6498 11.6237 36.4964 18.9899 37.2832C25.8014 38.0153 32.269 35.1852 38.3928 31.9509C39.0251 31.5903 39.3469 31.7761 39.2802 32.4426C39.1471 33.9288 39.2027 35.0104 39.3135 36.4527C39.3579 37.0537 38.9807 37.5017 38.3484 37.6547C32.6907 39.3702 27.2992 41.0966 21.3195 41.315C21.0644 43.0853 20.887 45.2705 20.9867 47.5105C21.1531 51.1273 21.608 54.0119 21.8743 55.1265C21.9631 55.5089 21.6192 55.7056 20.9536 55.64C20.2878 55.5745 19.5891 55.5307 18.4686 55.5307C17.3259 55.5307 16.5715 55.5635 15.8393 55.6291C15.1737 55.6837 14.8076 55.487 14.9185 55.0609L14.9296 55.0718ZM1.01813 55.6291C0.385793 55.6291 0.0529823 55.2904 0.130638 54.6348C0.274857 53.3782 0.385793 51.8484 0.352512 50.5481C0.330324 49.8379 0.685323 49.7397 1.31766 50.2314C2.72657 51.2365 4.75671 52.1436 5.83281 52.2746C7.01983 52.4275 8.01827 52.2746 8.01827 51.5317C8.01827 50.8322 5.49998 49.6303 3.72499 48.035C1.27329 45.8387 0.00860754 43.7081 0.00860754 41.4135C0.00860754 38.1355 3.27016 38.6053 7.23061 40.2334C9.22747 41.0529 10.2259 41.5665 11.6681 41.8943C12.2893 42.0363 12.6222 42.3532 12.5556 42.8121C12.4003 43.8828 12.2782 45.3799 12.3337 46.5272C12.3559 47.1173 11.9676 47.1719 11.3685 46.6145C10.0373 45.4016 8.59514 44.3528 7.5967 44.025C6.48732 43.6644 5.63312 43.7626 5.63312 44.4619C5.63312 45.3253 7.56342 46.538 9.14981 47.6527C11.4018 49.2369 13.6317 50.6137 13.6317 52.3183C13.6317 54.5255 10.592 55.8695 6.12123 55.8695C4.08 55.8695 2.63781 55.64 1.01813 55.6291ZM35.6194 55.5526C34.8096 55.5526 34.3214 55.5854 33.8443 55.6291C33.1899 55.6837 32.9459 55.4543 33.101 54.9953C33.2343 54.602 33.4007 53.9791 33.4007 53.0613C33.4007 51.6519 31.6257 51.1819 29.6622 51.3567C29.8063 53.1159 30.2168 54.3616 30.4719 55.0827C30.6162 55.498 30.2722 55.6946 29.5845 55.6619C29.0076 55.6291 28.3974 55.6072 27.399 55.6072C25.9567 55.6072 25.1358 55.6291 24.5145 55.6728C23.8158 55.7165 23.5161 55.5307 23.6271 55.1374C23.9599 54.2086 24.5478 52.2199 24.5478 49.7397C24.5478 47.2593 23.9599 44.6697 23.6271 43.3803C23.5161 42.8666 23.8268 42.5936 24.5478 42.5825C26.6667 42.528 28.3197 42.1019 30.4386 41.3916C34.9981 39.8619 38.2487 40.594 38.2487 44.2435C38.2487 46.4835 37.2169 48.1989 35.5084 49.3134C37.1726 49.7177 38.1377 50.9852 38.3595 51.8484C38.6146 52.8646 39.0584 54.001 39.3579 54.7222C39.602 55.3013 39.2802 55.6619 38.5815 55.6072C37.8382 55.5526 36.9506 55.5417 35.6194 55.5526ZM30.4386 49.8379C32.2136 49.4664 33.323 48.1552 33.323 45.7733C33.323 44.0578 32.6907 43.5114 31.3593 43.9265C30.6606 44.1452 29.9837 44.921 29.8063 45.642C29.4291 47.139 29.6176 48.6361 29.6176 50.0018C29.9394 49.9362 30.1058 49.9036 30.4275 49.8379H30.4386Z' fill='%23FF0000'/%3e%3cpath d='M47.6568 55.1375C45.3271 55.1812 42.9975 55.3559 41.2558 55.5418C40.5568 55.6183 40.224 55.3342 40.3683 54.7112C40.7786 52.8429 41.5109 48.3629 41.5109 43.4459C41.5109 38.5288 40.7676 34.2347 40.3683 32.3772C40.224 31.7653 40.5568 31.2845 41.2558 31.0332C45.1053 29.6673 51.695 26.5641 54.8012 24.8268C54.9121 24.7503 54.9676 25.1438 54.9121 25.8757C54.7679 27.5912 54.8567 28.9899 54.9121 31.186C54.9343 32.0494 54.5016 32.4209 53.8026 32.2022C51.2845 31.1752 48.6221 32.6066 47.2906 33.2621C47.2906 33.2621 46.9578 36.6822 46.8137 39.4685C48.2559 38.944 49.8533 37.906 50.9184 36.9555C51.5507 36.4527 51.8281 36.4747 51.7727 37.305C51.7171 38.0699 51.695 38.8786 51.695 39.7417C51.695 40.5284 51.6838 41.3698 51.7281 42.1019C51.7837 42.8995 51.5063 43.1618 50.8407 43.0197C49.7313 42.823 48.0673 42.8777 46.7693 43.271C46.9135 46.0355 47.2906 49.9801 47.2906 50.0238C53.969 49.1387 62.2561 48.647 68.3132 45.6749C68.9457 45.3034 69.2008 45.4564 69.1675 46.3524C69.0565 48.8218 69.0898 51.9032 69.2785 54.0556C69.3672 55.0281 69.0565 55.4544 68.3576 55.3996C61.4796 54.9188 54.5459 55.0064 47.668 55.1375H47.6568ZM62.2007 42.7793C60.348 42.834 58.4954 43.0416 57.0532 43.5333C56.3876 43.7627 56.0881 43.4131 56.1989 42.5717C56.5317 40.4082 57.1197 36.3764 57.1197 33.5134C57.1197 30.312 56.5317 26.9793 56.1989 25.384C56.0881 24.7066 56.3876 24.2586 57.0865 24.0839C58.4954 23.745 60.348 23.3081 62.1896 22.9366C64.1865 22.5431 66.1167 22.2699 67.925 21.9641C68.5573 21.8984 68.8901 22.2482 68.8458 23.0566C68.7793 24.2914 68.8124 25.7774 68.8124 26.8264C68.8124 27.7442 68.4019 27.9518 67.7363 27.5694C65.5843 26.3019 63.3322 26.8045 62.1784 27.0231C62.1784 27.0231 61.9233 28.8041 61.8125 30.6726C62.955 30.5415 64.3085 29.9624 65.2182 29.5034C65.8395 29.1866 66.15 29.3723 66.1056 30.2137C66.0723 30.8365 66.0279 31.4156 66.0279 32.0931C66.0279 32.6831 66.0279 33.2293 66.0613 33.8195C66.1056 34.7263 65.7951 34.9448 65.1405 34.6609C64.2086 34.2675 62.844 33.9506 61.7679 34.049C61.8456 36.0484 62.1784 38.0591 62.1784 38.0591C64.6634 38.0591 66.6936 37.458 68.3245 36.2451C68.9124 35.7971 69.2673 36.0158 69.2119 36.9444C69.1232 38.4634 69.1232 40.2226 69.2119 41.9489C69.2562 42.8121 68.8901 43.2164 68.2468 43.129C66.4274 42.8558 64.1754 42.7247 62.1784 42.7793H62.2007Z' fill='%23FF0000'/%3e%3cpath d='M75.6454 54.1105C76.1669 49.0734 76.3887 43.8504 76.5662 38.7476C76.6995 34.8141 76.4554 31.2738 76.2002 28.564C74.9798 28.1049 73.3824 28.1269 71.4631 28.859C70.7975 29.0994 70.3539 28.706 70.387 27.8319C70.4869 25.7121 70.5534 24.6959 70.4203 23.1552C70.3539 22.3357 70.7531 21.9642 71.3854 22.1063C72.861 22.445 73.7929 22.587 75.4901 23.0241C78.4079 23.778 79.8611 24.3572 82.7787 26.1382C84.5204 27.1981 85.408 27.8536 86.8834 28.9244C87.5157 29.3835 87.9041 30.1045 87.8485 30.6727C87.7377 31.842 87.7487 33.0766 87.8485 34.6502C87.893 35.3603 87.4382 35.3384 86.7724 34.6065C84.9198 32.5741 83.3666 31.3066 82.1464 30.8149C81.8913 33.164 81.6693 36.3546 81.6693 40.0697C81.6693 46.0904 82.3018 51.8377 82.5902 54.3072C82.701 55.1376 82.3682 55.5091 81.6693 55.378C80.9372 55.236 80.2272 55.1376 79.0401 55.1158C77.8976 55.1048 77.2208 55.1922 76.5995 55.3234C75.9006 55.4654 75.5457 55.0065 75.6344 54.0886L75.6454 54.1105Z' fill='%23FF0000'/%3e%3c/g%3e%3cdefs%3e%3cclipPath id='clip0_108_53'%3e%3crect width='88' height='56' fill='white'/%3e%3c/clipPath%3e%3c/defs%3e%3c/svg%3e"


    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            @media print {{
                * {{ -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }}
                body {{ margin: 0; padding: 20px; font-family: Arial, sans-serif; color: #000; text-transform: uppercase; }}
                @page {{ size: 80mm auto; margin: 0; }}
            }}
            body {{ width: 80mm; margin: 0 auto; padding: 10mm; font-family: Arial, sans-serif; text-transform: uppercase; }}
            .header {{ text-align: center; margin-bottom: 20px; border-bottom: 3px solid #000; padding-bottom: 15px; }}
            .logo {{ width: 36mm; height: auto; margin-bottom: 10px; }}
            .title {{ font-size: 24px; font-weight: 900; margin: 10px 0; }}
            .order-info {{ font-size: 14px; font-weight: 700; margin: 15px 0; padding: 10px; background: #f0f0f0; border: 2px solid #000; }}
            .display-number {{ font-size: 48px; font-weight: 900; text-align: center; margin: 20px 0; padding: 20px; border: 4px solid #000; background: #000; color: #fff; }}
            table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
            td {{ padding: 8px 0; border-bottom: 1px dashed #000; }}
            .main-item-desc {{ font-weight: 900; font-size: 18px; border-top: 3px solid #000; padding-top: 12px; }}
            .main-item-price {{ font-weight: 900; font-size: 18px; border-top: 3px solid #000; padding-top: 12px; text-align: right; }}
            .sub-item-desc {{ padding-left: 25px !important; font-size: 16px; }}
            .sub-item-price {{ font-size: 16px; text-align: right; }}
            .item-notes {{ padding-left: 25px !important; font-style: italic; font-size: 14px; }}
            .totals-section {{ margin-top: 20px; padding-top: 15px; border-top: 3px solid #000; }}
            .totals-row {{ display: flex; justify-content: space-between; font-size: 16px; font-weight: 700; padding: 4px 0; }}
            .total-final {{ font-size: 20px; font-weight: 900; border-top: 3px solid #000; margin-top: 5px; padding-top: 10px; }}
            .footer {{ text-align: center; margin-top: 25px; padding-top: 15px; border-top: 3px solid #000; font-size: 12px; font-weight: 700; }}
        </style>
    </head>
    <body>
        <div class="header">
            <img src="PASTE_LOGO_SVG_URI_HERE" alt="Logo" class="logo">
            <div class="title">CUSTOMER RECEIPT</div>
        </div>
        <div class="display-number">#{order.get('display_number', 'N/A')}</div>
        <div class="order-info">
            <div><strong>ORDER:</strong> {order.get('order_number', '')}</div>
            <div><strong>BATCH:</strong> {order.get('batch_id', 'N/A')}</div>
            <div><strong>TYPE:</strong> {order.get('order_placement_type', '').upper()}</div>
            <div><strong>CUSTOMER:</strong> {order.get('customer_name', 'WALK-IN')}</div>
            <div><strong>DAY:</strong> {order_day}</div>
            <div><strong>TIME:</strong> {order_time}</div>
        </div>
        <table><tbody>{items_html}</tbody></table>
        <div class="totals-section">
            <div class="totals-row"><span>SUBTOTAL</span><span>{format_currency(order.get('subtotal'))}</span></div>
            <div class="totals-row"><span>TAX</span><span>{format_currency(order.get('tax'))}</span></div>
            <div class="totals-row total-final"><span>TOTAL</span><span>{format_currency(order.get('total'))}</span></div>
        </div>
        <div class="footer"><div>COOKING WITH LOVE FOR YOU</div></div>
    </body>
    </html>
    """

    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "print", "order_receipt", order_id, {"order_number": order["order_number"]}, 
        request
    )

    return HTMLResponse(content=html_content)





