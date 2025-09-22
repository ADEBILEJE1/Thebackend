from enum import Enum
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel
from decimal import Decimal

class OrderType(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"

class OrderStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PREPARING = "preparing"
    READY = "ready"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class PaymentStatus(str, Enum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"

class OrderItem(BaseModel):
    id: Optional[str] = None
    order_id: Optional[str] = None
    product_id: str
    product_name: str
    quantity: int
    unit_price: Decimal
    total_price: Decimal
    notes: Optional[str] = None

class PaymentMethod(str, Enum):
    CASH = "cash"
    CARD = "card" 
    TRANSFER = "transfer"

class Order(BaseModel):
    id: Optional[str] = None
    order_number: str  # Unique, like "ORD-20250828-001"
    order_type: OrderType
    status: OrderStatus = OrderStatus.PENDING
    payment_status: PaymentStatus = PaymentStatus.PENDING
    payment_method: Optional[PaymentMethod] = None
    
    # Customer info
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    
    batch_id: Optional[str] = None
    batch_created_at: Optional[datetime] = None


    # Amounts
    subtotal: Decimal
    tax: Decimal = Decimal("0")
    total: Decimal
    
    # Tracking
    created_by: Optional[str] = None  # For offline orders
    confirmed_at: Optional[datetime] = None
    preparing_at: Optional[datetime] = None
    ready_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

