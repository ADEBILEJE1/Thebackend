from pydantic_settings import BaseSettings
import os

class Settings(BaseSettings):
    SUPABASE_URL: str
    SUPABASE_KEY: str
    SUPABASE_SERVICE_KEY: str 
    
    REDIS_URL: str = "redis://localhost:6379"
    
    SENDGRID_API_KEY: str
    FROM_EMAIL: str
    FRONTEND_URL: str
    
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    resend_api_key: str
    resend_app_url: str

    ENVIRONMENT: str = "development"

    MONNIFY_ACCOUNT_NAME: str = "LB" 

    MONNIFY_ENVIRONMENT: str = "sandbox"
    MONNIFY_API_KEY: str
    MONNIFY_SECRET_KEY: str
    MONNIFY_CONTRACT_CODE: str
    MONNIFY_WEBHOOK_IP: str = "35.242.133.146"
    
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    SPREADSHEET_API_KEY: str
    
    
    @property
    def MONNIFY_BASE_URL(self) -> str:
        if self.MONNIFY_ENVIRONMENT == "production":
            return "https://api.monnify.com"
        return "https://sandbox.monnify.com"
    
    class Config:
        env_file = ".env"

settings = Settings()