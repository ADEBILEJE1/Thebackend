from fastapi import APIRouter, HTTPException, status, Depends, Request
from datetime import datetime, timedelta
from pydantic import BaseModel, Field, EmailStr, validator
from typing import Optional
from fastapi import Security
from fastapi.security import OAuth2PasswordBearer
from ..core.security import generate_invitation_token
from ..core.permissions import (
    get_current_user, 
    require_super_admin, 
    require_manager_up, 
    require_staff,
    require_inventory_staff,
    require_sales_staff,
    require_chef_staff,
    security
)
from ..core.session import session_manager
from ..core.rate_limiter import auth_limiter
from ..core.cache import invalidate_user_cache
from ..database import supabase, supabase_admin
from ..services.celery import send_invitation_email
from ..models.user import UserRole
from ..core.activity_logger import log_activity




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

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    email: EmailStr
    new_password: str = Field(min_length=8)

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class DashboardSelection(BaseModel):
    selected_dashboard: str = Field(pattern="^(super_admin|manager|sales|inventory_staff|chef)$")

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/invite", response_model=dict)
async def invite_user(
    invitation: UserInvite,
    current_user: dict = Depends(require_manager_up)
):
    # Check role hierarchy
    if current_user["role"] == UserRole.MANAGER and invitation.role in [UserRole.SUPER_ADMIN, UserRole.MANAGER]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot invite users with equal or higher role"
        )
    
    # Check if user already exists
    existing = supabase.table("profiles").select("id").eq("email", invitation.email).execute()
    if existing.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already exists"
        )
    
    # Create invitation
    token = generate_invitation_token()
    expires_at = datetime.utcnow() + timedelta(days=7)
    
    invitation_data = {
        "email": invitation.email,
        "role": invitation.role,
        "token": token,
        "invited_by": current_user["id"],
        "expires_at": expires_at.isoformat(),
        "used": False
    }
    
    result = supabase_admin.table("invitations").insert(invitation_data).execute()
    
    # Send invitation email
    # send_invitation_email.delay(invitation.email, token)
    
    return {"message": "Invitation sent successfully"}




@router.post("/register", response_model=dict)
async def register(user_data: UserCreate):
    # Validate invitation token
    invitation = supabase_admin.table("invitations").select("*").eq("token", user_data.invitation_token).single().execute()
    
    if not invitation.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid invitation token"
        )
    
    if invitation.data["used"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation already used"
        )
    
    expires_at = datetime.fromisoformat(invitation.data["expires_at"]).replace(tzinfo=None)
    if expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation expired"
        )
    
    # Create user using Supabase Auth
    try:
        auth_response = supabase_admin.auth.admin.create_user({
            "email": invitation.data["email"],
            "password": user_data.password,
            "email_confirm": True
        })
        
        # Create profile with role
        profile_data = {
            "id": auth_response.user.id,
            "email": invitation.data["email"],
            "role": invitation.data["role"],
            "invited_by": invitation.data["invited_by"],
            "is_active": True
        }
        
        supabase_admin.table("profiles").insert(profile_data).execute()
        
        # Mark invitation as used
        supabase_admin.table("invitations").update({"used": True}).eq("id", invitation.data["id"]).execute()
        
        return {"message": "User created successfully", "email": invitation.data["email"]}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )






# @router.post("/login", response_model=dict)
# async def login(credentials: UserLogin, request: Request):
#     try:
#         # Use Supabase Auth
#         response = supabase.auth.sign_in_with_password({
#             "email": credentials.email,
#             "password": credentials.password
#         })
        
#         # Get profile
#         profile = supabase_admin.table("profiles").select("*").eq("id", response.user.id).single().execute()
        
#         if not profile.data:
#             supabase.auth.sign_out()
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail="User profile not found"
#             )
        
#         if not profile.data["is_active"]:
#             supabase.auth.sign_out()
#             raise HTTPException(
#                 status_code=status.HTTP_403_FORBIDDEN,
#                 detail="Account deactivated"
#             )
        
#         # Create Redis session
#         try:
#             session_manager.create_session(
#                 response.user.id,
#                 profile.data,
#                 response.session.access_token
#             )
#             print("DEBUG: Redis session created successfully")
#         except Exception as redis_error:
#             print(f"DEBUG: Redis session failed: {str(redis_error)}")
#             # Continue without Redis session for now
        
#         # Update last login
#         supabase.table("profiles").update({
#             "last_login": datetime.utcnow().isoformat()
#         }).eq("id", response.user.id).execute()
        
#         return {
#             "access_token": response.session.access_token,
#             "refresh_token": response.session.refresh_token,
#             "user": {
#                 "id": response.user.id,
#                 "email": profile.data["email"],
#                 "role": profile.data["role"]
#             }
#         }
#     except HTTPException:
#         raise
#     except Exception as e:
#         print(f"DEBUG: Login error: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Login failed: {str(e)}"
#         )


@router.post("/login", response_model=dict)
async def login(credentials: UserLogin, request: Request):
    try:
        await auth_limiter.check_rate_limit(request, credentials.email)
        
        response = supabase.auth.sign_in_with_password({
            "email": credentials.email,
            "password": credentials.password
        })
        
        profile = supabase_admin.table("profiles").select("*").eq("id", response.user.id).single().execute()
        
        if not profile.data:
            supabase.auth.sign_out()
            raise HTTPException(status_code=404, detail="User profile not found")
        
        if not profile.data["is_active"]:
            supabase.auth.sign_out()
            raise HTTPException(status_code=403, detail="Account deactivated")
        
        # Super admin needs dashboard selection
        if profile.data["role"] == UserRole.SUPER_ADMIN:
            return {
                "requires_dashboard_selection": True,
                "access_token": response.session.access_token,
                "refresh_token": response.session.refresh_token,
                "user": {
                    "id": response.user.id,
                    "email": profile.data["email"],
                    "role": profile.data["role"]
                },
                "available_dashboards": [
                    {"role": "super_admin", "label": "Super Admin Dashboard"},
                    {"role": "manager", "label": "Manager Dashboard"},
                    {"role": "sales", "label": "Sales Dashboard"},
                    {"role": "inventory_staff", "label": "Inventory Dashboard"},
                    {"role": "chef", "label": "Chef Dashboard"}
                ]
            }
        
        # Regular user - complete login
        session_manager.create_session(
            response.user.id,
            profile.data,
            response.session.access_token
        )
        
        supabase.table("profiles").update({
            "last_login": datetime.utcnow().isoformat()
        }).eq("id", response.user.id).execute()
        
        return {
            "requires_dashboard_selection": False,
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
            "user": {
                "id": response.user.id,
                "email": profile.data["email"],
                "role": profile.data["role"]
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Login failed: {str(e)}")


@router.post("/refresh")
async def refresh_token(refresh_token: str):
    try:
        response = supabase.auth.refresh_session(refresh_token)
        return {
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )



@router.post("/logout")
async def logout(
    current_user: dict = Depends(get_current_user),
    token = Depends(security) # Use the security object directly
):
    # Destroy Redis session
    session_manager.destroy_session(current_user["id"], token.credentials)
    
    # Invalidate user cache
    invalidate_user_cache(current_user["id"])
    
    # Sign out from Supabase
    try:
        supabase.auth.sign_out()
    except:
        pass
    
    return {"message": "Logged out successfully"}




@router.post("/change-password")
async def change_password(
    password_data: ChangePasswordRequest,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """Change password for authenticated user"""
    
    try:
        # Update password directly
        supabase_admin.auth.admin.update_user_by_id(
            current_user["id"],
            {"password": password_data.new_password}
        )
        
        # Destroy all other sessions except current
        session_manager.destroy_all_user_sessions(current_user["id"])
        
        # Log activity
        await log_activity(
            current_user["id"], current_user["email"], current_user["role"],
            "password_change", "auth", None,
            {"ip": request.client.host},
            request
        )
        
        return {"message": "Password changed successfully"}
        
    except Exception as e:
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password change failed"
        )
    
    


@router.post("/forgot-password")
async def forgot_password(
    request_data: ForgotPasswordRequest,
    request: Request
):
    """Send password reset link via email"""
    
    # Rate limiting
    await auth_limiter.check_rate_limit(request, request_data.email)
    
    # Check if user exists
    profile = supabase.table("profiles").select("id, is_active").eq("email", request_data.email).execute()
    
    if not profile.data:
        return {"message": "If the email exists, a reset link has been sent"}
    
    if not profile.data[0]["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated"
        )
    
    try:
        # Send reset link (not OTP)
        supabase.auth.reset_password_email(
            request_data.email,
            options={
                "redirect_to": "https://yourdomain.com/reset-password"  # Your frontend reset page
            }
        )
        
        # Log activity
        await log_activity(
            profile.data[0]["id"], request_data.email, "unknown",
            "forgot_password", "auth", None,
            {"ip": request.client.host},
            request
        )
        
        return {"message": "If the email exists, a reset link has been sent"}
        
    except Exception as e:
        return {"message": "If the email exists, a reset link has been sent"}


@router.post("/reset-password")
async def reset_password(
    reset_data: ResetPasswordRequest,
    request: Request
):
    """Reset password using token from email link"""
    
    # Rate limiting
    await auth_limiter.check_rate_limit(request, reset_data.email)
    
    try:
        # The token comes from the URL in the email link
        # User clicks link -> redirected to frontend -> frontend extracts token -> calls this endpoint
        response = supabase.auth.update_user({
            "password": reset_data.new_password
        })
        
        if not response.user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired reset link"
            )
        
        # Sign out all sessions
        session_manager.destroy_all_user_sessions(response.user.id)
        
        # Log activity
        await log_activity(
            response.user.id, reset_data.email, "unknown",
            "password_reset", "auth", None,
            {"ip": request.client.host},
            request
        )
        
        return {"message": "Password reset successful. Please login with your new password"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset link"
        )
    

@router.post("/select-dashboard")
async def select_dashboard(
    selection: DashboardSelection,
    token: str = Depends(security)
):
    """Complete super admin login by selecting dashboard"""
    
    try:
        user_response = supabase.auth.get_user(token.credentials)
        
        if not user_response.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        profile = supabase.table("profiles").select("*").eq("id", user_response.user.id).single().execute()
        
        if not profile.data or profile.data["role"] != UserRole.SUPER_ADMIN:
            raise HTTPException(status_code=403, detail="Only super admins can select dashboards")
        
        # Create session with selected dashboard
        session_data = profile.data.copy()
        session_data["active_dashboard"] = selection.selected_dashboard
        
        session_manager.create_session(
            user_response.user.id,
            session_data,
            token.credentials
        )
        
        supabase.table("profiles").update({
            "last_login": datetime.utcnow().isoformat()
        }).eq("id", user_response.user.id).execute()
        
        return {
            "message": "Dashboard selected successfully",
            "active_dashboard": selection.selected_dashboard,
            "user": {
                "id": user_response.user.id,
                "email": profile.data["email"],
                "role": profile.data["role"],
                "active_dashboard": selection.selected_dashboard
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid or expired token")