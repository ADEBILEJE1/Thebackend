from typing import List, Dict, Optional, Any
from datetime import datetime, date, timedelta
from decimal import Decimal
from collections import defaultdict
from ..database import supabase, supabase_admin
from ..services.redis import redis_client
from ..core.cache import CacheKeys
from ..core.session import session_manager
from ..models.user import UserRole
from ..models.order import OrderStatus, OrderType
from ..models.inventory import StockStatus
from .sales_service import SalesService
from .inventory_service import InventoryService



class AdminService:
    """Service class for super admin dashboard operations - includes all manager functionality"""
    
    @staticmethod
    async def get_admin_dashboard_overview(user_role: str) -> Dict[str, Any]:
        """Get comprehensive admin dashboard overview"""
        cache_key = f"admin:dashboard:overview:{user_role}"
        cached = redis_client.get(cache_key)
        if cached:
            return cached
        
        today = date.today()
        start_of_day = datetime.combine(today, datetime.min.time())
        
        # System health metrics
        system_health = await AdminService.get_system_health()
        
        # Business metrics (inherited from manager/sales)
        sales_overview = await SalesService.get_sales_dashboard_overview(user_role)
        inventory_overview = await InventoryService.get_dashboard_overview()
        
        # Get packaging analytics for today
        packaging_analytics = await InventoryService.get_packaging_analytics("overall")


        refund_analytics = await AdminService.get_refund_analytics("overall")
        
        # User activity metrics
        active_sessions = session_manager.get_active_sessions()
        
        # Today's system activity
        today_activities = supabase.table("activity_logs").select("*").gte("created_at", start_of_day.isoformat()).execute()
        
        # Critical alerts
        critical_alerts = []
        
        # Low stock alerts
        low_stock_items = supabase.table("products").select("name, units").eq("status", "low_stock").execute()
        if low_stock_items.data:
            critical_alerts.append({
                "type": "inventory",
                "severity": "warning",
                "message": f"{len(low_stock_items.data)} products are low on stock",
                "count": len(low_stock_items.data)
            })
        
        # Out of stock alerts
        out_of_stock = supabase.table("products").select("name").eq("status", "out_of_stock").execute()
        if out_of_stock.data:
            critical_alerts.append({
                "type": "inventory",
                "severity": "critical",
                "message": f"{len(out_of_stock.data)} products are out of stock",
                "count": len(out_of_stock.data)
            })
        
        # Failed order alerts (pending too long)
        old_pending = supabase.table("orders").select("order_number").eq("status", "pending").lt("created_at", (datetime.utcnow() - timedelta(hours=1)).isoformat()).execute()
        if old_pending.data:
            critical_alerts.append({
                "type": "orders",
                "severity": "warning", 
                "message": f"{len(old_pending.data)} orders pending for over 1 hour",
                "count": len(old_pending.data)
            })
        
        # Inactive staff alert
        week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        inactive_staff = supabase.table("profiles").select("email, role").eq("is_active", True).lt("last_login", week_ago).execute()
        if inactive_staff.data:
            critical_alerts.append({
                "type": "staff",
                "severity": "info",
                "message": f"{len(inactive_staff.data)} staff haven't logged in for 7+ days",
                "count": len(inactive_staff.data)
            })
        
        dashboard_data = {
            "system_overview": {
                "system_health": system_health["status"],
                "active_sessions": active_sessions,
                "redis_status": system_health["services"]["redis"],
                "database_status": system_health["services"]["database"],
                "total_activities_today": len(today_activities.data)
            },
            "business_metrics": {
                "todays_revenue": sales_overview["summary"]["total_revenue"],
                "todays_orders": sales_overview["summary"]["total_orders"],
                "completion_rate": sales_overview["order_breakdown"]["completion_rate"],
                "inventory_value": inventory_overview["summary"]["total_inventory_value"],
                "products_in_stock": inventory_overview["summary"]["stock_status"]["in_stock"]
            },
            "packaging_analytics": packaging_analytics,
            "refund_analytics": refund_analytics,
            "critical_alerts": critical_alerts,
            "quick_stats": {
                "total_users": await AdminService.get_total_users_count(),
                "active_staff_today": len([a for a in today_activities.data if a["user_role"] != UserRole.SUPER_ADMIN]),
                "system_uptime": system_health.get("uptime", "Unknown"),
                "cache_hit_rate": await AdminService.get_cache_metrics()
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Cache for 1 minute
        redis_client.set(cache_key, dashboard_data, 60)
        
        return dashboard_data
    
    @staticmethod
    async def get_system_health() -> Dict[str, Any]:
        """Get comprehensive system health metrics"""
        health_data = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "services": {
                "database": "connected",
                "redis": "disconnected"
            },
            "performance": {},
            "errors": []
        }
        
        # Check Redis connection and get stats
        try:
            redis_client.client.ping()
            health_data["services"]["redis"] = "connected"
            
            # Get Redis performance metrics
            redis_info = redis_client.client.info()
            health_data["performance"]["redis"] = {
                "connected_clients": redis_info.get("connected_clients", 0),
                "used_memory_human": redis_info.get("used_memory_human", "0"),
                "total_commands": redis_info.get("total_commands_processed", 0),
                "cache_hits": redis_info.get("keyspace_hits", 0),
                "cache_misses": redis_info.get("keyspace_misses", 0),
                "hit_rate": round(
                    (redis_info.get("keyspace_hits", 0) / 
                     (redis_info.get("keyspace_hits", 0) + redis_info.get("keyspace_misses", 1)) * 100), 2
                )
            }
        except Exception as e:
            health_data["services"]["redis"] = "error"
            health_data["errors"].append(f"Redis connection failed: {str(e)}")
            health_data["status"] = "degraded"
        
        # Check database connection
        try:
            test_query = supabase.table("profiles").select("id").limit(1).execute()
            health_data["services"]["database"] = "connected"
        except Exception as e:
            health_data["services"]["database"] = "error"
            health_data["errors"].append(f"Database connection failed: {str(e)}")
            health_data["status"] = "critical"
        
        # Get queue health
        try:
            pending_orders = redis_client.llen("orders:queue:pending") or 0
            kitchen_queue = redis_client.llen("orders:queue:kitchen") or 0
            
            health_data["performance"]["queues"] = {
                "pending_orders": pending_orders,
                "kitchen_queue": kitchen_queue,
                "queue_health": "healthy" if pending_orders < 50 else "warning"
            }
        except:
            health_data["performance"]["queues"] = {"status": "error"}
        
        return health_data
    

    @staticmethod
    async def get_revenue_analytics(period: str, date_from: Optional[date] = None, date_to: Optional[date] = None) -> Dict[str, Any]:
        """Get comprehensive revenue analytics with all breakdowns"""
        
        # Set date range based on period if not provided
        if not date_from or not date_to:
            end_date = date.today()
            if period == "daily":
                start_date = end_date
            elif period == "weekly":
                start_date = end_date - timedelta(days=7)
            elif period == "monthly":
                start_date = end_date - timedelta(days=30)
            elif period == "quarterly":
                start_date = end_date - timedelta(days=90)
            else:  # yearly
                start_date = end_date - timedelta(days=365)
        else:
            start_date = date_from
            end_date = date_to
        
        # Get orders with items and categories
        orders = supabase_admin.table("orders").select("*").gte("created_at", start_date.isoformat()).lte("created_at", f"{end_date.isoformat()}T23:59:59").neq("status", "cancelled").execute()

        # Fetch order_items separately
        for order in orders.data:
            items = supabase_admin.table("order_items").select("*, products(categories(name))").eq("order_id", order["id"]).execute()
            order["order_items"] = items.data
        
        # Revenue calculations with separate components
        product_revenue_online = Decimal('0')
        product_revenue_offline = Decimal('0')
        total_delivery_fees = Decimal('0')
        total_taxes = Decimal('0')
        
        # Calculate component revenues
        for order in orders.data:
            subtotal = Decimal(str(order.get("subtotal", 0)))
            tax = Decimal(str(order.get("tax", 0)))
            delivery_fee = Decimal(str(order.get("delivery_fee", 0)))
            
            # Add to tax total
            total_taxes += tax
            
            # Add delivery fees (only for online orders typically)
            total_delivery_fees += delivery_fee
            
            # Add product revenue by channel
            if order["order_type"] == "online":
                product_revenue_online += subtotal
            else:
                product_revenue_offline += subtotal
        
        # Calculate totals
        total_product_revenue = product_revenue_online + product_revenue_offline
        gross_revenue = total_product_revenue + total_taxes + total_delivery_fees
        
        # Revenue by categories (using subtotal amounts)
        category_revenue = defaultdict(Decimal)
        for order in orders.data:
            for item in order["order_items"]:
                if item["products"] and item["products"]["categories"]:
                    category_name = item["products"]["categories"]["name"]
                    category_revenue[category_name] += Decimal(str(item["total_price"]))
        
        return {
            "period": {"start": start_date, "end": end_date, "type": period},
            "revenue_breakdown": {
                "product_revenue": {
                    "online": float(product_revenue_online),
                    "offline": float(product_revenue_offline),
                    "total": float(total_product_revenue)
                },
                "delivery_fees": float(total_delivery_fees),
                "taxes_collected": float(total_taxes),
                "gross_revenue": float(gross_revenue)
            },
            "channel_breakdown": {
                "online_revenue": float(product_revenue_online + (total_delivery_fees if product_revenue_online > 0 else Decimal('0'))),
                "offline_revenue": float(product_revenue_offline),
                "total_revenue": float(gross_revenue)
            },
            "category_breakdown": [
                {"category": k, "revenue": float(v)} 
                for k, v in sorted(category_revenue.items(), key=lambda x: x[1], reverse=True)
            ],
            "revenue_composition": {
                "product_percentage": float((total_product_revenue / gross_revenue * 100)) if gross_revenue > 0 else 0,
                "delivery_percentage": float((total_delivery_fees / gross_revenue * 100)) if gross_revenue > 0 else 0,
                "tax_percentage": float((total_taxes / gross_revenue * 100)) if gross_revenue > 0 else 0
            }
        }



    @staticmethod
    async def get_cost_analytics(period: str, date_from: Optional[date] = None, date_to: Optional[date] = None) -> Dict[str, Any]:
        """Get comprehensive cost analytics including staff salaries, expenditures, and raw materials"""
        
        # Set date range
        if not date_from or not date_to:
            end_date = date.today()
            if period == "daily":
                start_date = end_date
            elif period == "weekly":
                start_date = end_date - timedelta(days=7)
            elif period == "monthly":
                start_date = end_date - timedelta(days=30)
            elif period == "quarterly":
                start_date = end_date - timedelta(days=90)
            else:  # yearly
                start_date = end_date - timedelta(days=365)
        else:
            start_date = date_from
            end_date = date_to
        
        # Get packaging analytics (existing)
        packaging_data = await InventoryService.get_packaging_analytics(period, start_date, end_date)
        
        # Get refunds in period (existing)
        refunds = supabase_admin.table("refunds").select("*").gte("created_at", start_date.isoformat()).lte("created_at", f"{end_date.isoformat()}T23:59:59").execute()
        
        total_refunds = len(refunds.data)
        total_refund_amount = sum(Decimal(str(r["refund_amount"])) for r in refunds.data)
        
        # Raw Material Costs (NEW)
        raw_material_costs = await AdminService._get_raw_material_costs(start_date, end_date)
        
        # Staff Salary Analytics (existing)
        salary_analytics = await AdminService._get_salary_analytics(start_date, end_date, period)
        
        # Expenditure Analytics (existing)
        expenditure_analytics = await AdminService._get_expenditure_analytics(start_date, end_date, period)
        
        # Calculate total costs
        packaging_cost = Decimal(str(packaging_data["cost_breakdown"]["total_packaging_cost"]))
        raw_material_cost = Decimal(str(raw_material_costs["total_raw_material_cost"]))
        total_salary_cost = Decimal(str(salary_analytics["total_salary_cost"]))
        total_expenditure_cost = Decimal(str(expenditure_analytics["total_expenditure_cost"]))
        total_costs = packaging_cost + total_refund_amount + raw_material_cost + total_salary_cost + total_expenditure_cost
        
        return {
            "period": {"start": start_date, "end": end_date, "type": period},
            "packaging_costs": packaging_data,
            "raw_material_costs": raw_material_costs,
            "refund_costs": {
                "total_refunds": total_refunds,
                "total_refund_amount": float(total_refund_amount),
                "average_refund": float(total_refund_amount / total_refunds) if total_refunds > 0 else 0
            },
            "salary_costs": salary_analytics,
            "expenditure_costs": expenditure_analytics,
            "cost_summary": {
                "total_packaging_cost": float(packaging_cost),
                "total_raw_material_cost": float(raw_material_cost),
                "total_refund_cost": float(total_refund_amount),
                "total_salary_cost": float(total_salary_cost),
                "total_expenditure_cost": float(total_expenditure_cost),
                "total_operational_costs": float(total_costs),
                "cost_breakdown_percentage": {
                    "packaging": round(float(packaging_cost / total_costs * 100), 2) if total_costs > 0 else 0,
                    "raw_materials": round(float(raw_material_cost / total_costs * 100), 2) if total_costs > 0 else 0,
                    "refunds": round(float(total_refund_amount / total_costs * 100), 2) if total_costs > 0 else 0,
                    "salaries": round(float(total_salary_cost / total_costs * 100), 2) if total_costs > 0 else 0,
                    "expenditures": round(float(total_expenditure_cost / total_costs * 100), 2) if total_costs > 0 else 0
                }
            }
        }



    
    @staticmethod
    async def get_total_users_count() -> int:
        """Get total system users count"""
        try:
            result = supabase.table("profiles").select("id", count="exact").execute()
            return result.count
        except:
            return 0
    
    @staticmethod
    async def get_cache_metrics() -> float:
        """Get cache hit rate percentage"""
        try:
            redis_info = redis_client.client.info()
            hits = redis_info.get("keyspace_hits", 0)
            misses = redis_info.get("keyspace_misses", 0)
            if hits + misses > 0:
                return round((hits / (hits + misses)) * 100, 2)
        except:
            pass
        return 0.0
    
    @staticmethod
    async def get_comprehensive_analytics(days: int = 30) -> Dict[str, Any]:
        """Get comprehensive business analytics for admin review"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Get all business data
        sales_analytics = await SalesService.get_revenue_analytics(days=days)
        inventory_analytics = await InventoryService.get_inventory_valuation()
        staff_performance = await SalesService.get_staff_performance(days=days)
        customer_analytics = await SalesService.get_customer_analytics(days=days)
        
        # System usage analytics
        activity_result = supabase.table("activity_logs").select("*").gte("created_at", start_date.isoformat()).execute()
        activities = activity_result.data
        
        # User activity breakdown
        user_activity = defaultdict(int)
        action_breakdown = defaultdict(int)
        daily_activity = defaultdict(int)
        
        for activity in activities:
            user_activity[activity["user_role"]] += 1
            action_breakdown[activity["action"]] += 1
            day = activity["created_at"][:10]
            daily_activity[day] += 1
        
        return {
            "period": {"start": start_date.date(), "end": end_date.date(), "days": days},
            "business_performance": {
                "sales": {
                    "total_revenue": sales_analytics["summary"]["total_revenue"],
                    "growth_rate": sales_analytics["summary"]["growth_rate_percent"],
                    "orders_completed": sales_analytics["summary"]["completed_orders"]
                },
                "inventory": {
                    "total_value": inventory_analytics["total_inventory_value"],
                    "products_count": inventory_analytics["total_units"],
                    "top_category": inventory_analytics["category_breakdown"][0]["category"] if inventory_analytics["category_breakdown"] else None
                },
                "customers": {
                    "total_customers": customer_analytics["customer_summary"]["total_customers"],
                    "retention_rate": customer_analytics["customer_summary"]["retention_rate"],
                    "average_value": customer_analytics["customer_value"]["average_customer_value"]
                }
            },
            "operational_metrics": {
                "staff_performance": {
                    "total_staff": len(staff_performance["staff_performance"]),
                    "top_performer": staff_performance["team_summary"]["top_performer"],
                    "team_revenue": staff_performance["team_summary"]["total_team_revenue"]
                },
                "system_usage": {
                    "total_activities": len(activities),
                    "daily_average": len(activities) / days,
                    "most_active_role": max(user_activity, key=user_activity.get) if user_activity else None,
                    "top_action": max(action_breakdown, key=action_breakdown.get) if action_breakdown else None
                }
            },
            "trends": {
                "daily_activity": [{"date": k, "activities": v} for k, v in sorted(daily_activity.items())],
                "role_activity": dict(user_activity),
                "action_breakdown": dict(action_breakdown)
            }
        }
    
    @staticmethod
    async def get_security_overview(days: int = 7) -> Dict[str, Any]:
        """Get security and access control overview"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Get security-related activities
        security_activities = supabase.table("activity_logs").select("*").gte("created_at", start_date.isoformat()).in_("action", ["login", "logout", "failed_login", "permission_denied", "create", "delete"]).execute()
        
        activities = security_activities.data
        
        # Analyze security events
        failed_logins = [a for a in activities if a["action"] == "failed_login"]
        successful_logins = [a for a in activities if a["action"] == "login"]
        permission_denials = [a for a in activities if a["action"] == "permission_denied"]
        user_creations = [a for a in activities if a["action"] == "create" and a["resource"] == "user"]
        user_deletions = [a for a in activities if a["action"] == "delete" and a["resource"] == "user"]
        
        # Suspicious activity detection
        suspicious_activities = []
        
        # Multiple failed logins
        failed_by_user = defaultdict(int)
        for fail in failed_logins:
            failed_by_user[fail.get("user_email", "unknown")] += 1
        
        for user, count in failed_by_user.items():
            if count > 5:
                suspicious_activities.append({
                    "type": "multiple_failed_logins",
                    "user": user,
                    "count": count,
                    "severity": "high" if count > 10 else "medium"
                })
        
        # Off-hours access
        off_hours_logins = [
            a for a in successful_logins 
            if datetime.fromisoformat(a["created_at"]).hour < 6 or datetime.fromisoformat(a["created_at"]).hour > 22
        ]
        
        if len(off_hours_logins) > 10:
            suspicious_activities.append({
                "type": "off_hours_access",
                "count": len(off_hours_logins),
                "severity": "low"
            })
        
        return {
            "period": {"start": start_date.date(), "end": end_date.date(), "days": days},
            "security_summary": {
                "successful_logins": len(successful_logins),
                "failed_logins": len(failed_logins),
                "permission_denials": len(permission_denials),
                "user_creations": len(user_creations),
                "user_deletions": len(user_deletions)
            },
            "suspicious_activities": suspicious_activities,
            "login_patterns": {
                "peak_login_hour": AdminService._get_peak_hour(successful_logins),
                "unique_users_logged_in": len(set(a.get("user_id") for a in successful_logins if a.get("user_id"))),
                "off_hours_logins": len(off_hours_logins)
            },
            "access_control": {
                "active_sessions": session_manager.get_active_sessions(),
                "permission_violations": len(permission_denials),
                "high_privilege_actions": len([a for a in activities if a.get("user_role") == UserRole.SUPER_ADMIN])
            }
        }
    
    @staticmethod
    def _get_peak_hour(login_activities: List[Dict]) -> int:
        """Helper to find peak login hour"""
        if not login_activities:
            return 0
        
        hour_counts = defaultdict(int)
        for activity in login_activities:
            hour = datetime.fromisoformat(activity["created_at"]).hour
            hour_counts[hour] += 1
        
        return max(hour_counts, key=hour_counts.get) if hour_counts else 0
    
    @staticmethod
    async def get_user_management_overview() -> Dict[str, Any]:
        """Get comprehensive user management data"""
        # Get all users with activity data
        users_result = supabase.table("profiles").select("*").execute()
        users = users_result.data
        
        # Get recent activity for each user
        week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        recent_activity = supabase.table("activity_logs").select("user_id, action, created_at").gte("created_at", week_ago).execute()
        
        activity_by_user = defaultdict(list)
        for activity in recent_activity.data:
            activity_by_user[activity["user_id"]].append(activity)
        
        # User statistics
        role_breakdown = defaultdict(int)
        active_users = 0
        inactive_users = 0
        
        user_details = []
        
        for user in users:
            role_breakdown[user["role"]] += 1
            
            user_activities = activity_by_user.get(user["id"], [])
            last_activity = max([datetime.fromisoformat(a["created_at"]) for a in user_activities]) if user_activities else None
            
            if user["is_active"]:
                active_users += 1
            else:
                inactive_users += 1
            
            user_details.append({
                "id": user["id"],
                "email": user["email"],
                "role": user["role"],
                "is_active": user["is_active"],
                "created_at": user["created_at"],
                "last_login": user.get("last_login"),
                "last_activity": last_activity.isoformat() if last_activity else None,
                "activity_count_7d": len(user_activities),
                "invited_by": user.get("invited_by")
            })
        
        # Sort by last activity (most recent first)
        user_details.sort(key=lambda x: x["last_activity"] or "1900-01-01", reverse=True)
        
        return {
            "summary": {
                "total_users": len(users),
                "active_users": active_users,
                "inactive_users": inactive_users,
                "role_breakdown": dict(role_breakdown)
            },
            "user_details": user_details,
            "activity_insights": {
                "most_active_users": sorted(
                    user_details, 
                    key=lambda x: x["activity_count_7d"], 
                    reverse=True
                )[:5],
                "inactive_users": [
                    u for u in user_details 
                    if not u["last_activity"] or 
                    datetime.fromisoformat(u["last_activity"]).replace(tzinfo=None) < datetime.utcnow() - timedelta(days=7)
                ]
            }
        }
    
    @staticmethod
    async def get_system_configuration() -> Dict[str, Any]:
        """Get system configuration and settings overview"""
        # This would include environment variables, feature flags, etc.
        # For now, returning basic system info
        
        return {
            "system_info": {
                "environment": "production",  # Could be read from config
                "version": "1.0.0",  # Could be read from package.json or version file
                "deployment_date": "2024-01-01",  # Could be read from deployment info
                "features_enabled": {
                    "inventory_management": True,
                    "sales_dashboard": True,
                    "order_management": True,
                    "user_invitations": True,
                    "real_time_updates": True,
                    "background_tasks": True
                }
            },
            "integrations": {
                "supabase": "connected",
                "redis": "connected",
                "sendgrid": "configured",  # Could check API key validity
                "celery": "running"  # Could check worker status
            },
            "limits": {
                "max_users": 1000,  # Could be configurable
                "max_products": 10000,
                "max_orders_per_day": 5000,
                "cache_ttl_seconds": 300,
                "session_timeout_minutes": 60
            }
        }
    

    @staticmethod
    async def get_refund_analytics(period: str, date_from: Optional[date] = None, date_to: Optional[date] = None) -> Dict[str, Any]:
        """Get refund analytics for specified period"""
        
        # Set date range
        if not date_from or not date_to:
            end_date = date.today()
            if period == "daily":
                start_date = end_date
            elif period == "weekly":
                start_date = end_date - timedelta(days=7)
            elif period == "monthly":
                start_date = end_date - timedelta(days=30)
            elif period == "quarterly":
                start_date = end_date - timedelta(days=90)
            else:  # yearly
                start_date = end_date - timedelta(days=365)
        else:
            start_date = date_from
            end_date = date_to
        
        # Get refunds in period
        refunds = supabase_admin.table("refunds").select("*").gte("created_at", start_date.isoformat()).lte("created_at", f"{end_date.isoformat()}T23:59:59").execute()
        
        total_refunds = len(refunds.data)
        total_refund_amount = sum(Decimal(str(r["refund_amount"])) for r in refunds.data)
        
        return {
            "period": {"start": start_date, "end": end_date, "type": period},
            "total_refunds": total_refunds,
            "total_refund_amount": float(total_refund_amount),
            "average_refund": float(total_refund_amount / total_refunds) if total_refunds > 0 else 0
        }
    

    @staticmethod
    async def _get_raw_material_costs(start_date: date, end_date: date) -> Dict[str, Any]:
        """Get raw material purchase costs for the period"""
        
        # Get purchase transactions (only ones with costs)
        transactions = supabase_admin.table("raw_material_transactions").select(
            "*, raw_materials(name, measurement_unit)"
        ).eq("transaction_type", "purchase").gte("created_at", start_date.isoformat()).lte("created_at", f"{end_date.isoformat()}T23:59:59").execute()
        
        total_cost = Decimal('0')
        material_costs = {}
        
        for transaction in transactions.data:
            cost = Decimal(str(transaction.get("cost", 0) or 0))
            total_cost += cost
            
            material_name = transaction["raw_materials"]["name"]
            if material_name not in material_costs:
                material_costs[material_name] = {
                    "total_cost": Decimal('0'),
                    "total_quantity": Decimal('0'),
                    "transactions": 0,
                    "unit": transaction["raw_materials"]["measurement_unit"]
                }
            
            material_costs[material_name]["total_cost"] += cost
            material_costs[material_name]["total_quantity"] += Decimal(str(transaction["quantity"]))
            material_costs[material_name]["transactions"] += 1
        
        # Convert to response format
        material_breakdown = []
        for material, data in material_costs.items():
            avg_cost_per_unit = data["total_cost"] / data["total_quantity"] if data["total_quantity"] > 0 else Decimal('0')
            material_breakdown.append({
                "material": material,
                "total_cost": float(data["total_cost"]),
                "total_quantity": float(data["total_quantity"]),
                "transactions": data["transactions"],
                "unit": data["unit"],
                "avg_cost_per_unit": float(avg_cost_per_unit)
            })
        
        return {
            "total_raw_material_cost": float(total_cost),
            "total_transactions": len(transactions.data),
            "material_breakdown": sorted(material_breakdown, key=lambda x: x["total_cost"], reverse=True),
            "average_transaction_cost": float(total_cost / len(transactions.data)) if transactions.data else 0
        }

    @staticmethod
    async def _get_salary_analytics(start_date: date, end_date: date, period: str) -> Dict[str, Any]:
        """Get staff salary analytics for the specified period"""
        
        # Get active staff salaries
        active_salaries = supabase_admin.table("staff_salaries").select("*").eq("is_active", True).execute()
        
        # Calculate salary costs based on period
        total_salary_cost = Decimal('0')
        staff_breakdown = []
        monthly_breakdown = {}
        
        for salary_entry in active_salaries.data:
            staff_name = salary_entry["staff_name"]
            staff_role = salary_entry["staff_role"]
            monthly_salary = Decimal(str(salary_entry["salary_amount"]))
            effective_date = datetime.fromisoformat(salary_entry["effective_date"]).date()
            
            # Skip if effective date is after our end date
            if effective_date > end_date:
                continue
            
            # Calculate applicable months in the period
            period_start = max(start_date, effective_date)
            period_end = end_date
            
            if period == "daily":
                # For daily, just check if the date falls within
                if start_date == end_date and period_start <= start_date <= period_end:
                    daily_salary = monthly_salary / 30  # Approximate daily rate
                    staff_cost = daily_salary
                else:
                    staff_cost = Decimal('0')
            elif period == "weekly":
                # Calculate weekly cost
                days_in_period = min(7, (period_end - period_start).days + 1)
                daily_salary = monthly_salary / 30
                staff_cost = daily_salary * days_in_period
            elif period == "monthly":
                # Single month or partial month
                if period_start.year == period_end.year and period_start.month == period_end.month:
                    # Same month
                    days_in_month = (period_end - period_start).days + 1
                    days_total_month = 30  # Approximate
                    staff_cost = monthly_salary * Decimal(str(days_in_month)) / Decimal(str(days_total_month))
                else:
                    # Full month calculation
                    staff_cost = monthly_salary
            elif period == "quarterly":
                # 3 months
                staff_cost = monthly_salary * Decimal('3')
            else:  # yearly
                # 12 months
                staff_cost = monthly_salary * Decimal('12')
            
            total_salary_cost += staff_cost
            
            staff_breakdown.append({
                "staff_name": staff_name,
                "staff_role": staff_role,
                "monthly_salary": float(monthly_salary),
                "period_cost": float(staff_cost),
                "effective_date": salary_entry["effective_date"],
                "is_system_staff": salary_entry["is_system_staff"]
            })
            
            # Monthly breakdown for detailed analysis
            current_date = period_start
            while current_date <= period_end:
                month_key = current_date.strftime("%Y-%m")
                if month_key not in monthly_breakdown:
                    monthly_breakdown[month_key] = {
                        "total_cost": Decimal('0'),
                        "staff_count": 0,
                        "staff_details": []
                    }
                
                # Check if staff was active this month
                month_start = current_date.replace(day=1)
                if effective_date <= current_date:
                    monthly_breakdown[month_key]["total_cost"] += monthly_salary
                    monthly_breakdown[month_key]["staff_count"] += 1
                    monthly_breakdown[month_key]["staff_details"].append({
                        "name": staff_name,
                        "role": staff_role,
                        "salary": float(monthly_salary)
                    })
                
                # Move to next month
                if current_date.month == 12:
                    current_date = current_date.replace(year=current_date.year + 1, month=1)
                else:
                    current_date = current_date.replace(month=current_date.month + 1)
                
                if current_date > period_end:
                    break
        
        # Get salary changes in the period
        salary_changes = supabase_admin.table("salary_history").select("*").gte("change_date", start_date.isoformat()).lte("change_date", f"{end_date.isoformat()}T23:59:59").execute()
        
        return {
            "total_salary_cost": float(total_salary_cost),
            "staff_breakdown": sorted(staff_breakdown, key=lambda x: x["period_cost"], reverse=True),
            "monthly_breakdown": [
                {
                    "month": month,
                    "total_cost": float(data["total_cost"]),
                    "staff_count": data["staff_count"],
                    "average_salary": float(data["total_cost"] / data["staff_count"]) if data["staff_count"] > 0 else 0,
                    "staff_details": data["staff_details"]
                }
                for month, data in sorted(monthly_breakdown.items())
            ],
            "salary_changes_in_period": [
                {
                    "staff_id": change["staff_id"],
                    "old_salary": change["old_salary"],
                    "new_salary": change["new_salary"],
                    "change_type": change["change_type"],
                    "change_reason": change["change_reason"],
                    "change_date": change["change_date"],
                    "changed_by": change["profiles"]["email"] if change.get("profiles") else None
                }
                for change in salary_changes.data
            ],
            "summary": {
                "total_active_staff": len(staff_breakdown),
                "system_staff_count": len([s for s in staff_breakdown if s["is_system_staff"]]),
                "manual_staff_count": len([s for s in staff_breakdown if not s["is_system_staff"]]),
                "highest_paid_staff": max(staff_breakdown, key=lambda x: x["period_cost"])["staff_name"] if staff_breakdown else None,
                "average_salary_cost": float(total_salary_cost / len(staff_breakdown)) if staff_breakdown else 0
            }
        }



    @staticmethod
    async def _get_expenditure_analytics(start_date: date, end_date: date, period: str) -> Dict[str, Any]:
        """Get expenditure analytics for the specified period"""
        
        # Get expenditures in the period
        expenditures = supabase_admin.table("expenditures").select(
            "*, expenditure_categories(name), profiles(email)"
        ).gte("expense_date", start_date.isoformat()).lte("expense_date", end_date.isoformat()).execute()
        
        total_expenditure_cost = Decimal('0')
        category_breakdown = defaultdict(lambda: {
            "total_amount": Decimal('0'),
            "count": 0,
            "entries": []
        })
        
        daily_breakdown = defaultdict(lambda: {
            "total_amount": Decimal('0'),
            "count": 0,
            "categories": defaultdict(Decimal)
        })
        
        monthly_breakdown = defaultdict(lambda: {
            "total_amount": Decimal('0'),
            "count": 0,
            "categories": defaultdict(Decimal)
        })
        
        for expenditure in expenditures.data:
            amount = Decimal(str(expenditure["amount"]))
            category_name = expenditure["expenditure_categories"]["name"]
            expense_date = expenditure["expense_date"]
            logged_by = expenditure["profiles"]["email"] if expenditure.get("profiles") else "Unknown"
            
            total_expenditure_cost += amount
            
            # Category breakdown
            category_breakdown[category_name]["total_amount"] += amount
            category_breakdown[category_name]["count"] += 1
            category_breakdown[category_name]["entries"].append({
                "amount": float(amount),
                "description": expenditure["description"],
                "expense_date": expense_date,
                "logged_by": logged_by,
                "notes": expenditure.get("notes")
            })
            
            # Daily breakdown
            daily_breakdown[expense_date]["total_amount"] += amount
            daily_breakdown[expense_date]["count"] += 1
            daily_breakdown[expense_date]["categories"][category_name] += amount
            
            # Monthly breakdown
            month_key = expense_date[:7]  # YYYY-MM format
            monthly_breakdown[month_key]["total_amount"] += amount
            monthly_breakdown[month_key]["count"] += 1
            monthly_breakdown[month_key]["categories"][category_name] += amount
        
        # Get top spending categories
        top_categories = sorted(
            [
                {
                    "category": cat,
                    "total_amount": float(data["total_amount"]),
                    "count": data["count"],
                    "average_amount": float(data["total_amount"] / data["count"]) if data["count"] > 0 else 0,
                    "percentage": float(data["total_amount"] / total_expenditure_cost * 100) if total_expenditure_cost > 0 else 0
                }
                for cat, data in category_breakdown.items()
            ],
            key=lambda x: x["total_amount"],
            reverse=True
        )
        
        return {
            "total_expenditure_cost": float(total_expenditure_cost),
            "category_breakdown": top_categories,
            "daily_breakdown": [
                {
                    "date": date,
                    "total_amount": float(data["total_amount"]),
                    "count": data["count"],
                    "categories": {k: float(v) for k, v in data["categories"].items()}
                }
                for date, data in sorted(daily_breakdown.items())
            ],
            "monthly_breakdown": [
                {
                    "month": month,
                    "total_amount": float(data["total_amount"]),
                    "count": data["count"],
                    "categories": {k: float(v) for k, v in data["categories"].items()}
                }
                for month, data in sorted(monthly_breakdown.items())
            ],
            "detailed_entries": [
                {
                    "category": cat,
                    "entries": data["entries"]
                }
                for cat, data in category_breakdown.items()
            ],
            "summary": {
                "total_entries": len(expenditures.data),
                "total_categories": len(category_breakdown),
                "highest_expense_category": top_categories[0]["category"] if top_categories else None,
                "average_expense_amount": float(total_expenditure_cost / len(expenditures.data)) if expenditures.data else 0,
                "period_daily_average": float(total_expenditure_cost / ((end_date - start_date).days + 1)) if total_expenditure_cost > 0 else 0
            }
        }

    @staticmethod
    async def get_payment_analytics(period: str, date_from: Optional[date] = None, date_to: Optional[date] = None) -> Dict[str, Any]:
        """Get comprehensive payment method analytics with time filters"""
        
        # Set date range
        if not date_from or not date_to:
            end_date = date.today()
            if period == "daily":
                start_date = end_date
            elif period == "weekly":
                start_date = end_date - timedelta(days=7)
            elif period == "monthly":
                start_date = end_date - timedelta(days=30)
            elif period == "quarterly":
                start_date = end_date - timedelta(days=90)
            else:  # yearly
                start_date = end_date - timedelta(days=365)
        else:
            start_date = date_from
            end_date = date_to
        
        # Get all paid orders in the period
        orders = supabase_admin.table("orders").select("*").gte("created_at", start_date.isoformat()).lte("created_at", f"{end_date.isoformat()}T23:59:59").in_("payment_status", ["paid"]).neq("status", "cancelled").execute()
        
        # Initialize payment tracking
        payment_breakdown = {
            "website": {"count": 0, "revenue": Decimal('0')},
            "cash": {"count": 0, "revenue": Decimal('0')},
            "card": {"count": 0, "revenue": Decimal('0')},
            "transfer": {"count": 0, "revenue": Decimal('0')}
        }
        
        daily_breakdown = defaultdict(lambda: {
            "website": {"count": 0, "revenue": Decimal('0')},
            "cash": {"count": 0, "revenue": Decimal('0')},
            "card": {"count": 0, "revenue": Decimal('0')},
            "transfer": {"count": 0, "revenue": Decimal('0')}
        })
        
        total_revenue = Decimal('0')
        total_orders = 0
        
        for order in orders.data:
            order_total = Decimal(str(order["total"]))
            order_date = order["created_at"][:10]
            total_revenue += order_total
            total_orders += 1
            
            # Determine payment method
            if order["order_type"] == "online":
                payment_method = "website"
            else:
                payment_method = order.get("payment_method", "cash")  # Default to cash for offline orders
            
            # Update totals
            payment_breakdown[payment_method]["count"] += 1
            payment_breakdown[payment_method]["revenue"] += order_total
            
            # Update daily breakdown
            daily_breakdown[order_date][payment_method]["count"] += 1
            daily_breakdown[order_date][payment_method]["revenue"] += order_total
        
        # Calculate percentages and convert to float
        payment_summary = []
        for method, data in payment_breakdown.items():
            percentage = (data["revenue"] / total_revenue * 100) if total_revenue > 0 else 0
            average_order = (data["revenue"] / data["count"]) if data["count"] > 0 else Decimal('0')
            
            payment_summary.append({
                "payment_method": method,
                "order_count": data["count"],
                "total_revenue": float(data["revenue"]),
                "percentage_of_revenue": round(float(percentage), 2),
                "percentage_of_orders": round((data["count"] / total_orders * 100), 2) if total_orders > 0 else 0,
                "average_order_value": float(average_order)
            })
        
        # Sort by revenue
        payment_summary.sort(key=lambda x: x["total_revenue"], reverse=True)
        
        # Convert daily breakdown to list format
        daily_data = []
        for date_str, methods in sorted(daily_breakdown.items()):
            day_data = {"date": date_str}
            for method, data in methods.items():
                day_data[f"{method}_count"] = data["count"]
                day_data[f"{method}_revenue"] = float(data["revenue"])
            daily_data.append(day_data)
        
        # Payment method trends
        offline_methods = ["cash", "card", "transfer"]
        total_offline_revenue = sum(payment_breakdown[method]["revenue"] for method in offline_methods)
        online_revenue = payment_breakdown["website"]["revenue"]
        
        return {
            "period": {"start": start_date, "end": end_date, "type": period},
            "payment_summary": payment_summary,
            "channel_analysis": {
                "online_revenue": float(online_revenue),
                "offline_revenue": float(total_offline_revenue),
                "online_percentage": float((online_revenue / total_revenue * 100)) if total_revenue > 0 else 0,
                "offline_percentage": float((total_offline_revenue / total_revenue * 100)) if total_revenue > 0 else 0,
                "digital_vs_cash": {
                    "digital_revenue": float(online_revenue + payment_breakdown["card"]["revenue"] + payment_breakdown["transfer"]["revenue"]),
                    "cash_revenue": float(payment_breakdown["cash"]["revenue"]),
                    "digital_percentage": float(((online_revenue + payment_breakdown["card"]["revenue"] + payment_breakdown["transfer"]["revenue"]) / total_revenue * 100)) if total_revenue > 0 else 0
                }
            },
            "daily_breakdown": daily_data,
            "insights": {
                "most_popular_method": payment_summary[0]["payment_method"] if payment_summary else None,
                "highest_average_order": max(payment_summary, key=lambda x: x["average_order_value"])["payment_method"] if payment_summary else None,
                "cash_dependency": float((payment_breakdown["cash"]["revenue"] / total_revenue * 100)) if total_revenue > 0 else 0,
                "total_orders": total_orders,
                "total_revenue": float(total_revenue)
            }
        }


    @staticmethod
    async def get_profit_analytics(period: str, date_from: Optional[date] = None, date_to: Optional[date] = None) -> Dict[str, Any]:
        """Get comprehensive profit analytics (Revenue - Costs)"""
        
        # Set date range (same logic as other methods)
        if not date_from or not date_to:
            end_date = date.today()
            if period == "daily":
                start_date = end_date
            elif period == "weekly":
                start_date = end_date - timedelta(days=7)
            elif period == "monthly":
                start_date = end_date - timedelta(days=30)
            elif period == "quarterly":
                start_date = end_date - timedelta(days=90)
            else:  # yearly
                start_date = end_date - timedelta(days=365)
        else:
            start_date = date_from
            end_date = date_to
        
        # Get revenue analytics
        revenue_data = await AdminService.get_revenue_analytics(period, start_date, end_date)
        
        # Get cost analytics
        cost_data = await AdminService.get_cost_analytics(period, start_date, end_date)
        
        # Extract totals
        total_revenue = Decimal(str(revenue_data["channel_breakdown"]["total_revenue"]))
        total_costs = Decimal(str(cost_data["cost_summary"]["total_operational_costs"]))
        
        # Calculate profit
        gross_profit = total_revenue - total_costs
        profit_margin = (gross_profit / total_revenue * 100) if total_revenue > 0 else 0
        
        # Daily profit breakdown
        daily_profits = {}
        
        # Get daily revenue breakdown
        daily_revenue = defaultdict(Decimal)
        orders = supabase_admin.table("orders").select("*").gte("created_at", start_date.isoformat()).lte("created_at", f"{end_date.isoformat()}T23:59:59").neq("status", "cancelled").execute()
        
        for order in orders.data:
            order_date = order["created_at"][:10]
            daily_revenue[order_date] += Decimal(str(order["total"]))
        
        # Get daily cost breakdown (simplified - distribute monthly costs daily)
        days_in_period = (end_date - start_date).days + 1
        daily_cost_estimate = total_costs / days_in_period if days_in_period > 0 else Decimal('0')
        
        # Calculate daily profits
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.isoformat()
            day_revenue = daily_revenue.get(date_str, Decimal('0'))
            day_cost = daily_cost_estimate  # Simplified daily cost allocation
            day_profit = day_revenue - day_cost
            
            daily_profits[date_str] = {
                "date": date_str,
                "revenue": float(day_revenue),
                "estimated_costs": float(day_cost),
                "profit": float(day_profit),
                "profit_margin": float((day_profit / day_revenue * 100)) if day_revenue > 0 else 0
            }
            
            current_date += timedelta(days=1)
        
        # Monthly profit breakdown
        monthly_profits = {}
        
        # Group daily data by month
        for date_str, day_data in daily_profits.items():
            month_key = date_str[:7]  # YYYY-MM
            if month_key not in monthly_profits:
                monthly_profits[month_key] = {
                    "month": month_key,
                    "revenue": 0,
                    "costs": 0,
                    "profit": 0,
                    "days_count": 0
                }
            
            monthly_profits[month_key]["revenue"] += day_data["revenue"]
            monthly_profits[month_key]["costs"] += day_data["estimated_costs"]
            monthly_profits[month_key]["profit"] += day_data["profit"]
            monthly_profits[month_key]["days_count"] += 1
        
        # Calculate monthly profit margins
        for month_data in monthly_profits.values():
            month_data["profit_margin"] = (month_data["profit"] / month_data["revenue"] * 100) if month_data["revenue"] > 0 else 0
            month_data["daily_average_profit"] = month_data["profit"] / month_data["days_count"] if month_data["days_count"] > 0 else 0
        
        # Profit trends and insights
        profit_trends = {
            "is_profitable": gross_profit > 0,
            "break_even_point": float(total_costs),  # Revenue needed to break even
            "revenue_vs_breakeven": float((total_revenue / total_costs * 100)) if total_costs > 0 else 0,
            "cost_efficiency": float((total_costs / total_revenue * 100)) if total_revenue > 0 else 0
        }
        
        # Cost impact analysis
        cost_impact = {
            "salary_impact_on_profit": float((cost_data["cost_summary"]["total_salary_cost"] / float(total_revenue) * 100)) if total_revenue > 0 else 0,
            "expenditure_impact_on_profit": float((cost_data["cost_summary"]["total_expenditure_cost"] / float(total_revenue) * 100)) if total_revenue > 0 else 0,
            "packaging_impact_on_profit": float((cost_data["cost_summary"]["total_packaging_cost"] / float(total_revenue) * 100)) if total_revenue > 0 else 0,
            "raw_material_impact_on_profit": float((cost_data["cost_summary"]["total_raw_material_cost"] / float(total_revenue) * 100)) if total_revenue > 0 else 0,
            "refund_impact_on_profit": float((cost_data["cost_summary"]["total_refund_cost"] / float(total_revenue) * 100)) if total_revenue > 0 else 0
        }
        
        # Recommendations based on profit analysis
        recommendations = []
        
        if profit_margin < 10:
            recommendations.append("Profit margin is low. Consider reducing costs or increasing prices.")
        
        if cost_impact["salary_impact_on_profit"] > 40:
            recommendations.append("Salary costs are high relative to revenue. Review staffing efficiency.")
        
        if cost_impact["expenditure_impact_on_profit"] > 20:
            recommendations.append("Expenditures are significant. Review and optimize spending categories.")
        
        if profit_trends["revenue_vs_breakeven"] < 120:
            recommendations.append("Revenue is close to break-even point. Focus on revenue growth.")
        
        if gross_profit < 0:
            recommendations.append("Business is operating at a loss. Immediate cost reduction or revenue increase needed.")
        
        return {
            "period": {"start": start_date, "end": end_date, "type": period},
            "profit_summary": {
                "total_revenue": float(total_revenue),
                "total_costs": float(total_costs),
                "gross_profit": float(gross_profit),
                "profit_margin_percent": float(profit_margin),
                "is_profitable": gross_profit > 0
            },
            "daily_breakdown": list(daily_profits.values()),
            "monthly_breakdown": list(monthly_profits.values()),
            "cost_impact_analysis": cost_impact,
            "profit_trends": profit_trends,
            "revenue_breakdown": revenue_data["channel_breakdown"],
            "cost_breakdown": cost_data["cost_summary"],
            "recommendations": recommendations,
            "key_metrics": {
                "revenue_per_day": float(total_revenue / days_in_period) if days_in_period > 0 else 0,
                "cost_per_day": float(total_costs / days_in_period) if days_in_period > 0 else 0,
                "profit_per_day": float(gross_profit / days_in_period) if days_in_period > 0 else 0,
                "break_even_revenue_needed": float(total_costs),
                "revenue_growth_needed_for_target_margin": float(total_costs / Decimal('0.8') - total_revenue) if total_revenue > 0 else 0  # Assuming 20% target margin
            }
        }
    

    @staticmethod
    async def get_raw_materials_analytics(period: str, date_from: Optional[date] = None, date_to: Optional[date] = None) -> Dict[str, Any]:
        """Get comprehensive raw materials analytics"""
        
        # Set date range
        if not date_from or not date_to:
            end_date = date.today()
            if period == "daily":
                start_date = end_date
            elif period == "weekly":
                start_date = end_date - timedelta(days=7)
            elif period == "monthly":
                start_date = end_date - timedelta(days=30)
            elif period == "quarterly":
                start_date = end_date - timedelta(days=90)
            else:  # yearly
                start_date = end_date - timedelta(days=365)
        else:
            start_date = date_from
            end_date = date_to
        
        # Get all raw materials with current status
        materials = supabase_admin.table("raw_materials").select("*, suppliers(name)").execute()
        
        # Calculate stock status
        total_materials = len(materials.data)
        in_stock = len([m for m in materials.data if m["current_quantity"] > 10])
        low_stock = len([m for m in materials.data if 0 < m["current_quantity"] <= 10])
        out_of_stock = len([m for m in materials.data if m["current_quantity"] <= 0])
        
        # Get transactions in period
        transactions = supabase_admin.table("raw_material_transactions").select(
            "*, raw_materials(name, measurement_unit)"
        ).gte("created_at", start_date.isoformat()).lte("created_at", f"{end_date.isoformat()}T23:59:59").execute()
        
        # Usage and purchase breakdown
        total_purchases = sum(t["quantity"] for t in transactions.data if t["transaction_type"] == "purchase")
        total_usage = sum(t["quantity"] for t in transactions.data if t["transaction_type"] == "usage")
        total_cost = sum(float(t.get("cost", 0)) for t in transactions.data if t["transaction_type"] == "purchase")
        
        # Material breakdown
        material_breakdown = []
        for material in materials.data:
            qty = material["current_quantity"]
            status = "out_of_stock" if qty <= 0 else ("low_stock" if qty <= 10 else "in_stock")
            
            material_breakdown.append({
                "id": material["id"],
                "name": material["name"],
                "current_quantity": qty,
                "measurement_unit": material["measurement_unit"],
                "status": status,
                "supplier": material["suppliers"]["name"] if material["suppliers"] else None
            })
        
        return {
            "period": {"start": start_date, "end": end_date, "type": period},
            "summary": {
                "total_materials": total_materials,
                "in_stock": in_stock,
                "low_stock": low_stock,
                "out_of_stock": out_of_stock,
                "total_purchases": total_purchases,
                "total_usage": total_usage,
                "total_cost": total_cost
            },
            "material_breakdown": material_breakdown,
            "alerts": {
                "critical_materials": [m for m in material_breakdown if m["status"] == "out_of_stock"],
                "low_stock_materials": [m for m in material_breakdown if m["status"] == "low_stock"]
            }
        }