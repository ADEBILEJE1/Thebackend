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
        
        # User activity metrics
        active_sessions = session_manager.get_active_sessions()
        
        # Today's system activity
        today_activities = supabase.table("activity_logs").select("*").gte("created_at", start_of_day.isoformat()).execute()
        
        # Critical alerts
        critical_alerts = []
        
        # Low stock alerts
        low_stock_items = supabase.table("products").select("name, units").eq("status", StockStatus.LOW_STOCK).execute()
        if low_stock_items.data:
            critical_alerts.append({
                "type": "inventory",
                "severity": "warning",
                "message": f"{len(low_stock_items.data)} products are low on stock",
                "count": len(low_stock_items.data)
            })
        
        # Out of stock alerts
        out_of_stock = supabase.table("products").select("name").eq("status", StockStatus.OUT_OF_STOCK).execute()
        if out_of_stock.data:
            critical_alerts.append({
                "type": "inventory",
                "severity": "critical",
                "message": f"{len(out_of_stock.data)} products are out of stock",
                "count": len(out_of_stock.data)
            })
        
        # Failed order alerts (pending too long)
        old_pending = supabase.table("orders").select("order_number").eq("status", OrderStatus.PENDING).lt("created_at", (datetime.utcnow() - timedelta(hours=1)).isoformat()).execute()
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
                    datetime.fromisoformat(u["last_activity"]) < datetime.utcnow() - timedelta(days=7)
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