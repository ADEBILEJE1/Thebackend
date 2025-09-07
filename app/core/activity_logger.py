from typing import Optional, Any
from datetime import datetime
from ..database import supabase
from fastapi import Request

async def log_activity(
    user_id: str,
    user_email: str,
    user_role: str,
    action: str,
    resource: str,
    resource_id: Optional[str] = None,
    details: Optional[dict] = None,
    request: Optional[Request] = None
):
    """Log user activity"""
    activity = {
        "user_id": user_id,
        "user_email": user_email,
        "user_role": user_role,
        "action": action,
        "resource": resource,
        "resource_id": resource_id,
        "details": details,
        "ip_address": request.client.host if request else None
    }
    
    supabase.table("activity_logs").insert(activity).execute()