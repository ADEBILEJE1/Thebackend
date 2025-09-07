from typing import TypeVar, Any, Awaitable, Callable, cast, Optional
from functools import wraps
import hashlib
from ..services.redis import redis_client

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])

class CacheKeys:
    """Centralized cache key management"""
    
    # User/Auth
    USER_SESSION = "session:{user_id}"
    USER_PROFILE = "profile:{user_id}"
    USER_PERMISSIONS = "permissions:{user_id}"
    
    # Products
    PRODUCT_LIST = "products:list:{filters}"
    PRODUCT_DETAIL = "product:{product_id}"
    CATEGORIES = "categories:all"
    CATEGORY_PRODUCTS = "category:{category_id}:products"
    
    # Orders
    ORDER_QUEUE = "orders:queue:{status}"
    ORDER_DETAIL = "order:{order_id}"
    TODAYS_ORDERS = "orders:today"
    
    # Dashboard
    DASHBOARD_STATS = "dashboard:stats:{user_id}"
    SALES_METRICS = "metrics:sales:{date}"
    INVENTORY_METRICS = "metrics:inventory"
    LOW_STOCK_ALERTS = "alerts:low_stock"
    
    # Rate limiting
    RATE_LIMIT = "rate_limit:{user_id}:{endpoint}"

def cache_key_wrapper(seconds: int = 300):
    """Decorator for caching function results"""
    
    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            cache_key = f"{func.__name__}:{hashlib.md5(str(args).encode() + str(kwargs).encode()).hexdigest()}"

            # Try to get from cache
            cached = redis_client.get(cache_key)
            if cached:
                return cached

            # Execute function
            result = await func(*args, **kwargs)

            # Store in cache
            if result is not None:
                redis_client.set(cache_key, result, seconds)

            return result

        return cast(F, wrapper)  # ✅ tells FastAPI it's the same type as func
    return decorator

def invalidate_cache(pattern: str):
    """Invalidate cache by pattern"""
    redis_client.delete_pattern(pattern)

# Cache invalidation helpers
def invalidate_product_cache(product_id: Optional[str] = None):
    """Invalidate product-related caches"""
    if product_id:
        redis_client.delete(CacheKeys.PRODUCT_DETAIL.format(product_id=product_id))
    redis_client.delete_pattern("products:list:*")
    redis_client.delete_pattern("category:*:products")
    redis_client.delete(CacheKeys.LOW_STOCK_ALERTS)

def invalidate_order_cache(order_id: Optional[str] = None):
    """Invalidate order-related caches"""
    if order_id:
        redis_client.delete(CacheKeys.ORDER_DETAIL.format(order_id=order_id))
    redis_client.delete_pattern("orders:queue:*")
    redis_client.delete(CacheKeys.TODAYS_ORDERS)
    redis_client.delete_pattern("dashboard:stats:*")
    redis_client.delete_pattern("metrics:sales:*")

def invalidate_user_cache(user_id: str):
    """Invalidate user-related caches"""
    redis_client.delete(
        CacheKeys.USER_SESSION.format(user_id=user_id),
        CacheKeys.USER_PROFILE.format(user_id=user_id),
        CacheKeys.USER_PERMISSIONS.format(user_id=user_id)
    )