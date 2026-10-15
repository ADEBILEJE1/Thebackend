import redis
import json
import time
import logging
from typing import Optional, Any, List
from ..config import settings

logger = logging.getLogger(__name__)

class RedisClient:
    def __init__(self):
        pool = redis.ConnectionPool.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=20,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        self.client = redis.Redis(connection_pool=pool)

    def _safe(self, func, default=None):
        for attempt in range(3):
            try:
                return func()
            except (redis.ConnectionError, redis.TimeoutError) as e:
                logger.warning(f"Redis attempt {attempt+1} failed: {e}")
                time.sleep(0.5 * (attempt + 1))
            except Exception as e:
                logger.error(f"Redis error: {e}")
                return default
        return default

    def set(self, key: str, value: Any, expire: Optional[int] = None):
        if isinstance(value, (dict, list)):
            value = json.dumps(value, default=str)
        def _do():
            if expire:
                self.client.setex(key, expire, value)
            else:
                self.client.set(key, value)
        self._safe(_do)

    def set_nx(self, key: str, value: Any, expire: int) -> bool:
        if isinstance(value, (dict, list)):
            value = json.dumps(value, default=str)
        def _do():
            result = self.client.set(key, value, nx=True, ex=expire)
            return result is True
        return self._safe(_do, default=False)
    
    def get(self, key: str) -> Optional[Any]:
        def _do():
            value = self.client.get(key)
            if value:
                try:
                    return json.loads(value)
                except:
                    return value
            return None
        return self._safe(_do)

    def delete(self, *keys: str):
        if keys:
            self._safe(lambda: self.client.delete(*keys))

    def exists(self, key: str) -> bool:
        return self._safe(lambda: self.client.exists(key) > 0, default=False)

    def delete_pattern(self, pattern: str):
        def _do():
            cursor = 0
            while True:
                cursor, keys = self.client.scan(cursor, match=pattern, count=100)
                if keys:
                    self.client.delete(*keys)
                if cursor == 0:
                    break
        self._safe(_do)

    def keys(self, pattern: str) -> List[str]:
        def _do():
            result = []
            cursor = 0
            while True:
                cursor, keys = self.client.scan(cursor, match=pattern, count=100)
                result.extend(keys)
                if cursor == 0:
                    break
            return result
        return self._safe(_do, default=[])

    def lpush(self, key: str, value: Any):
        if isinstance(value, dict):
            value = json.dumps(value)
        self._safe(lambda: self.client.lpush(key, value))

    def rpop(self, key: str) -> Optional[Any]:
        def _do():
            value = self.client.rpop(key)
            if value:
                try:
                    return json.loads(value)
                except:
                    return value
            return None
        return self._safe(_do)

    def lrange(self, key: str, start: int, stop: int) -> List:
        def _do():
            values = self.client.lrange(key, start, stop)
            return [json.loads(v) if v.startswith('{') else v for v in values]
        return self._safe(_do, default=[])

    def hset(self, name: str, mapping: dict):
        self._safe(lambda: self.client.hset(name, mapping=mapping))

    def hget(self, name: str, key: str) -> Optional[str]:
        return self._safe(lambda: self.client.hget(name, key))

    def hgetall(self, name: str) -> dict:
        return self._safe(lambda: self.client.hgetall(name), default={})

    def hdel(self, name: str, *keys: str):
        if keys:
            self._safe(lambda: self.client.hdel(name, *keys))

    def incr(self, key: str) -> int:
        return self._safe(lambda: self.client.incr(key), default=0)

    def expire(self, key: str, seconds: int):
        self._safe(lambda: self.client.expire(key, seconds))

    def ttl(self, key: str) -> int:
        return self._safe(lambda: self.client.ttl(key), default=-1)

redis_client = RedisClient()