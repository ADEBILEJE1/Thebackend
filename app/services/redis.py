import redis
import json
from typing import Optional, Any, List
from datetime import timedelta
from ..config import settings

class RedisClient:
    def __init__(self):
        self.client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        
    # Basic operations
    def get(self, key: str) -> Optional[Any]:
        value = self.client.get(key)
        if value:
            try:
                return json.loads(value)
            except:
                return value
        return None
    
    def set(self, key: str, value: Any, expire: Optional[int] = None):
        if isinstance(value, (dict, list)):
            value = json.dumps(value)
        if expire:
            self.client.setex(key, expire, value)
        else:
            self.client.set(key, value)
    
    def delete(self, *keys: str):
        if keys:
            self.client.delete(*keys)
    
    def exists(self, key: str) -> bool:
        return self.client.exists(key) > 0
    
    # Pattern operations
    def delete_pattern(self, pattern: str):
        keys = self.client.keys(pattern)
        if keys:
            self.client.delete(*keys)
    
    # List operations for queues
    def lpush(self, key: str, value: Any):
        if isinstance(value, dict):
            value = json.dumps(value)
        self.client.lpush(key, value)
    
    def rpop(self, key: str) -> Optional[Any]:
        value = self.client.rpop(key)
        if value:
            try:
                return json.loads(value)
            except:
                return value
        return None
    
    def lrange(self, key: str, start: int, stop: int) -> List:
        values = self.client.lrange(key, start, stop)
        return [json.loads(v) if v.startswith('{') else v for v in values]
    
    def get(self, key: str) -> Optional[Any]:
        try:
            value = self.client.get(key)
            if value:
                try:
                    return json.loads(value)
                except:
                    return value
            return None
        except redis.ConnectionError:
            return None 
    
    # Hash operations for session
    def hset(self, name: str, mapping: dict):
        self.client.hset(name, mapping=mapping)
    
    def hget(self, name: str, key: str) -> Optional[str]:
        return self.client.hget(name, key)
    
    def hgetall(self, name: str) -> dict:
        return self.client.hgetall(name)
    
    def hdel(self, name: str, *keys: str):
        if keys:
            self.client.hdel(name, *keys)
    
    # Increment for rate limiting
    def incr(self, key: str) -> int:
        return self.client.incr(key)
    
    def expire(self, key: str, seconds: int):
        self.client.expire(key, seconds)
    
    def ttl(self, key: str) -> int:
        return self.client.ttl(key)

redis_client = RedisClient()