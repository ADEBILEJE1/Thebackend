from typing import List, Dict, Optional, Any
from datetime import datetime, date, timedelta
from decimal import Decimal
import uuid
from collections import defaultdict
from ..database import supabase, supabase_admin
from ..services.redis import redis_client
from ..core.cache import CacheKeys
from ..models.order import OrderType, OrderStatus, PaymentStatus
from ..models.user import UserRole


class SalesService:
    """Service class for sales dashboard operations"""
    


    @staticmethod
    async def get_sales_dashboard_overview(user_role: str) -> Dict[str, Any]:
        """Get comprehensive sales dashboard overview - unified for all sales staff"""
        cache_key = f"sales:dashboard:overview:unified"
        cached = redis_client.get(cache_key)
        if cached:
            return cached
        
        # Use Nigeria timezone (Lagos)
        import pytz
        from decimal import Decimal
        
        nigeria_tz = pytz.timezone('Africa/Lagos')
        today_nigeria = datetime.now(nigeria_tz).date()
        start_of_day = datetime.combine(today_nigeria, datetime.min.time())
        start_of_day_utc = nigeria_tz.localize(start_of_day).astimezone(pytz.UTC)
        
        # Get ALL orders from start of Nigerian business day
        orders_result = supabase.table("orders").select("*, order_items(*)").gte("created_at", start_of_day_utc.isoformat()).execute()
        orders = orders_result.data
        
        # Count all non-cancelled orders (both online and offline)
        non_cancelled_orders = [o for o in orders if o["status"] != "cancelled"]
        total_orders = len(non_cancelled_orders)
        
        # Revenue from paid orders (completed + confirmed with payment)
        paid_orders = [
            o for o in orders 
            if o["status"] == "completed" or 
            (o["status"] == "confirmed" and o["payment_status"] == "paid")
        ]
        
        # Use Decimal for precise money calculations
        total_revenue = sum(Decimal(str(o["total"])) for o in paid_orders)
        average_order_value = total_revenue / len(paid_orders) if paid_orders else Decimal('0')
        
        # Order status breakdown
        completed_orders = [o for o in orders if o["status"] == "completed"]
        pending_orders = [o for o in orders if o["status"] == "pending"]
        preparing_orders = [o for o in orders if o["status"] == "preparing"]
        cancelled_orders = [o for o in orders if o["status"] == "cancelled"]
        
        # Order type breakdown (from non-cancelled orders)
        online_orders = [o for o in non_cancelled_orders if o["order_type"] == "online"]
        offline_orders = [o for o in non_cancelled_orders if o["order_type"] == "offline"]
        
        # Top products today (from completed orders only)
        product_sales = defaultdict(lambda: {"quantity": 0, "revenue": Decimal('0'), "orders": 0})
        
        for order in completed_orders:
            for item in order["order_items"]:
                product_name = item["product_name"]
                product_sales[product_name]["quantity"] += item["quantity"]
                product_sales[product_name]["revenue"] += Decimal(str(item["total_price"]))
                product_sales[product_name]["orders"] += 1
        
        top_products = sorted(
            [{"name": k, "quantity": v["quantity"], "revenue": float(v["revenue"]), "orders": v["orders"]} for k, v in product_sales.items()],
            key=lambda x: x["revenue"],
            reverse=True
        )[:5]
        
        # Hourly breakdown
        hourly_sales = defaultdict(lambda: {"orders": 0, "revenue": Decimal('0')})
        for order in orders:
            hour = datetime.fromisoformat(order["created_at"]).hour
            hourly_sales[hour]["orders"] += 1
            if order["status"] == "completed":
                hourly_sales[hour]["revenue"] += Decimal(str(order["total"]))
        
        dashboard_data = {
            "summary": {
                "total_orders": total_orders,
                "completed_orders": len(completed_orders),
                "pending_orders": len(pending_orders),
                "preparing_orders": len(preparing_orders),
                "cancelled_orders": len(cancelled_orders),
                "total_revenue": float(total_revenue),
                "average_order_value": float(average_order_value)
            },
            "order_breakdown": {
                "online_orders": len(online_orders),
                "offline_orders": len(offline_orders),
                "completion_rate": round((len(completed_orders) / total_orders * 100), 2) if total_orders > 0 else 0
            },
            "top_products_today": top_products,
            "hourly_breakdown": [
                {"hour": hour, "orders": data["orders"], "revenue": float(data["revenue"])} 
                for hour, data in sorted(hourly_sales.items())
            ],
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Cache for 30 seconds
        redis_client.set(cache_key, dashboard_data, 30)
        
        return dashboard_data


    
    @staticmethod
    async def get_revenue_analytics(days: int = 30) -> Dict[str, Any]:
        """Get detailed revenue analytics over specified period - unified view"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Get ALL orders - no user filtering
        orders_result = supabase_admin.table("orders").select("*").gte("created_at", start_date.isoformat()).execute()
        orders = orders_result.data
        
        # Daily revenue breakdown
        daily_revenue = defaultdict(lambda: {
            "orders": 0, 
            "revenue": 0, 
            "online_revenue": 0, 
            "offline_revenue": 0,
            "cancelled_revenue": 0
        })
        
        total_revenue = 0
        total_orders = len(orders)
        completed_orders = 0
        
        for order in orders:
            order_date = order["created_at"][:10]
            revenue = float(order["total"])
            
            daily_revenue[order_date]["orders"] += 1
            
            if order["status"] != "cancelled":
                daily_revenue[order_date]["revenue"] += revenue
                total_revenue += revenue
                completed_orders += 1
                
                if order["order_type"] == "online":
                    daily_revenue[order_date]["online_revenue"] += revenue
                else:
                    daily_revenue[order_date]["offline_revenue"] += revenue
            else:
                daily_revenue[order_date]["cancelled_revenue"] += revenue
        
        # Calculate growth rates
        if days >= 7:
            this_week_start = end_date - timedelta(days=7)
            last_week_start = end_date - timedelta(days=14)
            
            this_week_revenue = sum(
                float(o["total"]) for o in orders 
                if o["status"] != "cancelled" 
                and o.get("created_at")
                and o["created_at"] >= this_week_start.isoformat()
            )
            
            last_week_revenue = sum(
                float(o["total"]) for o in orders 
                if o["status"] != "cancelled" 
                and o.get("created_at")
                and last_week_start.isoformat() <= o["created_at"] < this_week_start.isoformat()
            )
            
            growth_rate = ((this_week_revenue - last_week_revenue) / last_week_revenue * 100) if last_week_revenue > 0 else 0
        else:
            growth_rate = 0
        
        # Peak performance analysis
        daily_data = [{"date": k, **v} for k, v in sorted(daily_revenue.items())]
        best_day = max(daily_data, key=lambda x: x["revenue"]) if daily_data else None
        
        return {
            "period": {"start": start_date.date(), "end": end_date.date(), "days": days},
            "summary": {
                "total_revenue": round(total_revenue, 2),
                "total_orders": total_orders,
                "completed_orders": completed_orders,
                "average_daily_revenue": round(total_revenue / days, 2),
                "growth_rate_percent": round(growth_rate, 2)
            },
            "daily_breakdown": daily_data,
            "best_performing_day": best_day,
            "online_vs_offline": {
                "online_percentage": round(
                    sum(day["online_revenue"] for day in daily_data) / total_revenue * 100, 2
                ) if total_revenue > 0 else 0,
                "offline_percentage": round(
                    sum(day["offline_revenue"] for day in daily_data) / total_revenue * 100, 2
                ) if total_revenue > 0 else 0
            }
        }
    
    @staticmethod
    async def get_staff_performance(days: int = 30, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Get sales staff performance metrics"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Get all sales staff
        staff_query = supabase.table("profiles").select("*").eq("role", "sales").eq("is_active", True)
        
        # If specific user requested, filter
        if user_id:
            staff_query = staff_query.eq("id", user_id)
        
        staff_result = staff_query.execute()
        staff_members = staff_result.data
        
        performance_data = []
        
        for staff in staff_members:
            # Get orders created by this staff member
            orders_result = supabase.table("orders").select("*").eq("created_by", staff["id"]).gte("created_at", start_date.isoformat()).execute()
            
            orders = orders_result.data
            completed_orders = [o for o in orders if o["status"] == "completed"]
            cancelled_orders = [o for o in orders if o["status"] == "cancelled"]
            
            total_revenue = sum(float(o["total"]) for o in completed_orders)
            total_orders = len(orders)
            
            # Calculate performance metrics
            completion_rate = (len(completed_orders) / total_orders * 100) if total_orders > 0 else 0
            cancellation_rate = (len(cancelled_orders) / total_orders * 100) if total_orders > 0 else 0
            average_order_value = total_revenue / len(completed_orders) if completed_orders else 0
            
            # Get activity data
            activity_result = supabase.table("activity_logs").select("action").eq("user_id", staff["id"]).gte("created_at", start_date.isoformat()).execute()
            
            performance_data.append({
                "staff_id": staff["id"],
                "staff_email": staff["email"],
                "total_orders": total_orders,
                "completed_orders": len(completed_orders),
                "cancelled_orders": len(cancelled_orders),
                "total_revenue": round(total_revenue, 2),
                "average_order_value": round(average_order_value, 2),
                "completion_rate": round(completion_rate, 2),
                "cancellation_rate": round(cancellation_rate, 2),
                "daily_average_orders": round(total_orders / days, 2),
                "daily_average_revenue": round(total_revenue / days, 2),
                "total_activities": len(activity_result.data),
                "last_active": staff.get("last_login")
            })
        
        # Sort by total revenue
        performance_data.sort(key=lambda x: x["total_revenue"], reverse=True)
        
        # Calculate team totals
        team_totals = {
            "total_team_revenue": sum(p["total_revenue"] for p in performance_data),
            "total_team_orders": sum(p["total_orders"] for p in performance_data),
            "average_completion_rate": sum(p["completion_rate"] for p in performance_data) / len(performance_data) if performance_data else 0,
            "top_performer": performance_data[0] if performance_data else None
        }
        
        return {
            "period": {"start": start_date.date(), "end": end_date.date(), "days": days},
            "staff_performance": performance_data,
            "team_summary": team_totals
        }
    
    @staticmethod
    async def get_customer_analytics(days: int = 30) -> Dict[str, Any]:
        """Analyze customer behavior and patterns"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Get orders with customer info
        orders_result = supabase_admin.table("orders").select("*").gte("created_at", start_date.isoformat()).neq("status", "cancelled").execute()
        
        orders = orders_result.data
        
        # Customer analysis
        customer_data = defaultdict(lambda: {
            "orders": 0, 
            "total_spent": 0, 
            "first_order": None, 
            "last_order": None,
            "order_types": {"online": 0, "offline": 0}
        })
        
        for order in orders:
            # Use email for online orders, phone for offline orders as customer identifier
            customer_id = order.get("customer_email") or order.get("customer_phone") or "anonymous"
            
            if customer_id != "anonymous":
                customer_data[customer_id]["orders"] += 1
                customer_data[customer_id]["total_spent"] += float(order["total"])
                customer_data[customer_id]["order_types"][order["order_type"]] += 1
                
                order_date = order["created_at"]
                if not customer_data[customer_id]["first_order"]:
                    customer_data[customer_id]["first_order"] = order_date
                customer_data[customer_id]["last_order"] = order_date
        
        # Calculate customer segments
        total_customers = len(customer_data)
        returning_customers = len([c for c in customer_data.values() if c["orders"] > 1])
        new_customers = total_customers - returning_customers
        
        # Top customers by spend
        top_customers = sorted(
            [{"customer_id": k, **v} for k, v in customer_data.items()],
            key=lambda x: x["total_spent"],
            reverse=True
        )[:10]
        
        # Calculate customer lifetime value
        average_customer_value = sum(c["total_spent"] for c in customer_data.values()) / total_customers if total_customers > 0 else 0
        average_orders_per_customer = sum(c["orders"] for c in customer_data.values()) / total_customers if total_customers > 0 else 0
        
        # Order frequency analysis
        repeat_customers = [c for c in customer_data.values() if c["orders"] > 1]
        high_value_customers = [c for c in customer_data.values() if c["total_spent"] > average_customer_value * 2]
        
        return {
            "period": {"start": start_date.date(), "end": end_date.date(), "days": days},
            "customer_summary": {
                "total_customers": total_customers,
                "new_customers": new_customers,
                "returning_customers": returning_customers,
                "retention_rate": round((returning_customers / total_customers * 100), 2) if total_customers > 0 else 0
            },
            "customer_value": {
                "average_customer_value": round(average_customer_value, 2),
                "average_orders_per_customer": round(average_orders_per_customer, 2),
                "high_value_customers_count": len(high_value_customers)
            },
            "top_customers": [
                {
                    "customer_id": c["customer_id"],
                    "total_orders": c["orders"],
                    "total_spent": round(c["total_spent"], 2),
                    "average_order_value": round(c["total_spent"] / c["orders"], 2),
                    "customer_since": c["first_order"][:10]
                }
                for c in top_customers
            ],
            "order_patterns": {
                "online_preference": len([c for c in customer_data.values() if c["order_types"]["online"] > c["order_types"]["offline"]]),
                "offline_preference": len([c for c in customer_data.values() if c["order_types"]["offline"] > c["order_types"]["online"]]),
                "mixed_preference": len([c for c in customer_data.values() if c["order_types"]["online"] > 0 and c["order_types"]["offline"] > 0])
            }
        }
    



    @staticmethod
    async def get_product_sales_analysis(days: int = 30) -> Dict[str, Any]:
        """Analyze product sales performance"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Get order items with product details
        order_items_result = supabase.table("order_items").select(
            "*, orders!inner(created_at, status), products!inner(name, price, categories(name))"
        ).gte("orders.created_at", start_date.isoformat()).neq("orders.status", "cancelled").execute()
        
        order_items = order_items_result.data
        
        # Product performance analysis
        product_performance = defaultdict(lambda: {
            "quantity_sold": 0,
            "revenue": 0,
            "orders": set(),
            "category": "",
            "unit_price": 0
        })
        
        category_performance = defaultdict(lambda: {"quantity": 0, "revenue": 0, "products": set()})
        
        for item in order_items:
            product_name = item["products"]["name"]
            category_name = item["products"]["categories"]["name"]
            quantity = item["quantity"]
            revenue = float(item["total_price"])
            order_id = item["order_id"]
            
            product_performance[product_name]["quantity_sold"] += quantity
            product_performance[product_name]["revenue"] += revenue
            product_performance[product_name]["orders"].add(order_id)
            product_performance[product_name]["category"] = category_name
            product_performance[product_name]["unit_price"] = float(item["products"]["price"])
            
            category_performance[category_name]["quantity"] += quantity
            category_performance[category_name]["revenue"] += revenue
            category_performance[category_name]["products"].add(product_name)
        
        # Convert to lists and calculate metrics
        product_list = []
        for product_name, data in product_performance.items():
            order_frequency = len(data["orders"])
            avg_quantity_per_order = data["quantity_sold"] / order_frequency if order_frequency > 0 else 0
            
            product_list.append({
                "product_name": product_name,
                "category": data["category"],
                "quantity_sold": data["quantity_sold"],
                "revenue": round(data["revenue"], 2),
                "order_frequency": order_frequency,
                "average_quantity_per_order": round(avg_quantity_per_order, 2),
                "revenue_per_unit": round(data["revenue"] / data["quantity_sold"], 2) if data["quantity_sold"] > 0 else 0,
                "daily_average_sales": round(data["quantity_sold"] / days, 2)
            })
        
        category_list = [
            {
                "category": k,
                "quantity_sold": v["quantity"],
                "revenue": round(v["revenue"], 2),
                "product_count": len(v["products"]),
                "average_revenue_per_product": round(v["revenue"] / len(v["products"]), 2) if v["products"] else 0
            }
            for k, v in category_performance.items()
        ]
        
        # Sort by different metrics
        top_by_quantity = sorted(product_list, key=lambda x: x["quantity_sold"], reverse=True)[:10]
        top_by_revenue = sorted(product_list, key=lambda x: x["revenue"], reverse=True)[:10]
        top_by_frequency = sorted(product_list, key=lambda x: x["order_frequency"], reverse=True)[:10]
        
        # Add inventory insights for sales alerts
        inventory_insights = {
            "unavailable_bestsellers": [],
            "critical_reorder_needed": []
        }
        
        # Get current product stock status
        products_result = supabase.table("products").select("id, name, units, status, low_stock_threshold").execute()
        products_stock = {p["name"]: p for p in products_result.data}
        
        # Find unavailable bestsellers (out of stock products that sold well)
        for product in top_by_quantity[:10]:  # Top 10 by quantity
            product_name = product["product_name"]
            if product_name in products_stock and products_stock[product_name]["status"] == "out_of_stock":
                inventory_insights["unavailable_bestsellers"].append({
                    "product_name": product_name,
                    "quantity_sold": product["quantity_sold"],
                    "daily_average_sales": product["daily_average_sales"]
                })
        
        # Find critical reorder needed
        for product in product_list:
            product_name = product["product_name"]
            if product_name in products_stock:
                stock_data = products_stock[product_name]
                if stock_data["status"] == "low_stock":
                    days_coverage = stock_data["units"] / product["daily_average_sales"] if product["daily_average_sales"] > 0 else 0
                    if days_coverage < 3:  # Less than 3 days stock
                        inventory_insights["critical_reorder_needed"].append({
                            "product_name": product_name,
                            "current_stock": stock_data["units"],
                            "daily_average_sales": product["daily_average_sales"],
                            "stock_coverage_days": round(days_coverage, 1),
                            "reorder_urgency": "critical" if days_coverage < 1 else "high"
                        })
        
        # Add sales recommendations
        sales_recommendations = {
            "immediate_actions": [
                "Restock critical items immediately",
                "Promote high-margin products",
                "Focus on bestselling categories",
                "Review out-of-stock bestsellers",
                "Optimize inventory levels"
            ]
        }
        
        return {
            "period": {"start": start_date.date(), "end": end_date.date(), "days": days},
            "top_products": {
                "by_quantity": top_by_quantity,
                "by_revenue": top_by_revenue,
                "by_frequency": top_by_frequency
            },
            "category_performance": sorted(category_list, key=lambda x: x["revenue"], reverse=True),
            "inventory_insights": inventory_insights,
            "sales_recommendations": sales_recommendations,
            "summary": {
                "total_products_sold": len(product_list),
                "total_quantity_sold": sum(p["quantity_sold"] for p in product_list),
                "total_revenue": sum(p["revenue"] for p in product_list),
                "average_items_per_order": sum(p["quantity_sold"] for p in product_list) / len(set().union(*[list(data["orders"]) for data in product_performance.values()])) if product_performance else 0
            }
        }


    @staticmethod
    async def get_live_metrics() -> Dict[str, Any]:
        """Get real-time sales metrics for live dashboard"""
        cache_key = "sales:live:metrics"
        cached = redis_client.get(cache_key)
        if cached:
            return cached
        
        today = date.today()
        start_of_day = datetime.combine(today, datetime.min.time())
        current_hour = datetime.utcnow().hour
        
        # Get today's orders
        orders_result = supabase.table("orders").select("*").gte("created_at", start_of_day.isoformat()).execute()
        orders = orders_result.data
        
        # Current hour metrics
        current_hour_start = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        last_hour_start = current_hour_start - timedelta(hours=1)  # ADD THIS LINE
        
        current_hour_orders = [
            o for o in orders 
            if o.get("created_at") and o["created_at"] >= current_hour_start.isoformat()
        ]

        last_hour_orders = [
            o for o in orders 
            if o.get("created_at") and last_hour_start.isoformat() <= o["created_at"] < current_hour_start.isoformat()
        ]
        
        # Calculate velocity
        current_revenue = sum(float(o["total"]) for o in current_hour_orders if o["status"] != "cancelled")
        last_hour_revenue = sum(float(o["total"]) for o in last_hour_orders if o["status"] != "cancelled")
        
        # Active orders (pending/preparing)
        active_orders = [o for o in orders if o["status"] in ["pending", "preparing"]]
        
        live_data = {
            "current_time": datetime.utcnow().isoformat(),
            "today_summary": {
                "total_orders": len(orders),
                "total_revenue": sum(float(o["total"]) for o in orders if o["status"] != "cancelled"),
                "active_orders": len(active_orders)
            },
            "current_hour": {
                "orders": len(current_hour_orders),
                "revenue": round(current_revenue, 2),
                "vs_last_hour": round(((current_revenue - last_hour_revenue) / last_hour_revenue * 100) if last_hour_revenue > 0 else 0, 2)
            },
            "queue_status": {
                "pending_orders": len([o for o in active_orders if o["status"] == "pending"]),
                "preparing_orders": len([o for o in active_orders if o["status"] == "preparing"]),
                "average_wait_time": "5-10 min"  # Could calculate based on historical data
            }
        }
        
        # Cache for 15 seconds
        redis_client.set(cache_key, live_data, 15)
        
        return live_data
    
    @staticmethod
    async def generate_financial_report(start_date: date, end_date: date) -> Dict[str, Any]:
        """Generate comprehensive financial report"""
        # Get orders in date range
        orders_result = supabase.table("orders").select("*, order_items(*)").gte("created_at", start_date.isoformat()).lte("created_at", f"{end_date.isoformat()}T23:59:59").execute()
        
        orders = orders_result.data
        completed_orders = [o for o in orders if o["status"] == "completed"]
        cancelled_orders = [o for o in orders if o["status"] == "cancelled"]
        
        # Revenue calculations
        gross_revenue = sum(float(o["total"]) for o in completed_orders)
        tax_collected = sum(float(o["tax"]) for o in completed_orders)
        net_revenue = gross_revenue - tax_collected
        
        # Cancelled revenue (potential loss)
        cancelled_revenue = sum(float(o["total"]) for o in cancelled_orders)
        
        # Payment method breakdown with proper tracking
        payment_breakdown = defaultdict(float)
        
        for order in completed_orders:
            order_total = float(order["total"])
            
            if order["order_type"] == "offline":
                # Use actual payment method from order
                payment_method = order.get("payment_method", "cash")  # Default to cash for legacy data
                payment_breakdown[payment_method] += order_total
            else:
                # Online orders
                payment_breakdown["online"] += order_total
        
        # Convert to regular dict with proper formatting
        payment_methods = {k: round(v, 2) for k, v in payment_breakdown.items()}
        
        # Daily breakdown
        daily_breakdown = defaultdict(lambda: {
            "orders": 0, 
            "revenue": 0, 
            "tax": 0,
            "payment_methods": defaultdict(float)
        })
        
        for order in completed_orders:
            order_date = order["created_at"][:10]
            order_total = float(order["total"])
            order_tax = float(order["tax"])
            
            daily_breakdown[order_date]["orders"] += 1
            daily_breakdown[order_date]["revenue"] += order_total
            daily_breakdown[order_date]["tax"] += order_tax
            
            # Track payment methods per day
            if order["order_type"] == "offline":
                payment_method = order.get("payment_method", "cash")
                daily_breakdown[order_date]["payment_methods"][payment_method] += order_total
            else:
                daily_breakdown[order_date]["payment_methods"]["online"] += order_total
        
        # Convert daily breakdown to list format
        daily_data = []
        for date_str, data in sorted(daily_breakdown.items()):
            daily_data.append({
                "date": date_str,
                "orders": data["orders"],
                "revenue": round(data["revenue"], 2),
                "tax": round(data["tax"], 2),
                "payment_methods": {k: round(v, 2) for k, v in data["payment_methods"].items()}
            })
        
        # Order type breakdown with payment insights
        offline_orders = [o for o in completed_orders if o["order_type"] == "offline"]
        online_orders = [o for o in completed_orders if o["order_type"] == "online"]
        
        # Payment method statistics for offline orders
        offline_payment_stats = defaultdict(int)
        for order in offline_orders:
            payment_method = order.get("payment_method", "cash")
            offline_payment_stats[payment_method] += 1
        
        return {
            "period": {"start": start_date, "end": end_date},
            "revenue_summary": {
                "gross_revenue": round(gross_revenue, 2),
                "tax_collected": round(tax_collected, 2),
                "net_revenue": round(net_revenue, 2),
                "cancelled_revenue": round(cancelled_revenue, 2),
                "total_orders": len(completed_orders),
                "average_order_value": round(gross_revenue / len(completed_orders), 2) if completed_orders else 0
            },
            "payment_methods": {
                "breakdown": payment_methods,
                "offline_order_stats": {
                    "total_offline_orders": len(offline_orders),
                    "cash_orders": offline_payment_stats.get("cash", 0),
                    "card_orders": offline_payment_stats.get("card", 0),
                    "transfer_orders": offline_payment_stats.get("transfer", 0),
                    "cash_percentage": round((offline_payment_stats.get("cash", 0) / len(offline_orders) * 100), 2) if offline_orders else 0,
                    "card_percentage": round((offline_payment_stats.get("card", 0) / len(offline_orders) * 100), 2) if offline_orders else 0,
                    "transfer_percentage": round((offline_payment_stats.get("transfer", 0) / len(offline_orders) * 100), 2) if offline_orders else 0
                }
            },
            "daily_breakdown": daily_data,
            "order_type_summary": {
                "online_orders": len(online_orders),
                "offline_orders": len(offline_orders),
                "online_revenue": round(sum(float(o["total"]) for o in online_orders), 2),
                "offline_revenue": round(sum(float(o["total"]) for o in offline_orders), 2),
                "online_percentage": round((len(online_orders) / len(completed_orders) * 100), 2) if completed_orders else 0,
                "offline_percentage": round((len(offline_orders) / len(completed_orders) * 100), 2) if completed_orders else 0
            },
            "order_status_summary": {
                "completed": len(completed_orders),
                "cancelled": len(cancelled_orders),
                "completion_rate": round(len(completed_orders) / len(orders) * 100, 2) if orders else 0
            }
        }
    

    @staticmethod
    async def get_individual_staff_analytics(staff_id: str, days: int = 30) -> Dict[str, Any]:
        """Get individual staff performance analytics"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Orders created by this staff
        orders = supabase.table("orders").select("*, order_items(*)").eq("created_by", staff_id).gte("created_at", start_date.isoformat()).execute()
        completed_orders = [o for o in orders.data if o["status"] == "completed"]
        
        # Activity tracking
        activities = supabase.table("activity_logs").select("*").eq("user_id", staff_id).gte("created_at", start_date.isoformat()).execute()
        
        # Calculate metrics
        total_revenue = sum(float(o["total"]) for o in completed_orders)
        total_orders = len(orders.data)
        
        # Active time calculation (rough estimate based on activity gaps)
        activity_times = [datetime.fromisoformat(a["created_at"]) for a in activities.data]
        activity_times.sort()
        
        active_minutes = 0
        for i in range(1, len(activity_times)):
            gap = (activity_times[i] - activity_times[i-1]).total_seconds() / 60
            if gap <= 30:  # Activities within 30 min considered active session
                active_minutes += gap
        
        # Product sales breakdown
        product_sales = {}
        for order in completed_orders:
            for item in order["order_items"]:
                product_name = item["product_name"]
                if product_name not in product_sales:
                    product_sales[product_name] = {"quantity": 0, "revenue": 0}
                product_sales[product_name]["quantity"] += item["quantity"]
                product_sales[product_name]["revenue"] += float(item["total_price"])
        
        return {
            "staff_id": staff_id,
            "period": {"start": start_date.date(), "end": end_date.date(), "days": days},
            "performance": {
                "total_revenue": round(total_revenue, 2),
                "total_orders": total_orders,
                "completed_orders": len(completed_orders),
                "average_order_value": round(total_revenue / len(completed_orders), 2) if completed_orders else 0,
                "daily_average_revenue": round(total_revenue / days, 2),
                "daily_average_orders": round(total_orders / days, 2)
            },
            "activity": {
                "total_actions": len(activities.data),
                "estimated_active_hours": round(active_minutes / 60, 2),
                "actions_per_hour": round(len(activities.data) / (active_minutes / 60), 2) if active_minutes > 0 else 0
            },
            "top_products_sold": sorted(
                [{"product": k, **v} for k, v in product_sales.items()],
                key=lambda x: x["revenue"],
                reverse=True
            )[:10]
        }
    

    # Add to sales_service.py

    @staticmethod
    async def deduct_stock_immediately(items: List[Dict[str, Any]], user_id: str):
        """Deduct stock immediately for offline orders with real-time updates"""
        
        for item in items:
            # Get current product
            product = supabase.table("products").select("*").eq("id", item["product_id"]).execute()
            
            if not product.data:
                continue
                
            product_data = product.data[0]
            current_units = product_data["units"]
            low_threshold = product_data["low_stock_threshold"]
            
            # Calculate new stock
            new_units = current_units - item["quantity"]

            if new_units < 0:
                raise ValueError(f"Insufficient stock for {product_data['name']}. Available: {current_units}, Requested: {item['quantity']}")
            
            # Determine new status
            if new_units == 0:
                new_status = "out_of_stock"
            elif new_units <= low_threshold:
                new_status = "low_stock"
            else:
                new_status = "in_stock"
            
            # Update product
            supabase.table("products").update({
                "units": new_units,
                "status": new_status,
                "updated_by": user_id,
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", item["product_id"]).execute()
            
            # Log stock entry
            # supabase.table("stock_entries").insert({
            #     "product_id": item["product_id"],
            #     "quantity": item["quantity"],
            #     "entry_type": "remove",
            #     "notes": f"Offline order sale",
            #     "entered_by": user_id
            # }).execute()
        
        # Invalidate inventory caches for real-time updates
        redis_client.delete_pattern("products:list:*")
        redis_client.delete_pattern("inventory:dashboard:*")
        redis_client.delete_pattern("sales:products:*")
        redis_client.delete("inventory:alerts:low_stock")

    @staticmethod
    async def restore_stock_immediately(items: List[Dict[str, Any]], user_id: str):
        """Restore stock immediately when order is recalled"""
        
        for item in items:
            product = supabase.table("products").select("*").eq("id", item["product_id"]).execute()
            
            if product.data:
                current_units = product.data[0]["units"]
                low_threshold = product.data[0]["low_stock_threshold"]
                new_units = current_units + item["quantity"]
                
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
                    "updated_by": user_id,
                    "updated_at": datetime.utcnow().isoformat()
                }).eq("id", item["product_id"]).execute()
                
                # Log stock restoration
                supabase.table("stock_entries").insert({
                    "product_id": item["product_id"],
                    "quantity": item["quantity"],
                    "entry_type": "add",
                    "notes": f"Order recall restoration",
                    "entered_by": user_id
                }).execute()
        
        # Clear caches for real-time updates
        redis_client.delete_pattern("products:list:*")
        redis_client.delete_pattern("inventory:dashboard:*")
        redis_client.delete_pattern("sales:products:*")
        redis_client.delete("inventory:alerts:low_stock")

    @staticmethod
    def generate_batch_id() -> str:
        """Generate unique batch ID for order grouping"""
        return f"BATCH-{datetime.now().strftime('%Y%m%d%H%M%S')}-{str(uuid.uuid4())[:8]}"
    
    @staticmethod
    def get_next_display_number():
        today = date.today().isoformat()
        key = f"display_counter:{today}"
        current = redis_client.get(key) or 0
        next_num = (int(current) % 50) + 1
        redis_client.set(key, next_num, 86400)
        return next_num
    

    

    @staticmethod
    async def validate_sales_cart_items(items: List[Dict]) -> List[Dict]:
        processed_items = []
        
        for item in items:
            product = supabase.table("products").select("*").eq("id", item["product_id"]).execute()
            
            if not product.data:
                raise ValueError(f"Product {item['product_id']} not found")
            
            product_data = product.data[0]
            
            if not product_data["is_available"] or product_data["status"] == "out_of_stock":
                raise ValueError(f"{product_data['name']} is not available")
            
            # NEW: Support options array
            options = item.get("options", [])
            
            if product_data.get("has_options") and not options:
                raise ValueError(f"{product_data['name']} requires option selection")
            
            # Calculate total quantity from options or use item quantity
            if options:
                total_quantity = sum(opt["quantity"] for opt in options)
            else:
                total_quantity = item.get("quantity", 1)
            
            if product_data["units"] < total_quantity:
                raise ValueError(f"Insufficient stock for {product_data['name']}")
            
            # Validate options
            if options:
                for opt in options:
                    option = supabase.table("product_options").select("*").eq("id", opt["option_id"]).eq("product_id", item["product_id"]).execute()
                    if not option.data:
                        raise ValueError(f"Invalid option for {product_data['name']}")
            
            processed_items.append({
                "product_id": item["product_id"],
                "product_name": product_data["name"],
                "options": options,
                "quantity": total_quantity,
                "unit_price": Decimal(str(product_data["price"])),
                "tax_per_unit": Decimal(str(product_data.get("tax_per_unit", 0))),
                "total_price": Decimal(str(product_data["price"])) * total_quantity,
                "preparation_time_minutes": product_data.get("preparation_time_minutes", 15),
                "notes": item.get("notes"),
                "is_extra": False
            })
            
            # Handle extras
            if "extras" in item and item["extras"]:
                for extra in item["extras"]:
                    extra_product = supabase.table("products").select("*").eq("id", extra["id"]).execute()
                    if not extra_product.data:
                        continue
                    
                    extra_data = extra_product.data[0]
                    extra_price = Decimal(str(extra_data["price"]))
                    
                    processed_items.append({
                        "product_id": extra["id"],
                        "product_name": extra_data["name"],
                        "options": [],
                        "quantity": extra["quantity"],
                        "unit_price": extra_price,
                        "tax_per_unit": Decimal(str(extra_data.get("tax_per_unit", 0))),
                        "total_price": extra_price * extra["quantity"],
                        "preparation_time_minutes": extra_data.get("preparation_time_minutes", 15),
                        "notes": extra.get("notes"),
                        "is_extra": True
                    })
        
        return processed_items