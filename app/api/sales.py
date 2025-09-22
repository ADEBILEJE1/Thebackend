from fastapi import APIRouter, HTTPException, status, Depends, Request, BackgroundTasks, Query
from typing import List, Optional,  Dict, Any
from datetime import datetime, date, timedelta
from decimal import Decimal
import random
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
    notes: Optional[str] = None

class OrderConfirm(BaseModel):
    payment_confirmed: bool



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



@router.get("/products")
async def get_products_for_orders(
    request: Request,
    category_id: Optional[str] = None,
    search: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    include_low_stock: bool = True,
    current_user: dict = Depends(require_sales_staff)
):
    """Get products for sales order creation"""
    await default_limiter.check_rate_limit(request, current_user["id"])
    
    cache_key = f"sales:products:{category_id}:{search}:{min_price}:{max_price}:{include_low_stock}"
    cached = redis_client.get(cache_key)
    if cached:
        return cached
    
    query = supabase.table("products").select("""
        id, sku, variant_name, price, description, image_url, units, status, is_available,
        product_templates(name),
        categories(id, name)
    """).eq("is_available", True)
    
    if not include_low_stock:
        query = query.neq("status", "low_stock").neq("status", "out_of_stock")
    else:
        query = query.neq("status", "out_of_stock")
    
    if category_id:
        query = query.eq("category_id", category_id)
    
    if search:
        query = query.or_(f"product_templates.name.ilike.%{search}%,categories.name.ilike.%{search}%")
    
    if min_price:
        query = query.gte("price", min_price)
    
    if max_price:
        query = query.lte("price", max_price)
    
    result = query.execute()
    
    products = []
    for product in result.data:
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
            "status": product["status"],
            "category": category
        })
    
    redis_client.set(cache_key, products, 60)
    return products

@router.get("/categories")
async def get_categories_for_orders(
    current_user: dict = Depends(require_sales_staff)
):
    """Get categories for order creation"""
    cached = redis_client.get("sales:categories")
    if cached:
        return cached
    
    result = supabase.table("categories").select("*").eq("is_active", True).order("name").execute()
    
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
    
    from .kitchen import deduct_stock
    await deduct_stock(order.data[0]["order_items"])
    
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



@router.post("/orders/validate-cart")
async def validate_sales_cart(
    items: List[Dict[str, Any]],
    current_user: dict = Depends(require_sales_staff)
):
    """Validate cart items for sales order"""
    try:
        # Use website cart validation logic
        processed_items = await CartService.validate_cart_items(items)
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

@router.post("/orders")
async def create_offline_order(
    order_data: OfflineOrderCreate,
    request: Request,
    current_user: dict = Depends(require_sales_staff)
):
    """Create offline order (pending payment)"""
    # Validate items
    processed_items = await CartService.validate_cart_items(order_data.items)
    totals = CartService.calculate_order_total(processed_items)
    
    # Generate order number
    order_number = f"ORD-{datetime.now().strftime('%Y%m%d')}-{random.randint(100, 999):03d}"
    
    # Create order (pending status)
    order_entry = {
        "order_number": order_number,
        "order_type": "offline",
        "status": "pending",
        "payment_status": "pending",
        "payment_method": order_data.payment_method,
        "customer_name": order_data.customer_name,
        "customer_phone": order_data.customer_phone,
        "subtotal": float(totals["subtotal"]),
        "tax": float(totals["vat"]),
        "total": float(totals["total"]),
        "notes": order_data.notes,
        "created_by": current_user["id"]
    }
    
    created_order = supabase_admin.table("orders").insert(order_entry).execute()
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
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "create", "offline_order", order_id, 
        {"order_number": order_number, "total": float(totals["total"])}, 
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
    order = supabase.table("orders").select("*, order_items(*)").eq("id", order_id).eq("status", "pending").execute()
    
    if not order.data:
        raise HTTPException(status_code=404, detail="Pending order not found")
    
    # Update order status
    supabase.table("orders").update({
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
    """Generate printable sales receipt"""
    order = supabase.table("orders").select("*, order_items(*)").eq("id", order_id).execute()
    
    if not order.data:
        raise HTTPException(status_code=404, detail="Order not found")
    
    order_data = order.data[0]
    
    receipt_data = {
        "order_number": order_data["order_number"],
        "order_type": order_data["order_type"],
        "customer_name": order_data.get("customer_name", "Walk-in Customer"),
        "payment_method": order_data.get("payment_method"),
        "created_at": order_data["created_at"],
        "items": order_data["order_items"],
        "subtotal": order_data["subtotal"],
        "tax": order_data["tax"],
        "total": order_data["total"]
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
    # Check order is pending
    order = supabase.table("orders").select("*").eq("id", order_id).eq("status", "pending").execute()
    
    if not order.data:
        raise HTTPException(status_code=404, detail="Pending order not found")
    
    # Validate new items
    processed_items = await CartService.validate_cart_items(items)
    totals = CartService.calculate_order_total(processed_items)
    
    # Delete existing items
    supabase.table("order_items").delete().eq("order_id", order_id).execute()
    
    # Create new items
    for item in processed_items:
        item_data = {
            "order_id": order_id,
            "product_id": item["product_id"],
            "product_name": item["product_name"],
            "quantity": item["quantity"],
            "unit_price": float(item["unit_price"]),
            "total_price": float(item["total_price"])
        }
        supabase.table("order_items").insert(item_data).execute()
    
    # Update order totals
    supabase.table("orders").update({
        "subtotal": float(totals["subtotal"]),
        "tax": float(totals["vat"]),
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