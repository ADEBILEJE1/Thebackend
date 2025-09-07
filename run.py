import uvicorn
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
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )