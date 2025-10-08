from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, date, timedelta
from .core.permissions import require_super_admin
from fastapi import Depends
from .api import auth, inventory, kitchen, websocket, sales, admin
from .config import settings
import time
from .database import supabase, supabase_admin
from .core.permissions import get_current_user
from .website.api import router as website_router

app = FastAPI(title="Leban Street API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
   """Add response time header"""
   start_time = time.time()
   response = await call_next(request)
   process_time = time.time() - start_time
   response.headers["X-Process-Time"] = str(process_time)
   return response



@app.get("/")
async def root():
    return {"message": "Of course its working fine!"}

@app.on_event("startup")
async def startup_event():
   """Initialize Redis connection on startup"""
   from .services.redis import redis_client
   try:
       redis_client.client.ping()
       print("Redis connected successfully")
   except Exception as e:
       print(f"Redis connection failed: {e}")

@app.on_event("shutdown")
async def shutdown_event():
   """Clean up on shutdown"""
   from .services.redis import redis_client
   try:
       redis_client.client.close()
       print("Redis connection closed")
   except:
       pass

app.include_router(auth.router)
app.include_router(inventory.router)
app.include_router(kitchen.router)
app.include_router(websocket.router)
app.include_router(sales.router)
app.include_router(admin.router)
app.include_router(website_router)






@app.get("/health")
async def health_check():
   from .services.redis import redis_client
   
   health = {
       "status": "healthy",
       "timestamp": datetime.utcnow().isoformat(),
       "services": {
           "database": "connected",
           "redis": "disconnected"
       }
   }
   
   # Check Redis
   try:
       redis_client.client.ping()
       health["services"]["redis"] = "connected"
   except:
       pass
   
   return health



@app.get("/debug-supabase")
async def debug_supabase():
    results = {}
    
    # Test regular client
    try:
        regular_test = supabase.table("profiles").select("id").limit(1).execute()
        results["regular_client"] = "success"
    except Exception as e:
        results["regular_client"] = str(e)
    
    # Test admin client
    try:
        admin_test = supabase_admin.table("profiles").select("id").limit(1).execute()
        results["admin_client"] = "success"
    except Exception as e:
        results["admin_client"] = str(e)
    
    # Test admin auth specifically
    try:
        auth_test = supabase_admin.auth.admin.list_users()
        results["admin_auth"] = "success"
    except Exception as e:
        results["admin_auth"] = str(e)
    
    return results


@app.get("/test-auth")
async def test_auth(request: Request, current_user: dict = Depends(get_current_user)):
    return {"user": current_user, "message": "Auth working"}



app = app 