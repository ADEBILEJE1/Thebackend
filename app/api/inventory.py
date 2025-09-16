from fastapi import APIRouter, HTTPException, status, Depends, Request, Query, UploadFile, File
from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta
from pydantic import BaseModel, Field, EmailStr
from enum  import Enum
from decimal import Decimal
import uuid

from ..models.inventory import StockStatus
from ..core.permissions import (
    get_current_user, 
    require_super_admin, 
    require_manager_up, 
    require_staff,
    require_inventory_staff,
    require_sales_staff,
    require_chef_staff
)
from ..core.cache import cache_key_wrapper, invalidate_product_cache, CacheKeys
from ..core.rate_limiter import default_limiter
from ..services.redis import redis_client
from ..models.user import UserRole
from ..database import supabase
from .inventory_service import InventoryService
from ..database import supabase, supabase_admin
from ..core.activity_logger import log_activity




class CategoryCreate(BaseModel):
    name: str
    description: Optional[str] = None

class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

class ProductCreate(BaseModel):
    name: str = Field(..., max_length=200)
    supplier_id: Optional[str] = None
    sku: Optional[str] = None
    variant_name: Optional[str] = None
    category_id: str
    price: Decimal = Field(gt=0)
    description: Optional[str] = None
    image_url: Optional[str] = None
    units: int = Field(ge=0, default=0)
    low_stock_threshold: int = Field(gt=0, default=10)
    product_type: str = Field(default="main", pattern="^(main|extra)$")
    main_product_id: Optional[str] = None

class ProductUpdate(BaseModel):
    category_id: Optional[str] = None
    price: Optional[Decimal] = Field(gt=0, default=None)
    sku: Optional[str] = None
    supplier: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    low_stock_threshold: Optional[int] = Field(gt=0, default=None)
    product_type: Optional[str] = Field(pattern="^(main|extra)$", default=None)
    main_product_id: Optional[str] = None

class StockUpdate(BaseModel):
    quantity: int = Field(gt=0)
    operation: str = Field(pattern="^(add|remove)$")
    notes: Optional[str] = None

class ProductAvailability(BaseModel):
    is_available: bool

class SKUCodeCreate(BaseModel):
   code: str = Field(max_length=50)
   name: str = Field(max_length=200)
   description: Optional[str] = None
   category_id: Optional[str] = None
   supplier_id: Optional[str] = None
   barcode: Optional[str] = None
   manufacturer_code: Optional[str] = None

class SKUCodeUpdate(BaseModel):
   name: Optional[str] = Field(max_length=200, default=None)
   description: Optional[str] = None
   category_id: Optional[str] = None
   supplier_id: Optional[str] = None
   barcode: Optional[str] = None
   manufacturer_code: Optional[str] = None
   is_active: Optional[bool] = None

class SKUMapping(BaseModel):
   sku_code_id: str
   is_primary: bool = False


class ProductResponse(BaseModel):
    id: str
    name: str
    category: dict
    price: float
    description: Optional[str]
    image_url: Optional[str]
    units: int
    status: str
    is_available: bool
    low_stock_threshold: int
    sku_mappings: List[Dict[str, Any]] = []

class SupplierCreate(BaseModel):
    name: str
    contact_person: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address: Optional[str] = None

class SupplierUpdate(BaseModel):
    name: Optional[str] = None
    contact_person: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    is_active: Optional[bool] = None



class CategoryCreate(BaseModel):
    name: str
    description: Optional[str] = None
    image_url: Optional[str] = None

class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    is_active: Optional[bool] = None

class BannerCreate(BaseModel):
    title: str
    description: Optional[str] = None
    image_url: str
    link_url: Optional[str] = None
    is_active: bool = True
    display_order: int = Field(default=0, ge=0)

class BannerUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    link_url: Optional[str] = None
    is_active: Optional[bool] = None
    display_order: Optional[int] = Field(default=None, ge=0)



class MeasurementUnit(str, Enum):
    KG = "kg"
    LITERS = "liters" 
    PACKS = "packs"
    DOZENS = "dozens"
    UNITS = "units"
    GRAMS = "grams"
    ML = "ml"

class TransactionType(str, Enum):
    PURCHASE = "purchase"
    USAGE = "usage"

class RawMaterialCreate(BaseModel):
    name: str = Field(..., max_length=200)
    sku: Optional[str] = Field(None, max_length=50)
    measurement_unit: MeasurementUnit
    units_per_pack: Optional[int] = Field(None, gt=0)  # Only for packs
    supplier_id: Optional[str] = None
    initial_quantity: Decimal = Field(default=0, ge=0)
    purchase_price: Optional[Decimal] = Field(None, ge=0)
    notes: Optional[str] = None

    def validate_units_per_pack(self):
        if self.measurement_unit == MeasurementUnit.PACKS and not self.units_per_pack:
            raise ValueError("units_per_pack required for pack measurement")
        if self.measurement_unit != MeasurementUnit.PACKS and self.units_per_pack:
            raise ValueError("units_per_pack only allowed for pack measurement")

class RawMaterialUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    sku: Optional[str] = Field(None, max_length=50)
    supplier_id: Optional[str] = None
    units_per_pack: Optional[int] = Field(None, gt=0)
    notes: Optional[str] = None

class MaterialTransaction(BaseModel):
    material_id: str
    transaction_type: TransactionType
    quantity: Decimal = Field(..., gt=0)
    cost: Optional[Decimal] = Field(None, ge=0)
    notes: Optional[str] = None

class DateRangeFilter(BaseModel):
    date_from: Optional[date] = None
    date_to: Optional[date] = None


class ImageType(str, Enum):
    PRODUCT = "product"
    CATEGORY = "category" 
    BANNER = "banner"

class AreaCreate(BaseModel):
    name: str = Field(max_length=100)
    delivery_fee: Decimal = Field(gt=0)
    estimated_time: str = Field(max_length=50)

class AreaUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    delivery_fee: Optional[Decimal] = Field(None, gt=0)
    estimated_time: Optional[str] = Field(None, max_length=50)
    is_active: Optional[bool] = None

router = APIRouter(prefix="/inventory", tags=["Inventory"])

# Categories
@router.post("/categories", response_model=dict)
async def create_category(
    category: CategoryCreate,
    current_user: dict = Depends(require_inventory_staff)
):
    # Check unique name
    existing = supabase.table("categories").select("id").eq("name", category.name).execute()
    if existing.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category name already exists"
        )
    
    category_data = {
        **category.dict(),
        "created_by": current_user["id"]
    }
    
    result = supabase_admin.table("categories").insert(category_data).execute()
    return {"message": "Category created", "data": result.data[0]}

@router.get("/categories", response_model=List[dict])
async def get_categories(
    active_only: bool = True,
    current_user: dict = Depends(get_current_user)
):
    query = supabase_admin.table("categories").select("*")
    if active_only:
        query = query.eq("is_active", True)
    
    result = query.order("name").execute()
    return result.data

@router.patch("/categories/{category_id}")
async def update_category(
    category_id: str,
    update: CategoryUpdate,
    current_user: dict = Depends(require_inventory_staff)
):
    updates = {}
    for k, v in update.dict().items():
        if v is not None:
            updates[k] = v
    
    if updates:
        result = supabase_admin.table("categories").update(updates).eq("id", category_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Category not found")
        
        # Clear website cache when category is updated
        redis_client.delete("website:categories")
    
    return {"message": "Category updated"}







@router.post("/products", response_model=dict)
async def create_product(
   product: ProductCreate,
   current_user: dict = Depends(require_inventory_staff)
):
   

   # Verify category exists
   category = supabase_admin.table("categories").select("id").eq("id", product.category_id).execute()
   if not category.data:
       raise HTTPException(status_code=404, detail="Category not found")
   
   # Verify supplier exists if provided
   if product.supplier_id:
       supplier = supabase.table("suppliers").select("id").eq("id", product.supplier_id).execute()
       if not supplier.data:
           raise HTTPException(status_code=404, detail="Supplier not found")
   
   # Validate product type and main product relationship
   if product.product_type == "extra":
       if not product.main_product_id:
           raise HTTPException(status_code=400, detail="Extra products must have a main product")
       
       main_product = supabase.table("products").select("id, product_type").eq("id", product.main_product_id).execute()
       if not main_product.data:
           raise HTTPException(status_code=404, detail="Main product not found")
       
       if main_product.data[0]["product_type"] != "main":
           raise HTTPException(status_code=400, detail="Can only link to main products")
   
   elif product.product_type == "main" and product.main_product_id:
       raise HTTPException(status_code=400, detail="Main products cannot have a main product reference")
   
   # Check SKU uniqueness if provided
   if product.sku and product.supplier_id:
       existing_sku = supabase.table("products").select("id").eq("sku", product.sku).eq("supplier_id", product.supplier_id).execute()
       if existing_sku.data:
           raise HTTPException(status_code=400, detail="SKU already exists for this supplier")
   
   # Determine stock status
   status = StockStatus.OUT_OF_STOCK
   if product.units > product.low_stock_threshold:
       status = StockStatus.IN_STOCK
   elif product.units > 0:
       status = StockStatus.LOW_STOCK
   
   product_dict = product.dict()
   product_dict["price"] = float(product_dict["price"])
   
   # Use template description if no description provided
   final_description = product.description
   
   product_data = {
       **product_dict,
       "name": product.name,
       "description": product.description,
       "status": status,
       "created_by": current_user["id"],
       "updated_by": current_user["id"]
   }
   
   result = supabase.table("products").insert(product_data).execute()
   
   # Log initial stock if units > 0
   if product.units > 0:
       stock_entry = {
           "product_id": result.data[0]["id"],
           "quantity": product.units,
           "entry_type": "add",
           "notes": "Initial stock",
           "entered_by": current_user["id"]
       }
       supabase_admin.table("stock_entries").insert(stock_entry).execute()
   
   return {"message": "Product created", "data": result.data[0]}




@router.get("/products", response_model=List[dict])
async def get_products(
    request: Request,
    category_id: Optional[str] = None,
    available_only: bool = False,
    include_out_of_stock: bool = True,
    current_user: dict = Depends(require_staff)  # Changed from require_inventory_staff
):
    # Rate limiting
    await default_limiter.check_rate_limit(request, current_user["id"])
    
    # Check cache
    cache_key = f"products:list:{category_id}:{available_only}:{include_out_of_stock}"
    cached = redis_client.get(cache_key)
    if cached:
        return cached
    
    query = supabase.table("products").select("*, categories(*), suppliers(name)")
    
    if category_id:
        query = query.eq("category_id", category_id)
    if available_only:
        query = query.eq("is_available", True)
    if not include_out_of_stock:
        query = query.neq("status", StockStatus.OUT_OF_STOCK)
    
    result = query.order("name").execute()
    
    # Cache for 1 minute
    redis_client.set(cache_key, result.data, 60)
    
    return result.data

@router.get("/products/{product_id}")
async def get_product(
    product_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    # Check cache
    cache_key = CacheKeys.PRODUCT_DETAIL.format(product_id=product_id)
    cached = redis_client.get(cache_key)
    if cached:
        return cached
    
    result = supabase.table("products").select("*, categories(*)").eq("id", product_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Cache for 5 minutes
    redis_client.set(cache_key, result.data[0], 300)
    
    return result.data[0]

@router.patch("/products/{product_id}")
async def update_product(
    product_id: str,
    update: ProductUpdate,
    current_user: dict = Depends(require_inventory_staff)
):
    updates = {}
    for k, v in update.dict().items():
        if v is not None:
            if k == "price":
                updates[k] = float(v)
            else:
                updates[k] = v
    
    if updates:
        updates["updated_by"] = current_user["id"]
        updates["updated_at"] = datetime.utcnow().isoformat()
        
        result = supabase.table("products").update(updates).eq("id", product_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Product not found")
    
    return {"message": "Product updated"}

# Stock Management
@router.post("/products/{product_id}/stock")
async def update_stock(
   product_id: str,
   stock: StockUpdate,
   request: Request,
   current_user: dict = Depends(require_inventory_staff)
):
   # Get current product
   product = supabase.table("products").select("*").eq("id", product_id).execute()
   if not product.data:
       raise HTTPException(status_code=404, detail="Product not found")
   
   current_units = product.data[0]["units"]
   low_threshold = product.data[0]["low_stock_threshold"]
   product_name = product.data[0]["name"]
   
   # Calculate new units
   if stock.operation == "add":
       new_units = current_units + stock.quantity
   else:  # remove
       if stock.quantity > current_units:
           raise HTTPException(
               status_code=status.HTTP_400_BAD_REQUEST,
               detail=f"Cannot remove {stock.quantity} units. Only {current_units} available"
           )
       new_units = current_units - stock.quantity
   
   # Determine new status
   if new_units == 0:
       new_status = StockStatus.OUT_OF_STOCK
   elif new_units <= low_threshold:
       new_status = StockStatus.LOW_STOCK
   else:
       new_status = StockStatus.IN_STOCK
   
   # Update product
   product_update = {
       "units": new_units,
       "status": new_status,
       "updated_by": current_user["id"],
       "updated_at": datetime.utcnow().isoformat()
   }
   
   supabase.table("products").update(product_update).eq("id", product_id).execute()
   
   # Log stock entry
   stock_entry = {
       "product_id": product_id,
       "quantity": stock.quantity,
       "entry_type": stock.operation,
       "notes": stock.notes,
       "entered_by": current_user["id"]
   }
   
   supabase_admin.table("stock_entries").insert(stock_entry).execute()
   
   # Invalidate cache
   invalidate_product_cache(product_id)
   
   # Update low stock alerts cache if needed
   if new_status in [StockStatus.LOW_STOCK, StockStatus.OUT_OF_STOCK]:
       redis_client.delete(CacheKeys.LOW_STOCK_ALERTS)
   
   # Enhanced activity logging
   await log_activity(
       current_user["id"], current_user["email"], current_user["role"],
       f"stock_{stock.operation}", "product", product_id,
       {
           "product_name": product_name,
           "quantity": stock.quantity,
           "previous_units": current_units,
           "new_units": new_units,
           "new_status": new_status,
           "notes": stock.notes,
           "operation": stock.operation
       },
       request
   )
   
   return {
       "message": f"Stock {stock.operation}ed successfully",
       "current_units": new_units,
       "status": new_status
   }

# Availability Toggle (for Sales staff)
@router.patch("/products/{product_id}/availability")
async def toggle_availability(
    product_id: str,
    availability: ProductAvailability,
    current_user: dict = Depends(require_inventory_staff)
):
    update = {
        "is_available": availability.is_available,
        "updated_by": current_user["id"],
        "updated_at": datetime.utcnow().isoformat()
    }
    
    result = supabase_admin.table("products").update(update).eq("id", product_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Product not found")
    
    return {"message": f"Product {'enabled' if availability.is_available else 'disabled'} for website"}

# Stock History
@router.get("/products/{product_id}/history")
async def get_stock_history(
    product_id: str,
    limit: int = 50,
    current_user: dict = Depends(require_inventory_staff)
):
    result = supabase_admin.table("stock_entries").select("*, profiles(email)").eq("product_id", product_id).order("created_at", desc=True).limit(limit).execute()
    return result.data





# Low Stock Alert
@router.get("/alerts/low-stock")
async def get_low_stock_items(
    request: Request,
    current_user: dict = Depends(require_inventory_staff)
):
    # Check cache
    cached = redis_client.get(CacheKeys.LOW_STOCK_ALERTS)
    if cached:
        return cached
    
    result = supabase.table("products").select("*, categories(name)").in_("status", [StockStatus.LOW_STOCK.value, StockStatus.OUT_OF_STOCK.value]).order("units").execute()
    
    # Cache for 5 minutes
    redis_client.set(CacheKeys.LOW_STOCK_ALERTS, result.data, 300)
    
    return result.data



@router.get("/main-products-dropdown")
async def get_main_products(
    current_user: dict = Depends(require_inventory_staff)
):
    """Get main products dropdown   for linking extra products"""
    result = supabase.table("products").select("id, name, price").eq("product_type", "main").eq("is_available", True).order("name").execute()
    return result.data

@router.get("/products/{product_id}/extras")
async def get_product_extras(
    product_id: str,
    current_user: dict = Depends(require_staff)
):
    """Get extra products linked to a main product"""
    result = supabase.table("products").select("*").eq("main_product_id", product_id).eq("is_available", True).execute()
    return result.data



@router.delete("/products/{product_id}")
async def delete_product(
    product_id: str,
    current_user: dict = Depends(require_inventory_staff)
):
    # Check if product has order history
    orders = supabase_admin.table("order_items").select("id").eq("product_id", product_id).execute()
    if orders.data:
        raise HTTPException(status_code=400, detail="Cannot delete product with order history")
    
    result = supabase_admin.table("products").delete().eq("id", product_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Clear cache
    invalidate_product_cache(product_id)
    
    return {"message": "Product deleted"}


@router.delete("/categories/{category_id}")
async def delete_category(
    category_id: str,
    current_user: dict = Depends(require_inventory_staff)
):
    # Check if category has products
    products = supabase_admin.table("products").select("id").eq("category_id", category_id).execute()
    if products.data:
        raise HTTPException(status_code=400, detail="Cannot delete category with existing products")
    
    
    result = supabase_admin.table("categories").delete().eq("id", category_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Category not found")
    
    return {"message": "Category deleted"}


@router.get("/dashboard")
async def get_inventory_dashboard(
    request: Request,
    current_user: dict = Depends(require_inventory_staff)
):
    """Get comprehensive inventory dashboard overview"""
    # Rate limiting
    await default_limiter.check_rate_limit(request, current_user["id"])
    
    dashboard_data = await InventoryService.get_dashboard_overview()
    
    # Log activity
    from ..core.activity_logger import log_activity
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "view", "inventory_dashboard", None, None, request
    )
    
    return dashboard_data

# Stock Movement Analytics
@router.get("/analytics/movement")
async def get_stock_movement_analytics(
    request: Request,
    days: int = 30,
    current_user: dict = Depends(require_inventory_staff)
):
    """Get stock movement trends and analytics"""
    if days > 365:  # Limit to 1 year maximum
        raise HTTPException(status_code=400, detail="Maximum 365 days allowed")
    
    movement_data = await InventoryService.get_stock_movement_trends(days)
    return movement_data

# Inventory Valuation
@router.get("/analytics/valuation")
async def get_inventory_valuation(
    request: Request,
    current_user: dict = Depends(require_inventory_staff)
):
    """Get detailed inventory valuation by category"""
    valuation_data = await InventoryService.get_inventory_valuation()
    return valuation_data

# Bulk Stock Operations
@router.post("/bulk-operations")
async def bulk_stock_operations(
    updates: List[Dict[str, Any]],
    request: Request,
    current_user: dict = Depends(require_inventory_staff)
):
    """Perform bulk stock updates"""
    # Validate input
    if len(updates) > 100:  # Limit bulk operations
        raise HTTPException(status_code=400, detail="Maximum 100 operations per bulk update")
    
    required_fields = ["product_id", "quantity", "operation"]
    for update in updates:
        for field in required_fields:
            if field not in update:
                raise HTTPException(status_code=400, detail=f"Missing required field: {field}")
        
        if update["operation"] not in ["add", "remove"]:
            raise HTTPException(status_code=400, detail="Operation must be 'add' or 'remove'")
        
        if not isinstance(update["quantity"], int) or update["quantity"] <= 0:
            raise HTTPException(status_code=400, detail="Quantity must be a positive integer")
    
    results = await InventoryService.bulk_stock_update(updates, current_user["id"])
    
    # Log activity
    from ..core.activity_logger import log_activity
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "bulk_update", "inventory", None, 
        {
            "total_operations": len(updates),
            "successful": len(results["successful"]),
            "failed": len(results["failed"])
        }, 
        request
    )
    
    return results



# Suppliers
@router.post("/suppliers", response_model=dict)
async def create_supplier(
    supplier: SupplierCreate,
    current_user: dict = Depends(require_inventory_staff)
):
    # Check unique name
    existing = supabase.table("suppliers").select("id").eq("name", supplier.name).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Supplier name already exists")
    
    supplier_data = {**supplier.dict(), "created_by": current_user["id"]}
    result = supabase.table("suppliers").insert(supplier_data).execute()
    return {"message": "Supplier created", "data": result.data[0]}

@router.get("/suppliers", response_model=List[dict])
async def get_suppliers(
    active_only: bool = True,
    search: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    query = supabase.table("suppliers").select("*")
    if active_only:
        query = query.eq("is_active", True)
    if search:
        query = query.ilike("name", f"%{search}%")
    
    result = query.order("name").execute()
    return result.data






# Reorder Suggestions
@router.get("/reorder-suggestions")
async def get_reorder_suggestions(
    request: Request,
    threshold_multiplier: float = 1.5,
    current_user: dict = Depends(require_inventory_staff)
):
    """Get intelligent reorder suggestions based on sales velocity"""
    if threshold_multiplier < 1.0 or threshold_multiplier > 5.0:
        raise HTTPException(status_code=400, detail="Threshold multiplier must be between 1.0 and 5.0")
    
    suggestions = await InventoryService.get_reorder_suggestions(threshold_multiplier)
    return suggestions

# Product Performance Analytics
@router.get("/performance")
async def get_product_performance(
    request: Request,
    days: int = 30,
    current_user: dict = Depends(require_inventory_staff)
):
    """Get product performance analytics based on sales"""
    if days > 365:
        raise HTTPException(status_code=400, detail="Maximum 365 days allowed")
    
    performance_data = await InventoryService.get_product_performance(days)
    return performance_data

# Wastage Analysis
@router.get("/analytics/wastage")
async def get_wastage_analysis(
    request: Request,
    days: int = 30,
    current_user: dict = Depends(require_manager_up)  # Manager+ only for wastage data
):
    """Get wastage and expired items analysis"""
    if days > 365:
        raise HTTPException(status_code=400, detail="Maximum 365 days allowed")
    
    wastage_data = await InventoryService.get_wastage_analysis(days)
    
    # Log activity
    from ..core.activity_logger import log_activity
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "view", "wastage_analysis", None, {"days": days}, request
    )
    
    return wastage_data

# Enhanced Low Stock Alerts with Predictions
@router.get("/alerts/enhanced")
async def get_enhanced_alerts(
    request: Request,
    include_predictions: bool = True,
    current_user: dict = Depends(require_inventory_staff)
):
    """Get enhanced low stock alerts with sales velocity predictions"""
    # Check cache first
    cache_key = f"inventory:alerts:enhanced:{include_predictions}"
    cached = redis_client.get(cache_key)
    if cached:
        return cached
    
    # Get standard low stock items
    standard_alerts = supabase.table("products").select("*, categories(name)").in_(
        "status", [StockStatus.LOW_STOCK, StockStatus.OUT_OF_STOCK]
    ).order("units").execute()
    
    alerts_data = {
        "standard_alerts": standard_alerts.data,
        "predictions": []
    }
    
    if include_predictions:
        # Get sales velocity for predictions
        seven_days_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        
        for product in standard_alerts.data:
            # Get recent sales
            order_items = supabase.table("order_items").select("quantity, orders!inner(created_at)").eq("product_id", product["id"]).gte("orders.created_at", seven_days_ago).execute()
            
            total_sold = sum(item["quantity"] for item in order_items.data)
            daily_velocity = total_sold / 7
            
            if daily_velocity > 0:
                days_remaining = product["units"] / daily_velocity
                alerts_data["predictions"].append({
                    "product_id": product["id"],
                    "product_name": product["name"],
                    "current_stock": product["units"],
                    "daily_velocity": round(daily_velocity, 2),
                    "estimated_days_remaining": round(days_remaining, 1),
                    "urgency": "critical" if days_remaining < 3 else ("high" if days_remaining < 7 else "medium")
                })
    
    # Sort predictions by urgency
    alerts_data["predictions"].sort(key=lambda x: x["estimated_days_remaining"])
    
    # Cache for 5 minutes
    redis_client.set(cache_key, alerts_data, 300)
    
    return alerts_data

# Category Performance Comparison
@router.get("/analytics/category-comparison")
async def get_category_performance_comparison(
    request: Request,
    days: int = 30,
    current_user: dict = Depends(require_inventory_staff)
):
    """Compare performance across categories"""
    if days > 365:
        raise HTTPException(status_code=400, detail="Maximum 365 days allowed")
    
    # Get all categories
    categories = supabase.table("categories").select("*").eq("is_active", True).execute()
    
    comparison_data = []
    start_date = (datetime.utcnow() - timedelta(days=days)).isoformat()
    
    for category in categories.data:
        # Get products in category
        products = supabase.table("products").select("id, name, price, units").eq("category_id", category["id"]).execute()
        
        if not products.data:
            continue
        
        # Get sales data for products in this category
        product_ids = [p["id"] for p in products.data]
        order_items = supabase.table("order_items").select("quantity, total_price, orders!inner(created_at)").in_("product_id", product_ids).gte("orders.created_at", start_date).execute()
        
        # Calculate metrics
        total_products = len(products.data)
        current_stock_value = sum(float(p["price"]) * p["units"] for p in products.data)
        total_units_sold = sum(item["quantity"] for item in order_items.data)
        total_revenue = sum(float(item["total_price"]) for item in order_items.data)
        
        # Stock turnover ratio
        avg_stock_value = current_stock_value  # Simplified - would need historical data for accuracy
        turnover_ratio = total_revenue / avg_stock_value if avg_stock_value > 0 else 0
        
        comparison_data.append({
            "category_id": category["id"],
            "category_name": category["name"],
            "total_products": total_products,
            "current_stock_value": round(current_stock_value, 2),
            "units_sold": total_units_sold,
            "revenue_generated": round(total_revenue, 2),
            "turnover_ratio": round(turnover_ratio, 2),
            "revenue_per_product": round(total_revenue / total_products, 2) if total_products > 0 else 0,
            "average_daily_sales": round(total_units_sold / days, 2)
        })
    
    # Sort by revenue
    comparison_data.sort(key=lambda x: x["revenue_generated"], reverse=True)
    
    return {
        "period": {"days": days},
        "category_comparison": comparison_data,
        "summary": {
            "total_categories": len(comparison_data),
            "total_stock_value": sum(c["current_stock_value"] for c in comparison_data),
            "total_revenue": sum(c["revenue_generated"] for c in comparison_data),
            "best_performing_category": comparison_data[0]["category_name"] if comparison_data else None,
            "highest_turnover": max(comparison_data, key=lambda x: x["turnover_ratio"])["category_name"] if comparison_data else None
        }
    }

# Stock Optimization Recommendations
@router.get("/optimization")
async def get_stock_optimization(
    request: Request,
    current_user: dict = Depends(require_manager_up)  # Manager+ only
):
    """Get advanced stock optimization recommendations"""
    cache_key = "inventory:optimization"
    cached = redis_client.get(cache_key)
    if cached:
        return cached
    
    # Get reorder suggestions
    reorder_suggestions = await InventoryService.get_reorder_suggestions()
    
    # Get performance data
    performance_data = await InventoryService.get_product_performance(30)
    
    # Get current inventory value
    valuation_data = await InventoryService.get_inventory_valuation()
    
    # Generate optimization recommendations
    recommendations = []
    
    # Overstock recommendations (products with high stock but low sales)
    low_performers = [p for p in performance_data["top_performers"]["by_quantity"] if p["daily_average_sales"] < 0.5]
    
    for product in low_performers[-5:]:  # Bottom 5 performers
        recommendations.append({
            "type": "reduce_stock",
            "priority": "medium",
            "product_name": product["product_name"],
            "reason": f"Low sales velocity ({product['daily_average_sales']} units/day)",
            "suggested_action": "Reduce reorder quantity or run promotion"
        })
    
    # High opportunity products (high sales but frequent stockouts)
    reorder_high_priority = [s for s in reorder_suggestions["suggestions"] if s["urgency_score"] > 80]
    
    for suggestion in reorder_high_priority[:5]:
        recommendations.append({
            "type": "increase_stock",
            "priority": "high",
            "product_name": suggestion["product_name"],
            "reason": f"High demand with frequent stockouts (urgency: {suggestion['urgency_score']})",
            "suggested_action": f"Increase stock by {suggestion['suggested_quantity']} units"
        })
    
    # Category balance recommendations
    category_performance = performance_data["category_performance"]
    if len(category_performance) > 1:
        top_category = category_performance[0]
        for category in category_performance[1:3]:  # Next 2 categories
            if category["total_revenue"] < top_category["total_revenue"] * 0.3:
                recommendations.append({
                    "type": "category_rebalance",
                    "priority": "low",
                    "category_name": category["category"],
                    "reason": "Underperforming category compared to top performer",
                    "suggested_action": "Review product mix or marketing for this category"
                })
    
    optimization_data = {
        "summary": {
            "total_inventory_value": valuation_data["total_inventory_value"],
            "products_needing_reorder": reorder_suggestions["summary"]["total_products_needing_reorder"],
            "high_priority_items": reorder_suggestions["summary"]["high_priority_count"],
            "optimization_opportunities": len(recommendations)
        },
        "recommendations": recommendations,
        "quick_actions": {
            "urgent_reorders": reorder_high_priority[:3],
            "overstock_items": low_performers[-3:] if low_performers else [],
            "total_reorder_cost": reorder_suggestions["summary"]["total_estimated_cost"]
        },
        "timestamp": datetime.utcnow().isoformat()
    }
    
    # Cache for 10 minutes
    redis_client.set(cache_key, optimization_data, 600)
    
    return optimization_data


@router.get("/analytics/staff/{staff_id}")
async def get_inventory_staff_analytics(
    staff_id: str,
    request: Request,
    days: int = 30,
    current_user: dict = Depends(require_manager_up)
):
    """Get individual inventory staff analytics"""
    analytics_data = await InventoryService.get_individual_inventory_analytics(staff_id, days)
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "view", "inventory_staff_analytics", staff_id, {"days": days}, request
    )
    
    return analytics_data

@router.get("/analytics/all-inventory-staff")
async def get_all_inventory_staff_analytics(
    request: Request,
    days: int = 30,
    current_user: dict = Depends(require_manager_up)
):
    """Get analytics for all inventory staff"""
    staff_result = supabase.table("profiles").select("*").eq("role", "inventory_staff").eq("is_active", True).execute()
    
    all_staff_analytics = []
    for staff in staff_result.data:
        staff_analytics = await InventoryService.get_individual_inventory_analytics(staff["id"], days)
        staff_analytics["staff_email"] = staff["email"]
        all_staff_analytics.append(staff_analytics)
    
    return {
        "period": {"days": days},
        "staff_analytics": all_staff_analytics,
        "team_summary": {
            "total_stock_entries": sum(s["stock_management"]["total_entries"] for s in all_staff_analytics),
            "total_units_managed": sum(s["stock_management"]["units_added"] + s["stock_management"]["units_removed"] for s in all_staff_analytics),
            "most_productive": max(all_staff_analytics, key=lambda x: x["stock_management"]["total_entries"])["staff_email"] if all_staff_analytics else None
        }
    }

@router.post("/sku-codes", response_model=dict)
async def create_sku_code(
   sku: SKUCodeCreate,
   current_user: dict = Depends(require_inventory_staff)
):
   # Check unique code
   existing = supabase.table("sku_codes").select("id").eq("code", sku.code).execute()
   if existing.data:
       raise HTTPException(status_code=400, detail="SKU code already exists")
   
   # Verify category if provided
   if sku.category_id:
       category = supabase.table("categories").select("id").eq("id", sku.category_id).execute()
       if not category.data:
           raise HTTPException(status_code=404, detail="Category not found")
   
   # Verify supplier if provided
   if sku.supplier_id:
       supplier = supabase.table("suppliers").select("id").eq("id", sku.supplier_id).execute()
       if not supplier.data:
           raise HTTPException(status_code=404, detail="Supplier not found")
   
   sku_data = {**sku.dict(), "created_by": current_user["id"]}
   result = supabase.table("sku_codes").insert(sku_data).execute()
   return {"message": "SKU code created", "data": result.data[0]}

@router.get("/sku-codes", response_model=List[dict])
async def get_sku_codes(
   active_only: bool = True,
   category_id: Optional[str] = None,
   supplier_id: Optional[str] = None,
   search: Optional[str] = None,
   current_user: dict = Depends(require_staff)
):
   query = supabase.table("sku_codes").select("*, categories(name), suppliers(name)")
   
   if active_only:
       query = query.eq("is_active", True)
   if category_id:
       query = query.eq("category_id", category_id)
   if supplier_id:
       query = query.eq("supplier_id", supplier_id)
   if search:
       query = query.or_(f"code.ilike.%{search}%,name.ilike.%{search}%")
   
   result = query.order("code").execute()
   return result.data

@router.patch("/sku-codes/{sku_id}")
async def update_sku_code(
   sku_id: str,
   update: SKUCodeUpdate,
   current_user: dict = Depends(require_inventory_staff)
):
   updates = {k: v for k, v in update.dict().items() if v is not None}
   
   if updates:
       updates["updated_at"] = datetime.utcnow().isoformat()
       result = supabase.table("sku_codes").update(updates).eq("id", sku_id).execute()
       if not result.data:
           raise HTTPException(status_code=404, detail="SKU code not found")
   
   return {"message": "SKU code updated"}

@router.delete("/sku-codes/{sku_id}")
async def deactivate_sku_code(
   sku_id: str,
   current_user: dict = Depends(require_inventory_staff)
):
   result = supabase.table("sku_codes").update({"is_active": False}).eq("id", sku_id).execute()
   if not result.data:
       raise HTTPException(status_code=404, detail="SKU code not found")
   
   return {"message": "SKU code deactivated"}

# Product-SKU Mapping
@router.post("/products/{product_id}/map-sku")
async def map_sku_to_product(
   product_id: str,
   mapping: SKUMapping,
   current_user: dict = Depends(require_inventory_staff)
):
   # Verify product exists
   product = supabase.table("products").select("id").eq("id", product_id).execute()
   if not product.data:
       raise HTTPException(status_code=404, detail="Product not found")
   
   # Verify SKU exists
   sku = supabase.table("sku_codes").select("id").eq("id", mapping.sku_code_id).execute()
   if not sku.data:
       raise HTTPException(status_code=404, detail="SKU code not found")
   
   # Check if mapping already exists
   existing = supabase.table("product_sku_mappings").select("id").eq("product_id", product_id).eq("sku_code_id", mapping.sku_code_id).execute()
   if existing.data:
       raise HTTPException(status_code=400, detail="SKU already mapped to this product")
   
   # If setting as primary, remove primary flag from other mappings
   if mapping.is_primary:
       supabase.table("product_sku_mappings").update({"is_primary": False}).eq("product_id", product_id).execute()
   
   mapping_data = {
       "product_id": product_id,
       "sku_code_id": mapping.sku_code_id,
       "is_primary": mapping.is_primary,
       "mapped_by": current_user["id"]
   }
   
   result = supabase.table("product_sku_mappings").insert(mapping_data).execute()
   return {"message": "SKU mapped to product", "data": result.data[0]}

@router.delete("/products/{product_id}/unmap-sku/{sku_id}")
async def unmap_sku_from_product(
   product_id: str,
   sku_id: str,
   current_user: dict = Depends(require_inventory_staff)
):
   result = supabase.table("product_sku_mappings").delete().eq("product_id", product_id).eq("sku_code_id", sku_id).execute()
   if not result.data:
       raise HTTPException(status_code=404, detail="Mapping not found")
   
   return {"message": "SKU unmapped from product"}

@router.get("/products/{product_id}/skus")
async def get_product_skus(
   product_id: str,
   current_user: dict = Depends(require_staff)
):
   result = supabase.table("product_sku_mappings").select(
       "*, sku_codes(code, name, description, barcode)"
   ).eq("product_id", product_id).execute()
   
   return result.data

@router.get("/sku-codes/{sku_id}/products")
async def get_sku_products(
   sku_id: str,
   current_user: dict = Depends(require_staff)
):
   result = supabase.table("product_sku_mappings").select(
       "*, products(id, name, price, units, status)"
   ).eq("sku_code_id", sku_id).execute()
   
   return result.data



@router.post("/upload-image")
async def upload_image(
    file: UploadFile = File(...),
    image_type: ImageType = ImageType.PRODUCT,
    current_user: dict = Depends(require_inventory_staff)
):
    # Type-specific validation
    size_limits = {
        ImageType.PRODUCT: 5 * 1024 * 1024,   # 5MB
        ImageType.CATEGORY: 3 * 1024 * 1024,  # 3MB  
        ImageType.BANNER: 10 * 1024 * 1024    # 10MB
    }
    
    # Validate file type
    if file.content_type not in ["image/jpeg", "image/jpg", "image/png", "image/webp"]:
        raise HTTPException(status_code=400, detail="Invalid file type")
    
    # Validate file size
    if file.size > size_limits[image_type]:
        max_mb = size_limits[image_type] / (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"File too large. Max {max_mb}MB for {image_type}")
    
    # Generate unique filename
    file_extension = file.filename.split('.')[-1].lower()
    filename = f"{uuid.uuid4()}.{file_extension}"
    
    # Upload to Supabase Storage
    try:
        bucket_name = f"{image_type.value}-images"
        
        supabase_admin.storage.from_(bucket_name).upload(
            filename, 
            file.file.read(),
            {"content-type": file.content_type}
        )
        
        
        base_url = supabase_admin.supabase_url
        image_url = f"{base_url}/storage/v1/object/public/{bucket_name}/{filename}"

        
        await log_activity(
            current_user["id"], current_user["email"], current_user["role"],
            "upload", f"{image_type.value}_image", None, 
            {"filename": filename, "size": file.size}, 
            None
        )
        
        return {
            "image_url": image_url,
            "filename": filename,
            "type": image_type.value
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


# Banner Management
@router.post("/banners", response_model=dict)
async def create_banner(
    banner: BannerCreate,
    current_user: dict = Depends(require_inventory_staff)
):
    banner_data = {
        **banner.dict(),
        "created_by": current_user["id"]
    }
    
    result = supabase.table("banners").insert(banner_data).execute()
    return {"message": "Banner created", "data": result.data[0]}

@router.get("/banners", response_model=List[dict])
async def get_banners(
    active_only: bool = False,
    current_user: dict = Depends(require_inventory_staff)
):
    query = supabase.table("banners").select("*")
    if active_only:
        query = query.eq("is_active", True)
    
    result = query.order("display_order", desc=False).order("created_at", desc=True).execute()
    return result.data

@router.patch("/banners/{banner_id}")
async def update_banner(
    banner_id: str,
    update: BannerUpdate,
    current_user: dict = Depends(require_inventory_staff)
):
    updates = {k: v for k, v in update.dict().items() if v is not None}
    
    if updates:
        updates["updated_at"] = datetime.utcnow().isoformat()
        result = supabase.table("banners").update(updates).eq("id", banner_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Banner not found")
    
    # Clear website cache when banner is updated
    redis_client.delete("website:banners")
    
    return {"message": "Banner updated"}

@router.delete("/banners/{banner_id}")
async def delete_banner(
    banner_id: str,
    current_user: dict = Depends(require_inventory_staff)
):
    result = supabase.table("banners").delete().eq("id", banner_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Banner not found")
    
    return {"message": "Banner deleted"}
















@router.post("/create_raw-materials", response_model=dict)
async def create_raw_material(
    material: RawMaterialCreate,
    request: Request,
    current_user: dict = Depends(require_inventory_staff)
):
    """Create new raw material"""
    material.validate_units_per_pack()
    
    # Check unique name
    existing = supabase.table("raw_materials").select("id").eq("name", material.name).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Material name already exists")
    
    # Check SKU uniqueness if provided
    if material.sku:
        existing_sku = supabase.table("raw_materials").select("id").eq("sku", material.sku).execute()
        if existing_sku.data:
            raise HTTPException(status_code=400, detail="SKU already exists")
    
    # Verify supplier if provided
    if material.supplier_id:
        supplier = supabase.table("suppliers").select("id").eq("name", material.supplier_id).execute()
        if not supplier.data:
            raise HTTPException(status_code=404, detail="Supplier not found")
    
    material_data = {
        **material.dict(exclude={"initial_quantity"}),
        "current_quantity": float(material.initial_quantity),
        "purchase_price": float(material.purchase_price) if material.purchase_price else None,
        "created_by": current_user["id"]
    }
    
    result = supabase.table("raw_materials").insert(material_data).execute()
    material_id = result.data[0]["id"]
    
    # Log initial quantity if > 0
    if material.initial_quantity > 0:
        transaction_data = {
            "material_id": material_id,
            "transaction_type": TransactionType.PURCHASE,
            "quantity": float(material.initial_quantity),
            "remaining_after": float(material.initial_quantity),
            "cost": float(material.purchase_price) if material.purchase_price else None,
            "notes": "Initial stock",
            "created_by": current_user["id"]
        }
        supabase.table("raw_material_transactions").insert(transaction_data).execute()
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "create", "raw_material", material_id, 
        {"name": material.name, "unit": material.measurement_unit}, 
        request
    )
    
    return {"message": "Raw material created", "data": result.data[0]}

@router.get("/get_raw_materials", response_model=List[dict])
async def get_raw_materials(
    request: Request,
    search: Optional[str] = None,
    measurement_unit: Optional[MeasurementUnit] = None,
    supplier_id: Optional[str] = None,
    low_stock_only: bool = False,
    current_user: dict = Depends(get_current_user)
):
    """Get raw materials with filtering"""
    cache_key = f"raw_materials:list:{search}:{measurement_unit}:{supplier_id}:{low_stock_only}"
    cached = redis_client.get(cache_key)
    if cached:
        return cached
    
    query = supabase.table("raw_materials").select("*, suppliers(name)")
    
    if search:
        query = query.or_(f"name.ilike.%{search}%,sku.ilike.%{search}%")
    
    if measurement_unit:
        query = query.eq("measurement_unit", measurement_unit)
    
    if supplier_id:
        query = query.eq("supplier_id", supplier_id)
    
    if low_stock_only:
        query = query.lte("current_quantity", 10)  # Configurable threshold
    
    result = query.order("name").execute()
    
    # Add stock status
    for material in result.data:
        qty = material["current_quantity"]
        if qty <= 0:
            material["stock_status"] = "out_of_stock"
        elif qty <= 10:  # Configurable
            material["stock_status"] = "low_stock"
        else:
            material["stock_status"] = "in_stock"
    
    redis_client.set(cache_key, result.data, 120)
    return result.data




@router.post("/transactions", response_model=dict)
async def create_transaction(
    transaction: MaterialTransaction,
    request: Request,
    current_user: dict = Depends(require_inventory_staff)
):
    """Record purchase or usage transaction"""
    # Get current material
    material = supabase.table("raw_materials").select("*").eq("id", transaction.material_id).execute()
    if not material.data:
        raise HTTPException(status_code=404, detail="Raw material not found")
    
    current_qty = Decimal(str(material.data[0]["current_quantity"]))
    
    # Calculate new quantity
    if transaction.transaction_type == TransactionType.PURCHASE:
        new_qty = current_qty + transaction.quantity
    else:  # USAGE
        if transaction.quantity > current_qty:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot use {transaction.quantity} {material.data[0]['measurement_unit']}. Only {current_qty} available"
            )
        new_qty = current_qty - transaction.quantity
    
    # Update material quantity
    supabase.table("raw_materials").update({
        "current_quantity": float(new_qty),
        "updated_at": datetime.utcnow().isoformat()
    }).eq("id", transaction.material_id).execute()
    
    # Record transaction
    transaction_data = {
        **transaction.dict(),
        "quantity": float(transaction.quantity),
        "remaining_after": float(new_qty),
        "cost": float(transaction.cost) if transaction.cost else None,
        "created_by": current_user["id"]
    }
    
    result = supabase.table("raw_material_transactions").insert(transaction_data).execute()
    
    # Clear cache
    redis_client.delete_pattern("raw_materials:*")
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        f"material_{transaction.transaction_type}", "raw_material", transaction.material_id,
        {
            "quantity": float(transaction.quantity),
            "remaining": float(new_qty),
            "material_name": material.data[0]["name"]
        },
        request
    )
    
    return {
        "message": f"Transaction recorded successfully",
        "remaining_quantity": float(new_qty),
        "transaction": result.data[0]
    }

@router.get("/{material_id}/transactions")
async def get_material_transactions(
    material_id: str,
    request: Request,
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    transaction_type: Optional[TransactionType] = Query(None),
    limit: int = Query(50, le=500),
    current_user: dict = Depends(get_current_user)
):
    """Get transaction history for specific material"""
    query = supabase.table("raw_material_transactions").select(
        "*, profiles(email)"
    ).eq("material_id", material_id)
    
    if date_from:
        query = query.gte("created_at", date_from.isoformat())
    
    if date_to:
        query = query.lte("created_at", f"{date_to.isoformat()}T23:59:59")
    
    if transaction_type:
        query = query.eq("transaction_type", transaction_type)
    
    result = query.order("created_at", desc=True).limit(limit).execute()
    return result.data

@router.get("/analytics/usage-summary")
async def get_usage_summary(
    request: Request,
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    material_id: Optional[str] = Query(None),
    current_user: dict = Depends(require_inventory_staff)
):
    """Get usage analytics with filtering"""
    if not date_from:
        date_from = date.today() - timedelta(days=30)
    if not date_to:
        date_to = date.today()
    
    # Build query
    query = supabase.table("raw_material_transactions").select(
        "*, raw_materials!inner(name, measurement_unit)"
    ).gte("created_at", date_from.isoformat()).lte("created_at", f"{date_to.isoformat()}T23:59:59")
    
    if material_id:
        query = query.eq("material_id", material_id)
    
    transactions = query.execute().data
    
    # Aggregate data
    usage_summary = {}
    purchase_summary = {}
    daily_usage = {}
    
    for txn in transactions:
        material_name = txn["raw_materials"]["name"]
        unit = txn["raw_materials"]["measurement_unit"]
        quantity = txn["quantity"]
        txn_date = txn["created_at"][:10]
        
        if txn["transaction_type"] == "usage":
            if material_name not in usage_summary:
                usage_summary[material_name] = {"total": 0, "unit": unit, "transactions": 0}
            usage_summary[material_name]["total"] += quantity
            usage_summary[material_name]["transactions"] += 1
            
            # Daily breakdown
            if txn_date not in daily_usage:
                daily_usage[txn_date] = {}
            if material_name not in daily_usage[txn_date]:
                daily_usage[txn_date][material_name] = 0
            daily_usage[txn_date][material_name] += quantity
        
        elif txn["transaction_type"] == "purchase":
            if material_name not in purchase_summary:
                purchase_summary[material_name] = {"total": 0, "unit": unit, "cost": 0}
            purchase_summary[material_name]["total"] += quantity
            if txn.get("cost"):
                purchase_summary[material_name]["cost"] += txn["cost"]
    
    return {
        "period": {"from": date_from, "to": date_to},
        "usage_summary": [
            {"material": k, **v} for k, v in usage_summary.items()
        ],
        "purchase_summary": [
            {"material": k, **v} for k, v in purchase_summary.items()
        ],
        "daily_usage": [
            {"date": k, "materials": v} for k, v in sorted(daily_usage.items())
        ]
    }

@router.get("/analytics/cost-analysis")
async def get_cost_analysis(
    request: Request,
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    current_user: dict = Depends(require_manager_up)
):
    """Get cost analysis for raw materials"""
    if not date_from:
        date_from = date.today() - timedelta(days=30)
    if not date_to:
        date_to = date.today()
    
    # Get purchase transactions with costs
    purchases = supabase.table("raw_material_transactions").select(
        "*, raw_materials!inner(name, measurement_unit)"
    ).eq("transaction_type", "purchase").gte("created_at", date_from.isoformat()).lte("created_at", f"{date_to.isoformat()}T23:59:59").execute()
    
    cost_analysis = {}
    total_spent = 0
    
    for purchase in purchases.data:
        material_name = purchase["raw_materials"]["name"]
        cost = purchase.get("cost", 0) or 0
        quantity = purchase["quantity"]
        
        if material_name not in cost_analysis:
            cost_analysis[material_name] = {
                "total_cost": 0,
                "total_quantity": 0,
                "transactions": 0,
                "unit": purchase["raw_materials"]["measurement_unit"]
            }
        
        cost_analysis[material_name]["total_cost"] += cost
        cost_analysis[material_name]["total_quantity"] += quantity
        cost_analysis[material_name]["transactions"] += 1
        total_spent += cost
    
    # Calculate average costs
    for material, data in cost_analysis.items():
        if data["total_quantity"] > 0:
            data["cost_per_unit"] = round(data["total_cost"] / data["total_quantity"], 2)
        else:
            data["cost_per_unit"] = 0
    
    return {
        "period": {"from": date_from, "to": date_to},
        "total_spent": round(total_spent, 2),
        "cost_breakdown": [
            {"material": k, **v, "total_cost": round(v["total_cost"], 2)}
            for k, v in cost_analysis.items()
        ],
        "top_expenses": sorted(
            [{"material": k, **v} for k, v in cost_analysis.items()],
            key=lambda x: x["total_cost"],
            reverse=True
        )[:10]
    }

@router.get("/reports/low-stock")
async def get_low_stock_report(
    current_user: dict = Depends(require_inventory_staff)
):
    """Get low stock alert report"""
    materials = supabase.table("raw_materials").select("*, suppliers(name)").lte("current_quantity", 10).execute()
    
    alerts = []
    for material in materials.data:
        qty = material["current_quantity"]
        status = "out_of_stock" if qty <= 0 else "low_stock"
        
        alerts.append({
            "material_id": material["id"],
            "name": material["name"],
            "current_quantity": qty,
            "measurement_unit": material["measurement_unit"],
            "status": status,
            "supplier": material["suppliers"]["name"] if material["suppliers"] else None,
            "sku": material["sku"]
        })
    
    return {
        "alerts": alerts,
        "summary": {
            "total_alerts": len(alerts),
            "out_of_stock": len([a for a in alerts if a["status"] == "out_of_stock"]),
            "low_stock": len([a for a in alerts if a["status"] == "low_stock"])
        }
    }

@router.get("/materials_dashboard")
async def get_raw_materials_dashboard(
    request: Request,
    current_user: dict = Depends(require_inventory_staff)
):
    """Get raw materials dashboard overview"""
    cache_key = "raw_materials:dashboard"
    cached = redis_client.get(cache_key)
    if cached:
        return cached
    
    # Get all materials
    materials = supabase.table("raw_materials").select("*").execute()
    
    # Calculate metrics
    total_materials = len(materials.data)
    in_stock = len([m for m in materials.data if m["current_quantity"] > 10])
    low_stock = len([m for m in materials.data if 0 < m["current_quantity"] <= 10])
    out_of_stock = len([m for m in materials.data if m["current_quantity"] <= 0])
    
    # Recent transactions
    recent = supabase.table("raw_material_transactions").select(
        "*, raw_materials(name), profiles(email)"
    ).order("created_at", desc=True).limit(10).execute()
    
    dashboard_data = {
        "summary": {
            "total_materials": total_materials,
            "in_stock": in_stock,
            "low_stock": low_stock,
            "out_of_stock": out_of_stock
        },
        "recent_transactions": recent.data,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    redis_client.set(cache_key, dashboard_data, 300)
    return dashboard_data


@router.get("/{material_id}", response_model=dict)
async def get_raw_material(
    material_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get specific raw material details"""
    result = supabase.table("raw_materials").select("*, suppliers(*)").eq("id", material_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Raw material not found")
    
    return result.data[0]

@router.patch("/{material_id}")
async def update_raw_material(
    material_id: str,
    update: RawMaterialUpdate,
    request: Request,
    current_user: dict = Depends(require_inventory_staff)
):
    """Update raw material details"""
    updates = {k: v for k, v in update.dict().items() if v is not None}
    
    if updates:
        updates["updated_at"] = datetime.utcnow().isoformat()
        result = supabase.table("raw_materials").update(updates).eq("id", material_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Raw material not found")
    
    await log_activity(
        current_user["id"], current_user["email"], current_user["role"],
        "update", "raw_material", material_id, updates, request
    )
    
    return {"message": "Raw material updated"}


@router.post("/areas", response_model=dict)
async def create_area(
    area: AreaCreate,
    current_user: dict = Depends(require_inventory_staff)
):
    existing = supabase.table("delivery_areas").select("id").eq("name", area.name).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Area name already exists")
    
    area_data = {
        **area.dict(),
        "delivery_fee": float(area.delivery_fee),
        "created_by": current_user["id"]
    }
    
    result = supabase.table("delivery_areas").insert(area_data).execute()
    redis_client.delete("delivery:areas")
    return {"message": "Area created", "data": result.data[0]}

@router.get("/areas", response_model=List[dict])
async def get_areas(
    active_only: bool = True,
    current_user: dict = Depends(get_current_user)
):
    cache_key = f"delivery:areas:{active_only}"
    cached = redis_client.get(cache_key)
    if cached:
        return cached
    
    query = supabase.table("delivery_areas").select("*")
    if active_only:
        query = query.eq("is_active", True)
    
    result = query.order("name").execute()
    redis_client.set(cache_key, result.data, 300)
    return result.data

@router.patch("/areas/{area_id}")
async def update_area(
    area_id: str,
    update: AreaUpdate,
    current_user: dict = Depends(require_inventory_staff)
):
    updates = {k: v for k, v in update.dict().items() if v is not None}
    if "delivery_fee" in updates:
        updates["delivery_fee"] = float(updates["delivery_fee"])
    
    if updates:
        updates["updated_at"] = datetime.utcnow().isoformat()
        result = supabase.table("delivery_areas").update(updates).eq("id", area_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Area not found")
    
    redis_client.delete_pattern("delivery:areas:*")
    return {"message": "Area updated"}

@router.delete("/areas/{area_id}")
async def delete_area(
    area_id: str,
    current_user: dict = Depends(require_inventory_staff)
):
    result = supabase.table("delivery_areas").delete().eq("id", area_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Area not found")
    
    redis_client.delete_pattern("delivery:areas:*")
    return {"message": "Area deleted"}


