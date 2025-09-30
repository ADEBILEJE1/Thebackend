from typing import Optional, Dict
from datetime import datetime, timedelta
from ..services.redis import redis_client
from ..config import settings

class SessionManager:
    """Manage user sessions in Redis"""
    
    @staticmethod
    def create_session(user_id: str, user_data: dict, token: str) -> str:
        
        session_key = f"session:{user_id}:{token[:8]}"  
        
        session_data = {
            "user_id": user_id,
            "email": user_data.get("email"), 
            "role": user_data.get("role"),
            "token": token,
            "created_at": datetime.utcnow().isoformat()
        }
        
        redis_client.hset(session_key, session_data)
        redis_client.expire(session_key, settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
        redis_client.set(f"active_session:{token}", user_id, settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
        
        return session_key
    
    @staticmethod
    def get_session(user_id: str, token: str) -> Optional[Dict]:
        session_key = f"session:{user_id}:{token[:8]}"
        session = redis_client.hgetall(session_key)
        
        if session and "user_id" in session:
            # Convert Redis strings back to proper format
            redis_client.hset(session_key, {"last_activity": datetime.utcnow().isoformat()})
            return session
        
        return None
    
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
    
    @staticmethod
    def destroy_all_user_sessions(user_id: str):
        """Destroy all sessions for a user"""
        pattern = f"session:{user_id}:*"
        sessions = redis_client.client.keys(pattern)
        if sessions:
            redis_client.client.delete(*sessions)
        
        # Also clear active session tokens
        token_pattern = f"active_session:*"
        tokens = redis_client.client.keys(token_pattern)
        for token_key in tokens:
            stored_user_id = redis_client.get(token_key)
            if stored_user_id == user_id:
                redis_client.delete(token_key)

session_manager = SessionManager()

