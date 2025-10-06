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
    area_id: str
    street_address: str
    is_default: bool = False

class AddressUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    area_id: Optional[str] = None
    street_address: Optional[str] = None
    is_default: Optional[bool] = None

class CartItem(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)
    option_id: Optional[str] = None
    notes: Optional[str] = None

class WebsiteOrder(BaseModel):
    items: List[CartItem]
    delivery_address_id: Optional[str] = None
    special_instructions: Optional[str] = None

class CheckoutRequest(BaseModel):
    orders: List[WebsiteOrder]
    quantity: Optional[int] = None
    customer_email: Optional[str] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    total_amount: Optional[float] = None
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

# class PaymentRequest(BaseModel):
#     orders: List[WebsiteOrder]
#     total_amount: Decimal
#     customer_email: str
#     customer_name: str
#     customer_phone: str

class PaymentRequest(BaseModel):
    orders: List[WebsiteOrder]
    total_amount: Decimal 
    customer_email: str
    customer_name: str 
    customer_phone: str 

    class Config:
        populate_by_name = True

class VirtualAccountResponse(BaseModel):
    account_number: str
    account_name: str
    bank_name: str
    amount: Decimal
    payment_reference: str
    expires_at: datetime

class EmailCheck(BaseModel):
    email: str
    phone: Optional[str] = None
    full_name: Optional[str] = None

class PinVerifyAndAddress(BaseModel):
    email: str
    pin: str
    address_data: Dict[str, Any]

class AddressUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    full_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_default: Optional[bool] = None