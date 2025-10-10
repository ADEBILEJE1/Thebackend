from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Dict, Set
import json
from datetime import datetime
from ..database import supabase
from ..services.redis import redis_client

router = APIRouter(prefix="/ws", tags=["WebSocket"])

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {
            "sales": set(),
            "kitchen": set(),
            "admin": set(),
            "website": set()  # ← Added
        }
    
    async def connect(self, websocket: WebSocket, channel: str):
        await websocket.accept()
        self.active_connections[channel].add(websocket)
    
    def disconnect(self, websocket: WebSocket, channel: str):
        self.active_connections[channel].discard(websocket)
    
    async def send_to_channel(self, message: dict, channel: str):
        dead_connections = set()
        for connection in self.active_connections[channel]:
            try:
                await connection.send_json(message)
            except:
                dead_connections.add(connection)
        
        for conn in dead_connections:
            self.active_connections[channel].discard(conn)
    
    async def broadcast(self, message: dict):
        for channel in self.active_connections:
            await self.send_to_channel(message, channel)

manager = ConnectionManager()

@router.websocket("/orders")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(None),
    session_token: str = Query(None),
    channel: str = Query(...)
):
    """WebSocket endpoint for staff and website customers"""
    
    # Website customer authentication
    if channel == "website":
        if not session_token:
            await websocket.close(code=1008, reason="Session token required")
            return
        
        # Validate session token
        session_data = redis_client.get(f"customer_session:{session_token}")
        if not session_data:
            await websocket.close(code=1008, reason="Invalid session")
            return
        
        await manager.connect(websocket, "website")
        
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(websocket, "website")
        return
    
    # Staff authentication (existing code)
    if not token:
        await websocket.close(code=1008, reason="Token required")
        return
    
    try:
        user = supabase.auth.get_user(token)
        if not user:
            await websocket.close(code=1008, reason="Invalid token")
            return
        
        profile = supabase.table("profiles").select("role").eq("id", user.user.id).execute()
        if not profile.data:
            await websocket.close(code=1008, reason="User not found")
            return
        
        user_role = profile.data[0]["role"]
        
        channel_permissions = {
            "sales": ["sales", "manager", "super_admin"],
            "kitchen": ["chef", "manager", "super_admin"],
            "admin": ["manager", "super_admin"]
        }
        
        if user_role not in channel_permissions.get(channel, []):
            await websocket.close(code=1008, reason="Unauthorized channel")
            return
        
        await manager.connect(websocket, channel)
        
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(websocket, channel)
    except Exception as e:
        await websocket.close(code=1008, reason="Authentication failed")

async def notify_order_update(order_id: str, event_type: str, data: dict):
    """Notify relevant channels about order updates"""
    message = {
        "event": event_type,
        "order_id": order_id,
        "data": data,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    # Route to appropriate channels
    if event_type == "new_order":
        await manager.send_to_channel(message, "kitchen")
        await manager.send_to_channel(message, "sales")
    
    elif event_type in ["order_completed", "batch_completed", "order_ready"]:
        await manager.send_to_channel(message, "sales")
        await manager.send_to_channel(message, "website")  # ← Notify customers
    
    elif event_type == "batch_started":
        await manager.send_to_channel(message, "kitchen")
        await manager.send_to_channel(message, "website")  # ← Notify customers
    
    elif event_type == "status_update":
        await manager.send_to_channel(message, "website")  # ← Notify customers
    
    # Always notify admin
    await manager.send_to_channel(message, "admin")