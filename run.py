import uvicorn
import os
from app.main import app
from app.utils.cache_warmer import warm_all_caches
import asyncio

async def startup():
    """Run startup tasks"""
    print("Starting Restaurant Management API...")
    
    # Warm caches
    try:
        await warm_all_caches()
    except Exception as e:
        print(f"Cache warming failed: {e}")

if __name__ == "__main__":
    # Run startup tasks
    asyncio.run(startup())
    
    # Start server
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="info"
    )