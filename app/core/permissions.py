

from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBearer
from ..models.user import UserRole
from ..database import supabase, supabase_admin
from ..services.redis import redis_client
from ..core.session import session_manager
from ..core.cache import CacheKeys

security = HTTPBearer()

async def get_current_user(token = Depends(security)):
    user_id = session_manager.validate_token(token.credentials)
    
    if user_id:
        cache_key = CacheKeys.USER_PROFILE.format(user_id=user_id)
        user_data = redis_client.get(cache_key)
        
        if user_data and isinstance(user_data, dict) and "id" in user_data:
            
            if user_data["role"] == UserRole.SUPER_ADMIN and "active_dashboard" in user_data:
                user_data["effective_role"] = user_data["active_dashboard"]
            else:
                user_data["effective_role"] = user_data["role"]
            return user_data
        
        try:
            user_result = supabase_admin.table("profiles").select("*").eq("id", user_id).single().execute()
            if user_result.data:
                
                session_data = session_manager.get_session(user_id, token.credentials)
                if session_data and "active_dashboard" in session_data:
                    user_result.data["active_dashboard"] = session_data["active_dashboard"]
                    user_result.data["effective_role"] = session_data["active_dashboard"]
                else:
                    user_result.data["effective_role"] = user_result.data["role"]
                
                redis_client.set(cache_key, user_result.data, 300)
                return user_result.data
        except:
            session_manager.destroy_session(user_id, token.credentials)
    
   
    try:
        user = supabase.auth.get_user(token.credentials)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials"
            )
        
        try:
            user_data = supabase_admin.table("profiles").select("*").eq("id", user.user.id).single().execute()
            if not user_data.data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User profile not found"
                )
        except:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User profile not found"
            )
        
        
        user_data.data["effective_role"] = user_data.data["role"]
        
        
        session_manager.create_session(user.user.id, user_data.data, token.credentials)
        
        return user_data.data
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )


async def require_super_admin(current_user: dict = Depends(get_current_user)):
    allowed_roles = [UserRole.SUPER_ADMIN]
    cache_key = CacheKeys.USER_PERMISSIONS.format(user_id=current_user["id"])
    cached_permission = redis_client.hget(cache_key, str(allowed_roles))
    
    if cached_permission == "allowed":
        return current_user
    elif cached_permission == "denied":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )
    
    check_role = current_user.get("effective_role", current_user["role"])
    
    if check_role in allowed_roles:
        redis_client.hset(cache_key, {str(allowed_roles): "allowed"})
        redis_client.expire(cache_key, 300)
        return current_user
    else:
        redis_client.hset(cache_key, {str(allowed_roles): "denied"})
        redis_client.expire(cache_key, 300)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )

async def require_manager_up(current_user: dict = Depends(get_current_user)):
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.MANAGER]
    cache_key = CacheKeys.USER_PERMISSIONS.format(user_id=current_user["id"])
    cached_permission = redis_client.hget(cache_key, str(allowed_roles))
    
    if cached_permission == "allowed":
        return current_user
    elif cached_permission == "denied":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )
    
    check_role = current_user.get("effective_role", current_user["role"])
    
    if check_role in allowed_roles:
        redis_client.hset(cache_key, {str(allowed_roles): "allowed"})
        redis_client.expire(cache_key, 300)
        return current_user
    else:
        redis_client.hset(cache_key, {str(allowed_roles): "denied"})
        redis_client.expire(cache_key, 300)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )

async def require_staff(current_user: dict = Depends(get_current_user)):
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.MANAGER, UserRole.INVENTORY, UserRole.SALES, UserRole.CHEF]
    cache_key = CacheKeys.USER_PERMISSIONS.format(user_id=current_user["id"])
    cached_permission = redis_client.hget(cache_key, str(allowed_roles))
    
    if cached_permission == "allowed":
        return current_user
    elif cached_permission == "denied":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )
    
    check_role = current_user.get("effective_role", current_user["role"])
    
    if check_role in allowed_roles:
        redis_client.hset(cache_key, {str(allowed_roles): "allowed"})
        redis_client.expire(cache_key, 300)
        return current_user
    else:
        redis_client.hset(cache_key, {str(allowed_roles): "denied"})
        redis_client.expire(cache_key, 300)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )

async def require_inventory_staff(current_user: dict = Depends(get_current_user)):
    allowed_roles = [UserRole.INVENTORY, UserRole.MANAGER, UserRole.SUPER_ADMIN]
    cache_key = CacheKeys.USER_PERMISSIONS.format(user_id=current_user["id"])
    cached_permission = redis_client.hget(cache_key, str(allowed_roles))
    
    if cached_permission == "allowed":
        return current_user
    elif cached_permission == "denied":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )
    
    check_role = current_user.get("effective_role", current_user["role"])
    
    if check_role in allowed_roles:
        redis_client.hset(cache_key, {str(allowed_roles): "allowed"})
        redis_client.expire(cache_key, 300)
        return current_user
    else:
        redis_client.hset(cache_key, {str(allowed_roles): "denied"})
        redis_client.expire(cache_key, 300)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )


async def require_chef_staff(current_user: dict = Depends(get_current_user)):
    allowed_roles = [UserRole.CHEF, UserRole.MANAGER, UserRole.SUPER_ADMIN]
    cache_key = CacheKeys.USER_PERMISSIONS.format(user_id=current_user["id"])
    cached_permission = redis_client.hget(cache_key, str(allowed_roles))
    
    if cached_permission == "allowed":
        return current_user
    elif cached_permission == "denied":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )
    
    check_role = current_user.get("effective_role", current_user["role"])
    
    if check_role in allowed_roles:
        redis_client.hset(cache_key, {str(allowed_roles): "allowed"})
        redis_client.expire(cache_key, 300)
        return current_user
    else:
        redis_client.hset(cache_key, {str(allowed_roles): "denied"})
        redis_client.expire(cache_key, 300)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )


async def require_sales_staff(current_user: dict = Depends(get_current_user)):
    allowed_roles = [UserRole.SALES, UserRole.MANAGER, UserRole.SUPER_ADMIN]
    cache_key = CacheKeys.USER_PERMISSIONS.format(user_id=current_user["id"])
    cached_permission = redis_client.hget(cache_key, str(allowed_roles))
    
    if cached_permission == "allowed":
        return current_user
    elif cached_permission == "denied":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )
    
    check_role = current_user.get("effective_role", current_user["role"])
    
    if check_role in allowed_roles:
        redis_client.hset(cache_key, {str(allowed_roles): "allowed"})
        redis_client.expire(cache_key, 300)
        return current_user
    else:
        redis_client.hset(cache_key, {str(allowed_roles): "denied"})
        redis_client.expire(cache_key, 300)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )
