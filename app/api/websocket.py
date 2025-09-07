from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Dict, Set
import json
from datetime import datetime
from ..database import supabase
from ..core.permissions import (
    get_current_user, 
    require_super_admin, 
    require_manager_up, 
    require_staff,
    require_inventory_staff,
    require_sales_staff,
    require_chef_staff
)

router = APIRouter(prefix="/ws", tags=["WebSocket"])

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {
            "sales": set(),
            "kitchen": set(),
            "admin": set()
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
    token: str = Query(...),
    channel: str = Query(...)
):
    # Validate token using Supabase
    try:
        user = supabase.auth.get_user(token)
        if not user:
            await websocket.close(code=1008, reason="Invalid token")
            return
        
        # Get user role
        profile = supabase.table("profiles").select("role").eq("id", user.user.id).execute()
        if not profile.data:
            await websocket.close(code=1008, reason="User not found")
            return
        
        user_role = profile.data[0]["role"]
        
        # Validate channel access
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
    message = {
        "event": event_type,
        "order_id": order_id,
        "data": data,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    if event_type == "new_order":
        await manager.send_to_channel(message, "kitchen")
        await manager.send_to_channel(message, "sales")
    elif event_type == "order_ready":
        await manager.send_to_channel(message, "sales")
    
    await manager.send_to_channel(message, "admin")