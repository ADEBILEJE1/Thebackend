from fastapi import APIRouter, HTTPException, status, Depends, Request, BackgroundTasks, Query
from typing import List, Optional,  Dict, Any
from datetime import datetime, date, timedelta
from decimal import Decimal
import random
import uuid
from .sales_service import SalesService
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
# async def get_products_for_orders(
#     request: Request,
#     category_id: Optional[str] = None,
#     search: Optional[str] = None,
#     min_price: Optional[float] = None,
#     max_price: Optional[float] = None,
#     include_low_stock: bool = True,
#     current_user: dict = Depends(require_sales_staff)
# ):
#     """Get products for sales order creation with tax information"""
#     await default_limiter.check_rate_limit(request, current_user["id"])
    
#     cache_key = f"sales:products:{category_id}:{search}:{min_price}:{max_price}:{include_low_stock}"
#     cached = redis_client.get(cache_key)
#     if cached:
#         return cached
    
#     query = supabase.table("products").select("""
#         id, sku, name, variant_name, price, tax_per_unit, preparation_time_minutes, 
#         description, image_url, units, status, is_available,
#         categories(id, name)
#     """).eq("is_available", True).eq("product_type", "main")
    
#     if not include_low_stock:
#         query = query.neq("status", "low_stock").neq("status", "out_of_stock")
#     else:
#         query = query.neq("status", "out_of_stock")
    
#     if category_id:
#         query = query.eq("category_id", category_id)
    
#     if search:
#         query = query.or_(f"name.ilike.%{search}%,categories.name.ilike.%{search}%")
    
#     if min_price:
#         query = query.gte("price", min_price)
    
#     if max_price:
#         query = query.lte("price", max_price)
    
#     result = query.execute()
    
#     products = []
#     for product in result.data:
#         display_name = product["name"]
#         if product.get("variant_name"):
#             display_name += f" - {product['variant_name']}"
        
#         category = {"id": None, "name": "Uncategorized"}
#         if product.get("categories") and product["categories"]:
#             category = product["categories"]
        
#         # Fetch extras for this main product
#         formatted_extras = []
#         extras = supabase.table("products").select("*").eq("main_product_id", product["id"]).eq("is_available", True).execute()
        
#         for extra in extras.data:
#             extra_display_name = extra["name"]
#             if extra.get("variant_name"):
#                 extra_display_name += f" - {extra['variant_name']}"
            
#             formatted_extras.append({
#                 "id": extra["id"],
#                 "name": extra_display_name,
#                 "price": float(extra["price"]),
#                 "tax_per_unit": float(extra.get("tax_per_unit", 0)),  # New field
#                 "preparation_time_minutes": extra.get("preparation_time_minutes", 15),  # New field
#                 "description": extra["description"],
#                 "image_url": extra["image_url"],
#                 "available_stock": extra["units"],
#                 "status": extra["status"]
#             })
        
#         products.append({
#             "id": product["id"],
#             "name": display_name,
#             "price": float(product["price"]),
#             "tax_per_unit": float(product.get("tax_per_unit", 0)),  # New field
#             "preparation_time_minutes": product.get("preparation_time_minutes", 15),  # New field
#             "description": product["description"],
#             "image_url": product["image_url"],
#             "available_stock": product["units"],
#             "status": product["status"],
#             "category": category,
#             "extras": formatted_extras
#         })
    
#     redis_client.set(cache_key, products, 60)
#     return products



# @router.get("/products")
# async def get_products_for_orders(
#     request: Request,
#     category_id: Optional[str] = None,
#     search: Optional[str] = None,
#     min_price: Optional[float] = None,
#     max_price: Optional[float] = None,
#     include_low_stock: bool = True,
#     current_user: dict = Depends(require_sales_staff)
# ):
#     await default_limiter.check_rate_limit(request, current_user["id"])
    
#     cache_key = f"sales:products:{category_id}:{search}:{min_price}:{max_price}:{include_low_stock}"
#     cached = redis_client.get(cache_key)
#     if cached:
#         return cached
    
#     query = supabase.table("products").select("""
#         id, sku, name, variant_name, price, tax_per_unit, preparation_time_minutes, 
#         description, image_url, units, status, is_available, has_options,
#         categories(id, name)
#     """).eq("is_available", True).eq("product_type", "main")
    
#     if not include_low_stock:
#         query = query.neq("status", "low_stock").neq("status", "out_of_stock")
#     else:
#         query = query.neq("status", "out_of_stock")
    
#     if category_id:
#         query = query.eq("category_id", category_id)
#     if search:
#         query = query.or_(f"name.ilike.%{search}%,categories.name.ilike.%{search}%")
#     if min_price:
#         query = query.gte("price", min_price)
#     if max_price:
#         query = query.lte("price", max_price)
    
#     result = query.execute()
    
#     products = []
#     for product in result.data:
#         display_name = product["name"]
#         if product.get("variant_name"):
#             display_name += f" - {product['variant_name']}"
        
#         category = {"id": None, "name": "Uncategorized"}
#         if product.get("categories") and product["categories"]:
#             category = product["categories"]
        
#         # Fetch options if product has them
#         product_options = []
#         if product.get("has_options"):
#             options = supabase.table("product_options").select("*").eq("product_id", product["id"]).order("display_order").execute()
#             product_options = [
#                 {
#                     "id": opt["id"],
#                     "name": opt["name"],
#                     "price_modifier": float(opt.get("price_modifier", 0))
#                 }
#                 for opt in options.data
#             ]
        
#         # Fetch extras
#         formatted_extras = []
#         extras = supabase.table("products").select("*").eq("main_product_id", product["id"]).eq("is_available", True).execute()
        
#         for extra in extras.data:
#             extra_display_name = extra["name"]
#             if extra.get("variant_name"):
#                 extra_display_name += f" - {extra['variant_name']}"
            
#             formatted_extras.append({
#                 "id": extra["id"],
#                 "name": extra_display_name,
#                 "price": float(extra["price"]),
#                 "tax_per_unit": float(extra.get("tax_per_unit", 0)),
#                 "preparation_time_minutes": extra.get("preparation_time_minutes", 15),
#                 "description": extra["description"],
#                 "image_url": extra["image_url"],
#                 "available_stock": extra["units"],
#                 "status": extra["status"]
#             })
        
#         products.append({
#             "id": product["id"],
#             "name": display_name,
#             "price": float(product["price"]),
#             "tax_per_unit": float(product.get("tax_per_unit", 0)),
#             "preparation_time_minutes": product.get("preparation_time_minutes", 15),
#             "description": product["description"],
#             "image_url": product["image_url"],
#             "available_stock": product["units"],
#             "status": product["status"],
#             "category": category,
#             "has_options": product.get("has_options", False),
#             "options": product_options,
#             "extras": formatted_extras
#         })
    
#     redis_client.set(cache_key, products, 60)
#     return products




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

    query = supabase_admin.table("products").select("*, categories(*)").eq("is_available", True).eq("product_type", "main")

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
    
    # Batch fetch extras and options
    product_ids = [p["id"] for p in products_result.data]
    
    extras_result = supabase_admin.table("products").select("*").in_("main_product_id", product_ids).eq("is_available", True).execute()
    options_result = supabase_admin.table("product_options").select("*").in_("product_id", product_ids).execute()
    
    # Map extras by main_product_id
    extras_map = {}
    for extra in extras_result.data:
        if extra["main_product_id"] not in extras_map:
            extras_map[extra["main_product_id"]] = []
        extras_map[extra["main_product_id"]].append(extra)
    
    # Map options by product_id
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
               (p.get("categories") and search_lower in p["categories"]["name"].lower())
        ]
    
    # Format response
    products = []
    for product in products_result.data:
        display_name = product["name"]
        if product.get("variant_name"):
            display_name += f" - {product['variant_name']}"
        
        category = product.get("categories") or {"id": None, "name": "Uncategorized"}
        
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
    
    sorted_data = sorted(products, key=lambda x: (x["category"]["name"], x["name"]))
    
    redis_client.set(cache_key, sorted_data, 300)
    return sorted_data


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
        "timestamp": datetime.utcnow().isoformat()
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
    
    end_date = datetime.utcnow()
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
    
    end_date = datetime.utcnow()
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
    
    supabase_admin.table("orders").update({
        "status": "preparing",
        "preparing_at": datetime.utcnow().isoformat()
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
    
    processed_items = await SalesService.validate_sales_cart_items(order_data.items)
    totals = CartService.calculate_order_total(processed_items)
    
    total_prep_time = sum(
        item["preparation_time_minutes"] * item["quantity"] 
        for item in processed_items
    )
    
    batch_id = SalesService.generate_batch_id()
    batch_created_at = datetime.utcnow().isoformat()
    display_number = SalesService.get_next_display_number()
    order_number = f"ORD-{datetime.now().strftime('%Y%m%d')}-{random.randint(100, 999):03d}"
    
    order_entry = {
        "order_number": order_number,
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
        "status": "preparing",
        "payment_status": "paid",
        "preparing_at": datetime.utcnow().isoformat()
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
    
    # Fetch options for each order item
    for order in result.data:
        for item in order["order_items"]:
            options_result = supabase_admin.table("order_item_options").select("""
                option_id,
                product_options(id, name)
            """).eq("order_item_id", item["id"]).execute()
            
            item["options"] = [
                {
                    "id": opt["product_options"]["id"],
                    "name": opt["product_options"]["name"]
                }
                for opt in options_result.data if opt.get("product_options")
            ]
    
    return result.data


# @router.get("/orders/pending")
# async def get_pending_orders(
#     current_user: dict = Depends(require_sales_staff)
# ):
#     """Get all pending orders"""
#     result = supabase_admin.table("orders").select("""
#         *, 
#         order_items(
#             *,
#             products(id, name, price, image_url),
#             order_item_options(
#                 option_id,
#                 product_options(id, name)
#             )
#         )
#     """).eq("status", "pending").order("created_at", desc=True).execute()
    
#     # Clean up the nested structure
#     for order in result.data:
#         for item in order.get("order_items", []):
#             item["options"] = [
#                 {
#                     "id": opt["product_options"]["id"],
#                     "name": opt["product_options"]["name"]
#                 }
#                 for opt in item.get("order_item_options", []) 
#                 if opt.get("product_options")
#             ]
#             item.pop("order_item_options", None)
    
#     return result.data


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
    result = supabase_admin.table("orders").select("*, order_items(*)").eq("status", "confirmed").not_.is_("batch_id", "null").order("batch_created_at").execute()
    
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


@router.get("/batches/{batch_id}/details")
async def get_batch_details(
    batch_id: str,
    current_user: dict = Depends(require_sales_staff)
):
    """Get detailed information about a specific batch"""
    orders = supabase_admin.table("orders").select("""
        *, 
        order_items(*),
        customer_addresses(full_address, delivery_areas(name, estimated_time)),
        website_customers(full_name, email, phone)
    """).eq("batch_id", batch_id).execute()
    
    if not orders.data:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    # Extract comprehensive customer and delivery info
    first_order = orders.data[0]
    customer_info = {
        "name": first_order.get("customer_name") or (first_order.get("website_customers", {}) or {}).get("full_name"),
        "phone": first_order.get("customer_phone") or (first_order.get("website_customers", {}) or {}).get("phone"),
        "email": first_order.get("customer_email") or (first_order.get("website_customers", {}) or {}).get("email")
    }
    
    delivery_info = first_order.get("customer_addresses")
    
    total_items = sum(len(order.get("order_items") or []) for order in orders.data)
    total_amount = sum(float(order["total"]) for order in orders.data)
    
    return {
        "batch_id": batch_id,
        "orders": orders.data,
        "customer_info": customer_info,
        "delivery_info": delivery_info,
        "summary": {
            "order_count": len(orders.data),
            "total_items": total_items,
            "total_amount": total_amount,
            "status": orders.data[0]["status"] if orders.data else None,
            "batch_created_at": orders.data[0]["batch_created_at"] if orders.data else None
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
    
    order_ids = [o["id"] for o in orders.data]
    
    # Update all orders to preparing
    supabase.table("orders").update({
        "status": "preparing",
        "preparing_at": datetime.utcnow().isoformat()
    }).in_("id", order_ids).execute()
    
    # Stock already deducted during confirmation - no deduction here
    
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
    """).not_.is_("batch_id", "null").in_("status", ["preparing", "completed"]).order("preparing_at", desc=True).range(offset, offset + limit - 1).execute()
    
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
                "updated_at": datetime.utcnow().isoformat()
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
    
    end_date = datetime.utcnow()
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