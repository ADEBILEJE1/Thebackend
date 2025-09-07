"""Cache warming utilities for better performance"""
from typing import List
from ..services.redis import redis_client
from ..database import supabase
from ..core.cache import CacheKeys
from datetime import datetime, date

async def warm_product_cache():
    """Pre-load frequently accessed products"""
    # Get all available products
    products = supabase.table("products").select("*, categories(*)").eq("is_available", True).execute()
    
    # Cache individual products
    for product in products.data:
        cache_key = CacheKeys.PRODUCT_DETAIL.format(product_id=product["id"])
        redis_client.set(cache_key, product, 300)
    
    # Cache product list
    redis_client.set("products:list:None:True:True", products.data, 60)
    
    # Cache categories
    categories = supabase.table("categories").select("*").eq("is_active", True).execute()
    redis_client.set(CacheKeys.CATEGORIES, categories.data, 600)
    
    print(f"Warmed cache with {len(products.data)} products and {len(categories.data)} categories")

async def warm_dashboard_cache():
    """Pre-load dashboard metrics"""
    start_of_day = datetime.combine(date.today(), datetime.min.time())
    
    # Today's orders
    orders = supabase.table("orders").select("status, total, order_type").gte("created_at", start_of_day.isoformat()).execute()
    
    stats = {
        "total_orders": len(orders.data),
        "pending": len([o for o in orders.data if o["status"] == "pending"]),
        "preparing": len([o for o in orders.data if o["status"] == "preparing"]),
        "completed": len([o for o in orders.data if o["status"] == "completed"]),
        "total_revenue": sum(float(o["total"]) for o in orders.data if o["status"] != "cancelled")
    }
    
    redis_client.set(CacheKeys.TODAYS_ORDERS, stats, 30)
    
    # Low stock alerts
    low_stock = supabase.table("products").select("*, categories(name)").in_("status", ["low_stock", "out_of_stock"]).execute()
    redis_client.set(CacheKeys.LOW_STOCK_ALERTS, low_stock.data, 300)
    
    print(f"Warmed dashboard cache with {len(orders.data)} orders")

# Run cache warming on startup
async def warm_all_caches():
    """Warm all caches on startup"""
    await warm_product_cache()
    await warm_dashboard_cache()