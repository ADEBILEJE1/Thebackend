from fastapi import APIRouter, HTTPException, status, Depends, Request
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from pydantic import BaseModel, Field, EmailStr
from decimal import Decimal

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
    product_template_id: str
    supplier_id: Optional[str] = None
    sku: Optional[str] = None
    variant_name: Optional[str] = None
    category_id: str
    price: Decimal = Field(gt=0)
    description: Optional[str] = None
    image_url: Optional[str] = None
    units: int = Field(ge=0, default=0)
    low_stock_threshold: int = Field(gt=0, default=10)

class ProductUpdate(BaseModel):
    category_id: Optional[str] = None
    price: Optional[Decimal] = Field(gt=0, default=None)
    sku: Optional[str] = None
    supplier: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    low_stock_threshold: Optional[int] = Field(gt=0, default=None)

class StockUpdate(BaseModel):
    quantity: int = Field(gt=0)
    operation: str = Field(pattern="^(add|remove)$")
    notes: Optional[str] = None

class ProductAvailability(BaseModel):
    is_available: bool

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

class ProductTemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    default_category_id: Optional[str] = None

class ProductTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    default_category_id: Optional[str] = None
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
    query = supabase.table("categories").select("*")
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
            if k == "price":
                updates[k] = float(v)
            else:
                updates[k] = v
    
    if updates:
        result = supabase.table("categories").update(updates).eq("id", category_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Category not found")
    
    return {"message": "Category updated"}

# Products
@router.post("/products", response_model=dict)
async def create_product(
    product: ProductCreate,
    current_user: dict = Depends(require_inventory_staff)
):
    # Verify product template exists
    template = supabase.table("product_templates").select("*").eq("id", product.product_template_id).execute()
    if not template.data:
        raise HTTPException(status_code=404, detail="Product template not found")
    

    template_data = template.data[0]

    # Verify category exists
    category = supabase.table("categories").select("id").eq("id", product.category_id).execute()
    if not category.data:
        raise HTTPException(status_code=404, detail="Category not found")
    
    # Verify supplier exists if provided
    if product.supplier_id:
        supplier = supabase.table("suppliers").select("id").eq("id", product.supplier_id).execute()
        if not supplier.data:
            raise HTTPException(status_code=404, detail="Supplier not found")
    
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
    product_dict["price"] = float(product_dict["price"])  # Convert Decimal to float
    product_data = {
        **product_dict,
        "name": template_data["name"],
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
    
    query = supabase.table("products").select("*, categories(*), suppliers(name), product_templates(name)")
    
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
   
   supabase.table("stock_entries").insert(stock_entry).execute()
   
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
    
    result = supabase.table("products").update(update).eq("id", product_id).execute()
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
    result = supabase.table("stock_entries").select("*, profiles(email)").eq("product_id", product_id).order("created_at", desc=True).limit(limit).execute()
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
    
    result = supabase.table("products").select("*, categories(name)").in_("status", [StockStatus.LOW_STOCK, StockStatus.OUT_OF_STOCK]).order("units").execute()
    
    # Cache for 5 minutes
    redis_client.set(CacheKeys.LOW_STOCK_ALERTS, result.data, 300)
    
    return result.data



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

# Product Templates
@router.post("/product-templates", response_model=dict)
async def create_product_template(
    template: ProductTemplateCreate,
    current_user: dict = Depends(require_inventory_staff)
):
    # Check unique name
    existing = supabase.table("product_templates").select("id").eq("name", template.name).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Product template name already exists")
    
    template_data = {**template.dict(), "created_by": current_user["id"]}
    result = supabase.table("product_templates").insert(template_data).execute()
    return {"message": "Product template created", "data": result.data[0]}

@router.get("/product-templates", response_model=List[dict])
async def get_product_templates(
    active_only: bool = True,
    search: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    query = supabase.table("product_templates").select("*, categories(*)")
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