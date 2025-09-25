from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBearer
from ..models.user import UserRole
from ..database import supabase
from ..services.redis import redis_client
from ..core.session import session_manager
from ..core.cache import CacheKeys
from ..database import supabase, supabase_admin



security = HTTPBearer()

async def get_current_user(token = Depends(security)):
    # Check Redis session first
    user_id = session_manager.validate_token(token.credentials)
    
    if user_id:
        # Get cached user profile
        cache_key = CacheKeys.USER_PROFILE.format(user_id=user_id)
        user_data = session_manager.get_session(user_id, token.credentials)
        
        if user_data:
            return user_data
        
        # Fallback to database - handle missing profile
        try:
            user_data = supabase_admin.table("profiles").select("*").eq("id", user_id).single().execute()
            if user_data.data:
                # Cache for 5 minutes
                redis_client.set(cache_key, user_data.data, 300)
                return user_data.data
        except:
            # Profile not found in DB, clear invalid session
            session_manager.destroy_session(user_id, token.credentials)
    
    # Fallback to Supabase auth validation
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
        
        # Create session in Redis
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
    
    if current_user["role"] in allowed_roles:
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
    
    if current_user["role"] in allowed_roles:
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
   
   if current_user["role"] in allowed_roles:
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
    
    if current_user["role"] in allowed_roles:
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
   
   if current_user["role"] in allowed_roles:
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
    
    if current_user["role"] in allowed_roles:
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

