"""Cleanup utilities for Redis and old data"""
from datetime import datetime, timedelta
from ..services.redis import redis_client
from ..database import supabase

async def cleanup_expired_sessions():
    """Remove expired Redis sessions"""
    pattern = "session:*"
    keys = redis_client.client.keys(pattern)
    
    expired_count = 0
    for key in keys:
        ttl = redis_client.ttl(key)
        if ttl == -2:  # Key doesn't exist
            redis_client.delete(key)
            expired_count += 1
    
    print(f"Cleaned up {expired_count} expired sessions")

async def cleanup_old_activity_logs(days: int = 90):
    """Archive old activity logs"""
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    # Delete old logs
    result = supabase.table("activity_logs").delete().lt("created_at", cutoff_date.isoformat()).execute()
    
    print(f"Deleted activity logs older than {days} days")

async def cleanup_rate_limit_keys():
    """Clean up old rate limit keys"""
    pattern = "rate_limit:*"
    keys = redis_client.client.keys(pattern)
    
    for key in keys:
        ttl = redis_client.ttl(key)
        if ttl == -1:  # No expiry set
            redis_client.delete(key)
    
    print(f"Cleaned up rate limit keys")

# Run cleanup tasks periodically
async def run_cleanup_tasks():
    """Run all cleanup tasks"""
    await cleanup_expired_sessions()
    await cleanup_old_activity_logs()
    await cleanup_rate_limit_keys()