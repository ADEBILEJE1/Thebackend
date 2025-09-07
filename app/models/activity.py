from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel

class ActivityLog(BaseModel):
    id: Optional[str] = None
    user_id: str
    user_email: str
    user_role: str
    action: str  # "create", "update", "delete", "login", "logout", "invite", "revoke"
    resource: str  # "product", "order", "user", "inventory", etc
    resource_id: Optional[str] = None
    details: Optional[dict] = None
    ip_address: Optional[str] = None
    created_at: Optional[datetime] = None

class Report(BaseModel):
    id: Optional[str] = None
    report_type: str  # "sales", "inventory", "activity"
    date_from: datetime
    date_to: datetime
    generated_by: str
    file_url: Optional[str] = None
    created_at: Optional[datetime] = None