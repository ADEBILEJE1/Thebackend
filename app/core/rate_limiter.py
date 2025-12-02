from fastapi import HTTPException, Request, status
from typing import Optional
from ..services.redis import redis_client

class RateLimiter:
    """Rate limiting using Redis"""
    
    def __init__(self, requests: int = 100, window: int = 60):
        self.requests = requests
        self.window = window
    
    async def check_rate_limit(self, request: Request, user_id: Optional[str] = None):
        """Check if request exceeds rate limit"""
        
        identifier = user_id or request.client.host
        endpoint = request.url.path
        
        key = f"rate_limit:{identifier}:{endpoint}"
        
        try:
           
            current = redis_client.incr(key)
            
            
            if current == 1:
                redis_client.expire(key, self.window)
            
            
            if current > self.requests:
                ttl = redis_client.ttl(key)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded. Try again in {ttl} seconds"
                )
            
            return current
        except HTTPException:
            raise
        except Exception as e:
            
            return 0


default_limiter = RateLimiter(requests=100, window=60)
strict_limiter = RateLimiter(requests=10, window=60)
auth_limiter = RateLimiter(requests=5, window=300) 