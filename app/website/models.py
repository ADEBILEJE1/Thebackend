from pydantic import BaseModel, Field, EmailStr, validator
from typing import List, Optional, Dict, Any
from decimal import Decimal
from datetime import datetime
from enum import Enum

class CustomerCreate(BaseModel):
    email: EmailStr
    full_name: str
    phone: str

class CustomerLogin(BaseModel):
    email: EmailStr

class PinVerification(BaseModel):
    email: EmailStr
    pin: str = Field(min_length=4, max_length=4)

class AddressCreate(BaseModel):
    name: str = Field(max_length=100)
    full_address: str
    latitude: float
    longitude: float
    is_default: bool = False

class CartItem(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)
    notes: Optional[str] = None

class WebsiteOrder(BaseModel):
    items: List[CartItem]
    delivery_address_id: Optional[str] = None
    special_instructions: Optional[str] = None

class CheckoutRequest(BaseModel):
    orders: List[WebsiteOrder]
    customer_details: Optional[CustomerCreate] = None
    new_address: Optional[AddressCreate] = None

class DeliveryCalculation(BaseModel):
    distance_km: float
    fee: Decimal
    estimated_time: str

class OrderSummaryItem(BaseModel):
    product_name: str
    quantity: int
    unit_price: Decimal
    total_price: Decimal

class OrderSummary(BaseModel):
    order_index: int
    items: List[OrderSummaryItem]
    subtotal: Decimal
    delivery_address: str
    delivery_fee: Decimal

class CheckoutSummary(BaseModel):
    orders: List[OrderSummary]
    total_subtotal: Decimal
    total_vat: Decimal
    total_delivery: Decimal
    grand_total: Decimal

class PaymentRequest(BaseModel):
    orders: List[WebsiteOrder]
    total_amount: Decimal
    customer_email: str
    customer_name: str
    customer_phone: str

class VirtualAccountResponse(BaseModel):
    account_number: str
    account_name: str
    bank_name: str
    amount: Decimal
    payment_reference: str
    expires_at: datetime