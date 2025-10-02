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

    MONNIFY_ENVIRONMENT: str = "sandbox"
    MONNIFY_API_KEY: str
    MONNIFY_SECRET_KEY: str
    MONNIFY_CONTRACT_CODE: str
    MONNIFY_BASE_URL: str = "https://sandbox-api.monnify.com"
    
    # Add this line:
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # 1 hour default
    
    class Config:
        env_file = ".env"

settings = Settings()