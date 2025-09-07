from typing import Optional, Dict
from datetime import datetime, timedelta
from ..services.redis import redis_client
from ..config import settings

class SessionManager:
    """Manage user sessions in Redis"""
    
    @staticmethod
    def create_session(user_id: str, user_data: dict, token: str) -> str:
        """Create a new session"""
        session_key = f"session:{user_id}"
        
        session_data = {
            "user_id": user_id,
            "email": user_data.get("email"),
            "role": user_data.get("role"),
            "token": token,
            "created_at": datetime.utcnow().isoformat(),
            "last_activity": datetime.utcnow().isoformat()
        }
        
        # Store session with expiry
        redis_client.hset(session_key, session_data)
        redis_client.expire(session_key, settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
        
        # Track active sessions
        redis_client.set(f"active_session:{token}", user_id, settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
        
        return session_key
    
    @staticmethod
    def get_session(user_id: str) -> Optional[Dict]:
        """Get session data"""
        session_key = f"session:{user_id}"
        session = redis_client.hgetall(session_key)
        
        if session:
            # Update last activity
            redis_client.hset(session_key, {"last_activity": datetime.utcnow().isoformat()})
            redis_client.expire(session_key, settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
        
        return session
    
    @staticmethod
    def validate_token(token: str) -> Optional[str]:
        """Quick token validation without DB call"""
        user_id = redis_client.get(f"active_session:{token}")
        if user_id:
            # Refresh expiry
            redis_client.expire(f"active_session:{token}", settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
        return user_id
    
    @staticmethod
    def destroy_session(user_id: str, token: Optional[str] = None):
        """Destroy user session"""
        redis_client.delete(f"session:{user_id}")
        if token:
            redis_client.delete(f"active_session:{token}")
    
    @staticmethod
    def get_active_sessions() -> int:
        """Count active sessions"""
        return len(redis_client.client.keys("session:*"))

session_manager = SessionManager()