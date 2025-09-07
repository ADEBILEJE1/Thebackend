from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from decimal import Decimal

class StockStatus(str, Enum):
    IN_STOCK = "in_stock"
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"

class Category(BaseModel):
    id: Optional[str] = None
    name: str
    description: Optional[str] = None
    is_active: bool = True
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None

class Product(BaseModel):
    id: Optional[str] = None
    product_template_id: str  # Required reference to template
    supplier_id: Optional[str] = None
    sku: Optional[str] = None  # Unique identifier
    variant_name: Optional[str] = None  # e.g., "Large", "Red", "500ml"
    category_id: str
    price: Decimal
    description: Optional[str] = None
    image_url: Optional[str] = None
    units: int = 0
    low_stock_threshold: int = 10
    is_available: bool = True
    status: Optional[StockStatus] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class StockEntry(BaseModel):
    id: Optional[str] = None
    product_id: str
    quantity: int
    entry_type: str  # "add" or "remove"
    notes: Optional[str] = None
    entered_by: str
    created_at: Optional[datetime] = None

class Supplier(BaseModel):
    id: Optional[str] = None
    name: str
    contact_person: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    is_active: bool = True
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class ProductTemplate(BaseModel):
    id: Optional[str] = None
    name: str  # Unique template name
    description: Optional[str] = None
    default_category_id: Optional[str] = None
    is_active: bool = True
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None