from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr

class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    MANAGER = "manager"
    INVENTORY = "inventory"
    SALES = "sales"
    CHEF = "chef"

class User(BaseModel):
    id: Optional[str] = None
    email: EmailStr
    role: UserRole
    is_active: bool = True
    invited_by: Optional[str] = None
    created_at: Optional[datetime] = None
    last_login: Optional[datetime] = None
    
class Invitation(BaseModel):
    id: Optional[str] = None
    email: EmailStr
    role: UserRole
    token: str
    invited_by: str
    expires_at: datetime
    used: bool = False
    created_at: Optional[datetime] = None