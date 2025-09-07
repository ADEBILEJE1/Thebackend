from pydantic import BaseModel, EmailStr
from typing import Optional
from ..models.user import UserRole

class UserCreate(BaseModel):
    email: Optional[EmailStr] = None  
    password: str
    invitation_token: str

    class Config:
        json_schema_extra = {
            "example": {
                "invitation_token": "abc123token",
                "password": "SecurePassword123!"
            }
        }


class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserInvite(BaseModel):
    email: EmailStr
    role: UserRole

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class UserResponse(BaseModel):
    id: str
    email: str
    role: str
    is_active: bool