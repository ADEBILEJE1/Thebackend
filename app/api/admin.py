from fastapi import APIRouter, HTTPException, status, Depends, Request, BackgroundTasks, Query
from typing import List, Optional
from decimal import Decimal
from datetime import datetime, date, timedelta
from pydantic import BaseModel, Field, validator, EmailStr
from .admin_service import AdminService
from ..models.user import UserRole
from collections import defaultdict
from ..core.permissions import (
    get_current_user,
    require_super_admin,
    require_manager_up
)
from ..core.activity_logger import log_activity
from ..core.rate_limiter import default_limiter
from ..services.redis import redis_client
from ..database import supabase, supabase_admin



class BulkUserAction(BaseModel):
    action: str = Field(pattern="^(activate|deactivate|delete)$")
    user_ids: List[str] = Field(min_items=1, max_items=50)
    reason: Optional[str] = None

class DataExportRequest(BaseModel):
    data_types: List[str] = Field(min_items=1)
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    
    @validator('data_types')
    def validate_data_types(cls, v):
        valid_types = ["users", "orders", "products", "activities", "inventory"]
        invalid = [t for t in v if t not in valid_types]
        if invalid:
            raise ValueError(f"Invalid data types: {invalid}")
        return v

class StaffSalaryCreate(BaseModel):
    staff_id: Optional[str] = None  # None for manual entries
    staff_name: str = Field(max_length=255)
    staff_role: Optional[str] = Field(None, max_length=100)
    salary_amount: Decimal = Field(gt=0)
    effective_date: date = Field(default_factory=date.today)
    is_system_staff: bool = False

class StaffSalaryUpdate(BaseModel):
    salary_amount: Optional[Decimal] = Field(None, gt=0)
    change_reason: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = None

class ExpenditureCategoryCreate(BaseModel):
    name: str = Field(max_length=255)
    description: Optional[str] = None

class ExpenditureCategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    is_active: Optional[bool] = None

class ExpenditureCreate(BaseModel):
    category_id: str
    amount: Decimal = Field(gt=0)
    description: str = Field(max_length=500)
    notes: Optional[str] = None
    receipt_url: Optional[str] = None
    expense_date: date = Field(default_factory=date.today)

class ExpenditureUpdate(BaseModel):
    amount: Optional[Decimal] = Field(None, gt=0)
    description: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = None
    receipt_url: Optional[str] = None
    expense_date: Optional[date] = None


router = APIRouter(prefix="/admin", tags=["Administration"])

# Main Admin Dashboard
@router.get("/dashboard")
async def get_admin_dashboard(
    request: Request,
    current_user: dict = Depends(require_manager_up)
):
    """Get comprehensive admin dashboard overview"""
    # Rate limiting
    await default_limiter.check_rate_limit(request, current_user["id"])
    
    dashboard_data = await AdminService.get_admin_dashboard_overview(current_user["role"])
    
    # Log activity
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "view", "admin_dashboard", None, None, request
    )
    
    return dashboard_data


@router.get("/analytics/revenue")
async def get_revenue_analytics(
    request: Request,
    period: str = Query("daily", pattern="^(daily|weekly|monthly|quarterly|yearly)$"),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    current_user: dict = Depends(require_manager_up)
):
    """Get comprehensive revenue analytics"""
    revenue_data = await AdminService.get_revenue_analytics(period, date_from, date_to)
    return revenue_data


@router.get("/analytics/costs")
async def get_cost_analytics(
    request: Request,
    period: str = Query("monthly", pattern="^(daily|weekly|monthly|quarterly|yearly)$"),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    current_user: dict = Depends(require_manager_up)
):
    """Get comprehensive cost analytics including packaging, refunds, and other expenses"""
    cost_data = await AdminService.get_cost_analytics(period, date_from, date_to)
    return cost_data



@router.get("/analytics/profit")
async def get_profit_analytics(
    request: Request,
    period: str = Query("monthly", pattern="^(daily|weekly|monthly|quarterly|yearly)$"),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    current_user: dict = Depends(require_manager_up)
):
    """Get comprehensive profit analytics (Revenue - Costs)"""
    profit_data = await AdminService.get_profit_analytics(period, date_from, date_to)
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "view", "profit_analytics", None, 
        {"period": period, "date_from": str(date_from), "date_to": str(date_to)}, 
        request
    )
    
    return profit_data



@router.get("/analytics/payments")
async def get_payment_analytics(
    request: Request,
    period: str = Query("monthly", pattern="^(daily|weekly|monthly|quarterly|yearly)$"),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    current_user: dict = Depends(require_manager_up)
):
    """Get comprehensive payment method analytics"""
    payment_data = await AdminService.get_payment_analytics(period, date_from, date_to)
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "view", "payment_analytics", None, 
        {"period": period, "date_from": str(date_from), "date_to": str(date_to)}, 
        request
    )
    
    return payment_data



# Comprehensive Business Analytics
@router.get("/analytics/comprehensive")
async def get_comprehensive_analytics(
    request: Request,
    days: int = 30,
    current_user: dict = Depends(require_manager_up)
):
    """Get comprehensive business analytics across all modules"""
    if days > 365:
        raise HTTPException(status_code=400, detail="Maximum 365 days allowed")
    
    analytics_data = await AdminService.get_comprehensive_analytics(days=days)
    
    # Log activity
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "view", "comprehensive_analytics", None, {"days": days}, request
    )
    
    return analytics_data

# Security Overview (Super Admin only)
@router.get("/security/overview")
async def get_security_overview(
    request: Request,
    days: int = 7,
    current_user: dict = Depends(require_super_admin)
):
    """Get security and access control overview"""
    if days > 90:
        raise HTTPException(status_code=400, detail="Maximum 90 days allowed")
    
    security_data = await AdminService.get_security_overview(days=days)
    
    # Log activity
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "view", "security_overview", None, {"days": days}, request
    )
    
    return security_data

# User Management Overview
@router.get("/users/overview")
async def get_user_management_overview(
    request: Request,
    current_user: dict = Depends(require_manager_up)
):
    """Get comprehensive user management data"""
    user_data = await AdminService.get_user_management_overview()
    
    # Filter sensitive data for managers (non-super admins)
    if current_user["role"] != UserRole.SUPER_ADMIN:
        # Remove super admin users from the view
        user_data["user_details"] = [
            u for u in user_data["user_details"] 
            if u["role"] != UserRole.SUPER_ADMIN
        ]
        user_data["summary"]["role_breakdown"].pop(UserRole.SUPER_ADMIN, None)
        user_data["summary"]["total_users"] = len(user_data["user_details"])
    
    return user_data

# System Configuration (Super Admin only)
@router.get("/system/configuration")
async def get_system_configuration(
    request: Request,
    current_user: dict = Depends(require_super_admin)
):
    """Get system configuration and settings"""
    config_data = await AdminService.get_system_configuration()
    
    # Log activity
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "view", "system_configuration", None, None, request
    )
    
    return config_data

# Real-time System Metrics
@router.get("/metrics/realtime")
async def get_realtime_metrics(
    request: Request,
    current_user: dict = Depends(require_manager_up)
):
    """Get real-time system metrics"""
    cache_key = f"admin:realtime:metrics:{current_user['role']}"
    cached = redis_client.get(cache_key)
    if cached:
        return cached
    
    # Get real-time data
    current_time = datetime.utcnow()
    hour_ago = current_time - timedelta(hours=1)
    
    # Recent orders
    recent_orders = supabase.table("orders").select("status, total, created_at").gte("created_at", hour_ago.isoformat()).execute()
    
    # Recent activities
    recent_activities = supabase.table("activity_logs").select("action, user_role, created_at").gte("created_at", hour_ago.isoformat()).execute()
    
    # Active sessions
    from ..core.session import session_manager
    active_sessions = session_manager.get_active_sessions()
    
    # Current queue status
    try:
        pending_queue = redis_client.llen("orders:queue:pending") or 0
        kitchen_queue = redis_client.llen("orders:queue:kitchen") or 0
    except:
        pending_queue = kitchen_queue = 0
    
    # Calculate metrics
    completed_orders = len([o for o in recent_orders.data if o["status"] == "completed"])
    total_revenue_hour = sum(float(o["total"]) for o in recent_orders.data if o["status"] not in ["cancelled", "pending"])
    
    realtime_data = {
        "timestamp": current_time.isoformat(),
        "current_activity": {
            "active_users": active_sessions,
            "orders_last_hour": len(recent_orders.data),
            "completed_orders_hour": completed_orders,
            "revenue_last_hour": round(total_revenue_hour, 2),
            "activities_last_hour": len(recent_activities.data)
        },
        "queue_status": {
            "pending_orders": pending_queue,
            "kitchen_queue": kitchen_queue,
            "queue_health": "healthy" if pending_queue < 20 else "busy"
        },
        "system_load": {
            "redis_connections": 0,  # Could get from Redis info
            "database_connections": 0,  # Could get from DB stats
            "response_time_avg": "< 50ms"  # Could track actual response times
        },
        "hourly_trend": [
            {
                "hour": (current_time - timedelta(hours=i)).hour,
                "orders": len([o for o in recent_orders.data if datetime.fromisoformat(o["created_at"]).hour == (current_time - timedelta(hours=i)).hour]),
                "activities": len([a for a in recent_activities.data if datetime.fromisoformat(a["created_at"]).hour == (current_time - timedelta(hours=i)).hour])
            }
            for i in range(4)  # Last 4 hours
        ]
    }
    
    # Cache for 30 seconds
    redis_client.set(cache_key, realtime_data, 30)
    
    return realtime_data

# Critical Alerts Management
@router.get("/alerts/critical")
async def get_critical_alerts(
    request: Request,
    current_user: dict = Depends(require_manager_up)
):
    """Get all critical system and business alerts"""
    cache_key = "admin:critical:alerts"
    cached = redis_client.get(cache_key)
    if cached:
        return cached
    
    alerts = []
    
    # System alerts (Super Admin only)
    if current_user["role"] == UserRole.SUPER_ADMIN:
        system_health = await AdminService.get_system_health()
        if system_health["status"] != "healthy":
            alerts.append({
                "type": "system",
                "severity": "critical" if system_health["status"] == "critical" else "warning",
                "title": "System Health Issue",
                "message": f"System status: {system_health['status']}",
                "details": system_health["errors"],
                "timestamp": system_health["timestamp"]
            })
    
    # Business alerts
    # Out of stock items
    out_of_stock = supabase.table("products").select("name, categories(name)").eq("status", "out_of_stock").execute()
    if out_of_stock.data:
        alerts.append({
            "type": "inventory",
            "severity": "high",
            "title": "Products Out of Stock",
            "message": f"{len(out_of_stock.data)} products are completely out of stock",
            "details": [f"{p['name']} ({p['categories']['name']})" for p in out_of_stock.data[:5]],
            "count": len(out_of_stock.data),
            "timestamp": datetime.utcnow().isoformat()
        })
    
    # Old pending orders
    old_pending = supabase.table("orders").select("order_number, created_at").eq("status", "pending").lt("created_at", (datetime.utcnow() - timedelta(hours=2)).isoformat()).execute()
    if old_pending.data:
        alerts.append({
            "type": "orders",
            "severity": "medium",
            "title": "Stale Pending Orders",
            "message": f"{len(old_pending.data)} orders have been pending for over 2 hours",
            "details": [f"Order {o['order_number']}" for o in old_pending.data[:5]],
            "count": len(old_pending.data),
            "timestamp": datetime.utcnow().isoformat()
        })
    
    # Failed activities (potential issues)
    failed_activities = supabase.table("activity_logs").select("resource, action, user_email").gte("created_at", (datetime.utcnow() - timedelta(hours=24)).isoformat()).execute()
    if failed_activities.data and len(failed_activities.data) > 10:
        alerts.append({
            "type": "system",
            "severity": "medium",
            "title": "High Error Rate",
            "message": f"{len(failed_activities.data)} errors recorded in the last 24 hours",
            "details": [f"{a['action']} on {a['resource']}" for a in failed_activities.data[:5]],
            "count": len(failed_activities.data),
            "timestamp": datetime.utcnow().isoformat()
        })
    
    # Inactive staff
    inactive_staff = supabase.table("profiles").select("email, role, last_login").eq("is_active", True).lt("last_login", (datetime.utcnow() - timedelta(days=7)).isoformat()).execute()
    if inactive_staff.data and len(inactive_staff.data) > 3:
        alerts.append({
            "type": "staff",
            "severity": "low",
            "title": "Inactive Staff Members",
            "message": f"{len(inactive_staff.data)} staff haven't logged in for 7+ days",
            "details": [f"{s['email']} ({s['role']})" for s in inactive_staff.data[:5]],
            "count": len(inactive_staff.data),
            "timestamp": datetime.utcnow().isoformat()
        })
    
    alerts_data = {
        "alerts": sorted(alerts, key=lambda x: {"critical": 4, "high": 3, "medium": 2, "low": 1}[x["severity"]], reverse=True),
        "summary": {
            "total_alerts": len(alerts),
            "critical_count": len([a for a in alerts if a["severity"] == "critical"]),
            "high_count": len([a for a in alerts if a["severity"] == "high"]),
            "medium_count": len([a for a in alerts if a["severity"] == "medium"]),
            "low_count": len([a for a in alerts if a["severity"] == "low"])
        }
    }
    
    # Cache for 2 minutes
    redis_client.set(cache_key, alerts_data, 120)
    
    return alerts_data

# Performance Monitoring
@router.get("/performance/summary")
async def get_performance_summary(
    request: Request,
    hours: int = 24,
    current_user: dict = Depends(require_super_admin)
):
    """Get system performance summary over specified hours"""
    if hours > 168:  # Max 1 week
        raise HTTPException(status_code=400, detail="Maximum 168 hours (1 week) allowed")
    
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=hours)
    
    # Get performance data
    orders_result = supabase.table("orders").select("created_at, status").gte("created_at", start_time.isoformat()).execute()
    activities_result = supabase.table("activity_logs").select("created_at, action").gte("created_at", start_time.isoformat()).execute()
    
    # Calculate hourly performance
    hourly_performance = defaultdict(lambda: {"orders": 0, "activities": 0, "errors": 0})
    
    for order in orders_result.data:
        hour_key = datetime.fromisoformat(order["created_at"]).replace(minute=0, second=0, microsecond=0)
        hourly_performance[hour_key]["orders"] += 1
    
    for activity in activities_result.data:
        hour_key = datetime.fromisoformat(activity["created_at"]).replace(minute=0, second=0, microsecond=0)
        hourly_performance[hour_key]["activities"] += 1
        if "error" in activity.get("notes", "").lower():
            hourly_performance[hour_key]["errors"] += 1
    
    # System metrics
    try:
        redis_info = redis_client.client.info()
        system_metrics = {
            "redis_memory_usage": redis_info.get("used_memory_human", "Unknown"),
            "redis_connected_clients": redis_info.get("connected_clients", 0),
            "cache_hit_rate": round(
                (redis_info.get("keyspace_hits", 0) / 
                 (redis_info.get("keyspace_hits", 0) + redis_info.get("keyspace_misses", 1)) * 100), 2
            )
        }
    except:
        system_metrics = {"status": "Redis unavailable"}
    
    performance_data = {
        "period": {"start": start_time, "end": end_time, "hours": hours},
        "system_metrics": system_metrics,
        "performance_summary": {
            "total_orders": len(orders_result.data),
            "total_activities": len(activities_result.data),
            "error_count": sum(p["errors"] for p in hourly_performance.values()),
            "peak_hour_orders": max(hourly_performance.values(), key=lambda x: x["orders"])["orders"] if hourly_performance else 0,
            "average_orders_per_hour": len(orders_result.data) / hours if hours > 0 else 0
        },
        "hourly_breakdown": [
            {
                "hour": hour.isoformat(),
                **data
            }
            for hour, data in sorted(hourly_performance.items())
        ]
    }
    
    return performance_data

# Bulk User Operations (Super Admin only)
@router.post("/users/bulk-action")
async def bulk_user_action(
    request: Request,
    action: str,  # "activate", "deactivate", "delete"
    user_ids: List[str],
    reason: Optional[str] = None,
    current_user: dict = Depends(require_super_admin)
):
    """Perform bulk actions on users"""
    if action not in ["activate", "deactivate", "delete"]:
        raise HTTPException(status_code=400, detail="Action must be activate, deactivate, or delete")
    
    if len(user_ids) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 users per bulk action")
    
    # Prevent self-action
    if current_user["id"] in user_ids:
        raise HTTPException(status_code=400, detail="Cannot perform bulk action on your own account")
    
    results = {"successful": [], "failed": []}
    
    for user_id in user_ids:
        try:
            # Get user details
            user_result = supabase.table("profiles").select("*").eq("id", user_id).execute()
            if not user_result.data:
                results["failed"].append({"user_id": user_id, "error": "User not found"})
                continue
            
            user = user_result.data[0]
            
            # Prevent actions on other super admins
            if user["role"] == UserRole.SUPER_ADMIN and user_id != current_user["id"]:
                results["failed"].append({"user_id": user_id, "error": "Cannot modify other super admins"})
                continue
            
            if action == "delete":
                # Delete from auth and profile
                supabase_admin.auth.admin.delete_user(user_id)
                supabase.table("profiles").delete().eq("id", user_id).execute()
                
                results["successful"].append({
                    "user_id": user_id,
                    "email": user["email"],
                    "action": "deleted"
                })
                
            else:
                # Activate/deactivate
                is_active = action == "activate"
                supabase.table("profiles").update({
                    "is_active": is_active,
                    "updated_at": datetime.utcnow().isoformat()
                }).eq("id", user_id).execute()
                
                results["successful"].append({
                    "user_id": user_id,
                    "email": user["email"],
                    "action": action
                })
            
            # Log individual action
            await log_activity(
                current_user["id"], current_user["email"], current_user["role"],
                action, "user", user_id, 
                {"reason": reason, "target_email": user["email"], "bulk_action": True},
                request
            )
            
        except Exception as e:
            results["failed"].append({
                "user_id": user_id,
                "error": str(e)
            })
    
    # Log bulk action summary
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "bulk_action", "users", None,
        {
            "action": action,
            "total_users": len(user_ids),
            "successful": len(results["successful"]),
            "failed": len(results["failed"]),
            "reason": reason
        },
        request
    )
    
    return {
        "message": f"Bulk {action} completed",
        "results": results,
        "summary": {
            "total_processed": len(user_ids),
            "successful": len(results["successful"]),
            "failed": len(results["failed"])
        }
    }



# User Management (move from management.py to admin.py)
@router.get("/users", response_model=List[dict])
async def get_all_users(
    request: Request,
    role: Optional[UserRole] = None,
    is_active: Optional[bool] = None,
    current_user: dict = Depends(require_manager_up)
):
    query = supabase.table("profiles").select("*, invitations!invited_by(invited_by)")
    
    if current_user["role"] == UserRole.MANAGER:
        query = query.neq("role", UserRole.SUPER_ADMIN)
    
    if role:
        query = query.eq("role", role)
    if is_active is not None:
        query = query.eq("is_active", is_active)
    
    result = query.order("created_at", desc=True).execute()
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "view", "users", None, {"filter_role": role, "filter_active": is_active},
        request
    )
    
    return result.data

@router.patch("/users/{user_id}/status")
async def update_user_status(
    user_id: str,
    is_active: bool,
    reason: Optional[str] = None,
    request: Request = None,
    current_user: dict = Depends(require_manager_up)
):
    target_user = supabase.table("profiles").select("*").eq("id", user_id).execute()
    if not target_user.data:
        raise HTTPException(status_code=404, detail="User not found")
    
    target_role = target_user.data[0]["role"]
    
    if current_user["role"] == UserRole.MANAGER:
        if target_role in [UserRole.SUPER_ADMIN, UserRole.MANAGER]:
            raise HTTPException(status_code=403, detail="Cannot modify users with equal or higher role")
    
    supabase.table("profiles").update({
        "is_active": is_active,
        "updated_at": datetime.utcnow().isoformat()
    }).eq("id", user_id).execute()
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "revoke" if not is_active else "restore", "user",
        user_id, {"reason": reason, "target_email": target_user.data[0]["email"]},
        request
    )
    
    return {"message": f"User {'deactivated' if not is_active else 'activated'} successfully"}

# Activity Monitoring
@router.get("/activities", response_model=List[dict])
async def get_activity_logs(
    request: Request,
    user_id: Optional[str] = None,
    resource: Optional[str] = None,
    action: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 100,
    current_user: dict = Depends(require_manager_up)
):
    query = supabase.table("activity_logs").select("*")
    
    if current_user["role"] == UserRole.MANAGER:
        query = query.neq("user_role", UserRole.SUPER_ADMIN)
    
    if user_id:
        query = query.eq("user_id", user_id)
    if resource:
        query = query.eq("resource", resource)
    if action:
        query = query.eq("action", action)
    if date_from:
        query = query.gte("created_at", date_from.isoformat())
    if date_to:
        query = query.lte("created_at", date_to.isoformat())
    
    result = query.order("created_at", desc=True).limit(limit).execute()
    return result.data

@router.get("/activities/user/{user_id}")
async def get_user_activities(
    user_id: str,
    request: Request,
    limit: int = 50,
    current_user: dict = Depends(require_manager_up)
):
    target_user = supabase.table("profiles").select("role").eq("id", user_id).execute()
    if not target_user.data:
        raise HTTPException(status_code=404, detail="User not found")
    
    if current_user["role"] == UserRole.MANAGER and target_user.data[0]["role"] == "super_admin":
        raise HTTPException(status_code=403, detail="Cannot view this user's activities")
    
    result = supabase.table("activity_logs").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(limit).execute()
    return result.data

# Team Performance
@router.get("/team-performance")
async def get_team_performance(
    request: Request,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    current_user: dict = Depends(require_manager_up)
):
    if not date_from:
        date_from = date.today() - timedelta(days=7)
    if not date_to:
        date_to = date.today()
    
    query = supabase.table("profiles").select("*").eq("is_active", True)
    if current_user["role"] == UserRole.MANAGER:
        query = query.neq("role", UserRole.SUPER_ADMIN)
    
    team = query.execute()
    
    performance = []
    for member in team.data:
        activities = supabase.table("activity_logs").select("action").eq("user_id", member["id"]).gte("created_at", date_from.isoformat()).lte("created_at", date_to.isoformat()).execute()
        
        metrics = {"total_actions": len(activities.data)}
        
        if member["role"] == "sales":
            orders = supabase.table("orders").select("id").eq("created_by", member["id"]).gte("created_at", date_from.isoformat()).execute()
            metrics["orders_created"] = len(orders.data)
        elif member["role"] == "inventory_staff":
            entries = supabase.table("stock_entries").select("id").eq("entered_by", member["id"]).gte("created_at", date_from.isoformat()).execute()
            metrics["stock_entries"] = len(entries.data)
        elif member["role"] == "chef":
            chef_activities = [a for a in activities.data if a["action"] == "order_completed"]
            metrics["orders_completed"] = len(chef_activities)
        
        performance.append({
            "user": {
                "id": member["id"],
                "email": member["email"],
                "role": member["role"]
            },
            "metrics": metrics,
            "last_active": member["last_login"]
        })
    
    return {
        "period": {"from": date_from, "to": date_to},
        "team_performance": performance
    }


@router.get("/analytics/raw-materials")
async def get_raw_materials_analytics(
    request: Request,
    period: str = Query("monthly", pattern="^(daily|weekly|monthly|quarterly|yearly)$"),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    current_user: dict = Depends(require_manager_up)
):
    """Get comprehensive raw materials analytics"""
    raw_materials_data = await AdminService.get_raw_materials_analytics(period, date_from, date_to)
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "view", "raw_materials_analytics", None, 
        {"period": period, "date_from": str(date_from), "date_to": str(date_to)}, 
        request
    )
    
    return raw_materials_data



@router.post("/payroll/staff")
async def create_staff_salary(
    staff_data: StaffSalaryCreate,
    request: Request,
    current_user: dict = Depends(require_super_admin)
):
    """Create or update staff salary entry"""
    
    # Validate staff exists if staff_id provided
    if staff_data.staff_id:
        staff = supabase.table("profiles").select("*").eq("id", staff_data.staff_id).execute()
        if not staff.data:
            raise HTTPException(status_code=404, detail="Staff member not found")
        
        # Auto-populate from profile if system staff
        staff_profile = staff.data[0]
        actual_name = staff_profile["email"].split("@")[0].replace(".", " ").title()
        actual_role = staff_profile["role"]
        is_system = True
    else:
        # Manual entry
        actual_name = staff_data.staff_name
        actual_role = staff_data.staff_role
        is_system = False
    
    # Check if salary entry already exists for this effective date
    if staff_data.staff_id:
        existing = supabase.table("staff_salaries").select("*").eq("staff_id", staff_data.staff_id).eq("effective_date", staff_data.effective_date.isoformat()).execute()
    else:
        existing = supabase.table("staff_salaries").select("*").eq("staff_name", staff_data.staff_name).eq("effective_date", staff_data.effective_date.isoformat()).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Salary entry already exists for this date")
    
    salary_entry = {
        "staff_id": staff_data.staff_id,
        "staff_name": actual_name,
        "staff_role": actual_role,
        "salary_amount": float(staff_data.salary_amount),
        "effective_date": staff_data.effective_date.isoformat(),
        "is_system_staff": is_system,
        "created_by": current_user["id"]
    }
    
    result = supabase.table("staff_salaries").insert(salary_entry).execute()
    
    # Log initial salary in history
    history_entry = {
        "staff_id": staff_data.staff_id,
        "old_salary": None,
        "new_salary": float(staff_data.salary_amount),
        "change_reason": "Initial salary entry",
        "change_type": "initial",
        "changed_by": current_user["id"]
    }
    
    supabase.table("salary_history").insert(history_entry).execute()
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "create", "staff_salary", result.data[0]["id"],
        {"staff_name": actual_name, "salary": float(staff_data.salary_amount)},
        request
    )
    
    return {"message": "Staff salary created", "data": result.data[0]}

@router.get("/payroll/staff")
async def get_staff_salaries(
    request: Request,
    active_only: bool = True,
    current_user: dict = Depends(require_manager_up)
):
    """Get all staff salary entries"""
    query = supabase.table("staff_salaries").select("*")
    
    if active_only:
        query = query.eq("is_active", True)
    
    result = query.order("staff_name").execute()
    
    return result.data

@router.patch("/payroll/staff/{salary_id}")
async def update_staff_salary(
    salary_id: str,
    update_data: StaffSalaryUpdate,
    request: Request,
    current_user: dict = Depends(require_super_admin)
):
    """Update staff salary - creates history record for salary changes"""
    
    # Get current salary entry
    current_salary = supabase.table("staff_salaries").select("*").eq("id", salary_id).execute()
    
    if not current_salary.data:
        raise HTTPException(status_code=404, detail="Salary entry not found")
    
    current_data = current_salary.data[0]
    updates = {}
    
    # Handle salary change
    if update_data.salary_amount is not None:
        old_salary = float(current_data["salary_amount"])
        new_salary = float(update_data.salary_amount)
        
        if old_salary != new_salary:
            # Determine change type
            change_type = "increase" if new_salary > old_salary else "decrease"
            
            # Create history record
            history_entry = {
                "staff_id": current_data["staff_id"],
                "old_salary": old_salary,
                "new_salary": new_salary,
                "change_reason": update_data.change_reason or f"Salary {change_type}",
                "change_type": change_type,
                "changed_by": current_user["id"]
            }
            
            supabase.table("salary_history").insert(history_entry).execute()
            
            updates["salary_amount"] = new_salary
    
    # Handle activation/deactivation
    if update_data.is_active is not None:
        updates["is_active"] = update_data.is_active
    
    if updates:
        updates["updated_at"] = datetime.utcnow().isoformat()
        result = supabase.table("staff_salaries").update(updates).eq("id", salary_id).execute()
        
        await log_activity(
            current_user["id"], current_user["email"], current_user["role"],
            "update", "staff_salary", salary_id,
            {"changes": updates, "staff_name": current_data["staff_name"]},
            request
        )
    
    return {"message": "Staff salary updated"}

@router.get("/payroll/staff/{staff_id}/history")
async def get_staff_salary_history(
    staff_id: str,
    request: Request,
    current_user: dict = Depends(require_manager_up)
):
    """Get salary change history for specific staff"""
    
    history = supabase.table("salary_history").select(
        "*, profiles!salary_history_changed_by_fkey(email)"
    ).eq("staff_id", staff_id).order("change_date", desc=True).execute()
    
    return history.data

@router.delete("/payroll/staff/{salary_id}")
async def delete_staff_salary(
    salary_id: str,
    request: Request,
    current_user: dict = Depends(require_super_admin)
):
    """Soft delete staff salary entry (deactivate)"""
    
    result = supabase.table("staff_salaries").update({
        "is_active": False,
        "updated_at": datetime.utcnow().isoformat()
    }).eq("id", salary_id).execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Salary entry not found")
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "deactivate", "staff_salary", salary_id, None, request
    )
    
    return {"message": "Staff salary deactivated"}

# Auto-populate system staff
@router.post("/payroll/sync-system-staff")
async def sync_system_staff(
    request: Request,
    current_user: dict = Depends(require_super_admin)
):
    """Auto-populate salary entries for all active system staff without salaries"""
    
    # Get all active profiles that don't have salary entries
    profiles = supabase.table("profiles").select("*").eq("is_active", True).execute()
    existing_salaries = supabase.table("staff_salaries").select("staff_id").eq("is_system_staff", True).execute()
    
    existing_staff_ids = {s["staff_id"] for s in existing_salaries.data if s["staff_id"]}
    
    new_entries = []
    for profile in profiles.data:
        if profile["id"] not in existing_staff_ids:
            entry = {
                "staff_id": profile["id"],
                "staff_name": profile["email"].split("@")[0].replace(".", " ").title(),
                "staff_role": profile["role"],
                "salary_amount": 0.00,  # Default to 0, admin can update
                "is_system_staff": True,
                "created_by": current_user["id"]
            }
            new_entries.append(entry)
    
    if new_entries:
        result = supabase.table("staff_salaries").insert(new_entries).execute()
        
        await log_activity(
            current_user["id"], current_user["email"], current_user["role"],
            "sync", "system_staff_salaries", None,
            {"new_entries": len(new_entries)},
            request
        )
        
        return {"message": f"Synced {len(new_entries)} system staff members", "created": len(new_entries)}
    
    return {"message": "All system staff already have salary entries", "created": 0}

# Expenditure Categories Management
@router.post("/expenditures/categories")
async def create_expenditure_category(
    category_data: ExpenditureCategoryCreate,
    request: Request,
    current_user: dict = Depends(require_manager_up)
):
    """Create expenditure category"""
    
    # Check unique name
    existing = supabase.table("expenditure_categories").select("id").eq("name", category_data.name).execute()
    
    if existing.data:
        raise HTTPException(status_code=400, detail="Category name already exists")
    
    category_entry = {
        **category_data.dict(),
        "created_by": current_user["id"]
    }
    
    result = supabase.table("expenditure_categories").insert(category_entry).execute()
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "create", "expenditure_category", result.data[0]["id"],
        {"category_name": category_data.name},
        request
    )
    
    return {"message": "Expenditure category created", "data": result.data[0]}

@router.get("/expenditures/categories")
async def get_expenditure_categories(
    active_only: bool = True,
    current_user: dict = Depends(get_current_user)
):
    """Get expenditure categories"""
    
    query = supabase.table("expenditure_categories").select("*")
    
    if active_only:
        query = query.eq("is_active", True)
    
    result = query.order("name").execute()
    return result.data

@router.patch("/expenditures/categories/{category_id}")
async def update_expenditure_category(
    category_id: str,
    update_data: ExpenditureCategoryUpdate,
    request: Request,
    current_user: dict = Depends(require_manager_up)
):
    """Update expenditure category"""
    
    updates = {k: v for k, v in update_data.dict().items() if v is not None}
    
    if updates:
        updates["updated_at"] = datetime.utcnow().isoformat()
        result = supabase.table("expenditure_categories").update(updates).eq("id", category_id).execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Category not found")
        
        await log_activity(
            current_user["id"], current_user["email"], current_user["role"],
            "update", "expenditure_category", category_id, updates, request
        )
    
    return {"message": "Category updated"}

# Expenditure Logging
@router.post("/expenditures")
async def create_expenditure(
    expenditure_data: ExpenditureCreate,
    request: Request,
    current_user: dict = Depends(require_manager_up)
):
    """Log expenditure"""
    
    # Verify category exists
    category = supabase.table("expenditure_categories").select("name").eq("id", expenditure_data.category_id).eq("is_active", True).execute()
    
    if not category.data:
        raise HTTPException(status_code=404, detail="Expenditure category not found")
    
    expenditure_entry = {
        **expenditure_data.dict(),
        "amount": float(expenditure_data.amount),
        "expense_date": expenditure_data.expense_date.isoformat(),
        "logged_by": current_user["id"]
    }
    
    result = supabase.table("expenditures").insert(expenditure_entry).execute()
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "create", "expenditure", result.data[0]["id"],
        {
            "category": category.data[0]["name"],
            "amount": float(expenditure_data.amount),
            "description": expenditure_data.description
        },
        request
    )
    
    return {"message": "Expenditure logged", "data": result.data[0]}

@router.get("/expenditures")
async def get_expenditures(
    request: Request,
    category_id: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user)
):
    """Get expenditures with filtering"""
    
    query = supabase.table("expenditures").select(
        "*, expenditure_categories(name), profiles(email)"
    )
    
    if category_id:
        query = query.eq("category_id", category_id)
    
    if date_from:
        query = query.gte("expense_date", date_from.isoformat())
    
    if date_to:
        query = query.lte("expense_date", date_to.isoformat())
    
    result = query.order("logged_at", desc=True).range(offset, offset + limit - 1).execute()
    
    return {
        "expenditures": result.data,
        "limit": limit,
        "offset": offset
    }

@router.patch("/expenditures/{expenditure_id}")
async def update_expenditure(
    expenditure_id: str,
    update_data: ExpenditureUpdate,
    request: Request,
    current_user: dict = Depends(require_manager_up)
):
    """Update expenditure (manager+ only)"""
    
    updates = {}
    for k, v in update_data.dict().items():
        if v is not None:
            if k == "amount":
                updates[k] = float(v)
            elif k == "expense_date":
                updates[k] = v.isoformat()
            else:
                updates[k] = v
    
    if updates:
        result = supabase.table("expenditures").update(updates).eq("id", expenditure_id).execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Expenditure not found")
        
        await log_activity(
            current_user["id"], current_user["email"], current_user["role"],
            "update", "expenditure", expenditure_id, updates, request
        )
    
    return {"message": "Expenditure updated"}

@router.delete("/expenditures/{expenditure_id}")
async def delete_expenditure(
    expenditure_id: str,
    request: Request,
    current_user: dict = Depends(require_manager_up)
):
    """Delete expenditure (manager+ only)"""
    
    result = supabase.table("expenditures").delete().eq("id", expenditure_id).execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Expenditure not found")
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "delete", "expenditure", expenditure_id, None, request
    )
    
    return {"message": "Expenditure deleted"}