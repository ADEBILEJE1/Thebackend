from pydantic_settings import BaseSettings
import os

class Settings(BaseSettings):
    SUPABASE_URL: str
    SUPABASE_KEY: str
    SUPABASE_SERVICE_KEY: str  # Service role key for admin operations
    
    REDIS_URL: str = "redis://localhost:6379"
    
    SENDGRID_API_KEY: str
    FROM_EMAIL: str
    FRONTEND_URL: str
    
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    MONNIFY_API_KEY: str = os.getenv("MONNIFY_API_KEY")
    MONNIFY_SECRET_KEY: str = os.getenv("MONNIFY_SECRET_KEY")
    MONNIFY_CONTRACT_CODE: str = os.getenv("MONNIFY_CONTRACT_CODE")
    
    # Add this line:
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # 1 hour default
    
    class Config:
        env_file = ".env"

settings = Settings()