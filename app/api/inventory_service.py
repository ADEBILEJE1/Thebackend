from typing import List, Dict, Optional, Any
from datetime import datetime, date, timedelta
from decimal import Decimal
from collections import defaultdict
from sqlalchemy import text
from ..database import supabase
from ..services.redis import redis_client
from ..core.cache import CacheKeys
from ..models.inventory import StockStatus
from ..models.user import UserRole


class InventoryService:
    """Service class for inventory dashboard operations"""
    
    @staticmethod
    async def get_dashboard_overview() -> Dict[str, Any]:
        """Get comprehensive inventory dashboard overview"""
        cache_key = "inventory:dashboard:overview"
        cached = redis_client.get(cache_key)
        if cached:
            return cached
        
        # Get all products with categories
        products_result = supabase.table("products").select("*, categories(name)").execute()
        products = products_result.data
        
        # Calculate key metrics
        total_products = len(products)
        total_categories = len(set(p["categories"]["name"] for p in products if p["categories"]))
        
        # Stock status breakdown
        in_stock_count = len([p for p in products if p["status"] == StockStatus.IN_STOCK])
        low_stock_count = len([p for p in products if p["status"] == StockStatus.LOW_STOCK])
        out_of_stock_count = len([p for p in products if p["status"] == StockStatus.OUT_OF_STOCK])
        
        # Calculate total inventory value
        total_value = sum(float(p["price"]) * p["units"] for p in products)
        
        # Get low stock items
        critical_items = [
            {
                "id": p["id"],
                "name": p["name"],
                "current_stock": p["units"],
                "threshold": p["low_stock_threshold"],
                "category": p["categories"]["name"] if p["categories"] else "Uncategorized",
                "status": p["status"]
            }
            for p in products if p["status"] in [StockStatus.LOW_STOCK, StockStatus.OUT_OF_STOCK]
        ]
        
        # Recent stock movements (last 10)
        movements_result = supabase.table("stock_entries").select(
            "*, products(name), profiles(email)"
        ).order("created_at", desc=True).limit(10).execute()
        
        recent_movements = [
            {
                "product_name": m["products"]["name"],
                "quantity": m["quantity"],
                "type": m["entry_type"],
                "user": m["profiles"]["email"],
                "timestamp": m["created_at"],
                "notes": m.get("notes")
            }
            for m in movements_result.data
        ]
        
        dashboard_data = {
            "summary": {
                "total_products": total_products,
                "total_categories": total_categories,
                "total_inventory_value": float(total_value),
                "stock_status": {
                    "in_stock": in_stock_count,
                    "low_stock": low_stock_count,
                    "out_of_stock": out_of_stock_count
                }
            },
            "critical_items": critical_items,
            "recent_movements": recent_movements,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Cache for 2 minutes
        redis_client.set(cache_key, dashboard_data, 120)
        return dashboard_data
    
    @staticmethod
    async def get_stock_movement_trends(days: int = 30) -> Dict[str, Any]:
        """Analyze stock movement trends over specified days"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Get stock entries in date range
        movements_result = supabase.table("stock_entries").select(
            "*, products(name, categories(name))"
        ).gte("created_at", start_date.isoformat()).execute()
        
        movements = movements_result.data
        
        # Daily movement summary
        daily_movements = {}
        product_trends = {}
        category_trends = {}
        
        for movement in movements:
            movement_date = movement["created_at"][:10]
            product_name = movement["products"]["name"]
            category_name = movement["products"]["categories"]["name"]
            quantity = movement["quantity"]
            entry_type = movement["entry_type"]
            
            # Daily totals
            if movement_date not in daily_movements:
                daily_movements[movement_date] = {"additions": 0, "removals": 0, "net": 0}
            
            if entry_type == "add":
                daily_movements[movement_date]["additions"] += quantity
                daily_movements[movement_date]["net"] += quantity
            else:
                daily_movements[movement_date]["removals"] += quantity
                daily_movements[movement_date]["net"] -= quantity
            
            # Product trends
            if product_name not in product_trends:
                product_trends[product_name] = {"additions": 0, "removals": 0, "net": 0}
            
            if entry_type == "add":
                product_trends[product_name]["additions"] += quantity
                product_trends[product_name]["net"] += quantity
            else:
                product_trends[product_name]["removals"] += quantity
                product_trends[product_name]["net"] -= quantity
            
            # Category trends
            if category_name not in category_trends:
                category_trends[category_name] = {"additions": 0, "removals": 0, "net": 0}
            
            if entry_type == "add":
                category_trends[category_name]["additions"] += quantity
                category_trends[category_name]["net"] += quantity
            else:
                category_trends[category_name]["removals"] += quantity
                category_trends[category_name]["net"] -= quantity
        
        # Sort trends by activity
        top_products = sorted(
            [{"product": k, **v} for k, v in product_trends.items()],
            key=lambda x: abs(x["net"]),
            reverse=True
        )[:10]
        
        return {
            "period": {"start": start_date.date(), "end": end_date.date(), "days": days},
            "daily_movements": [
                {"date": k, **v} for k, v in sorted(daily_movements.items())
            ],
            "top_active_products": top_products,
            "category_summary": [
                {"category": k, **v} for k, v in category_trends.items()
            ],
            "total_movements": len(movements)
        }
    
    @staticmethod
    async def get_inventory_valuation() -> Dict[str, Any]:
        """Calculate detailed inventory valuation by category"""
        products_result = supabase.table("products").select("*, categories(name)").execute()
        products = products_result.data
        
        category_valuations = {}
        total_value = 0.0
        total_units = 0
        
        for product in products:
            category_name = product["categories"]["name"]
            product_value = float(product["price"]) * product["units"]
            total_value += product_value
            total_units += product["units"]
            
            if category_name not in category_valuations:
                category_valuations[category_name] = {
                    "total_value": 0.0,
                    "total_units": 0,
                    "product_count": 0,
                    "products": []
                }
            
            category_valuations[category_name]["total_value"] += float(product_value)
            category_valuations[category_name]["total_units"] += product["units"]
            category_valuations[category_name]["product_count"] += 1
            category_valuations[category_name]["products"].append({
                "name": product["name"],
                "units": product["units"],
                "unit_price": float(product["price"]),
                "total_value": float(product_value),
                "status": product["status"]
            })
        
        # Convert to serializable format and calculate percentages
        valuation_data = []
        for category, data in category_valuations.items():
            value_percentage = (float(data["total_value"]) / float(total_value) * 100) if total_value > 0 else 0
            units_percentage = (data["total_units"] / total_units * 100) if total_units > 0 else 0
            
            valuation_data.append({
                "category": category,
                "total_value": float(data["total_value"]),
                "total_units": data["total_units"],
                "product_count": data["product_count"],
                "value_percentage": round(value_percentage, 2),
                "units_percentage": round(units_percentage, 2),
                "average_unit_price": float(data["total_value"]) / data["total_units"] if data["total_units"] > 0 else 0,
                "products": sorted(data["products"], key=lambda x: x["total_value"], reverse=True)
            })
        
        return {
            "total_inventory_value": float(total_value),
            "total_units": total_units,
            "category_breakdown": sorted(valuation_data, key=lambda x: x["total_value"], reverse=True),
            "timestamp": datetime.utcnow().isoformat()
        }
    
    @staticmethod
    async def bulk_stock_update(updates: List[Dict[str, Any]], user_id: str) -> Dict[str, Any]:
        """Perform bulk stock updates with validation"""
        results = {
            "successful": [],
            "failed": [],
            "total_processed": len(updates)
        }
        
        for update in updates:
            try:
                product_id = update["product_id"]
                quantity = update["quantity"]
                operation = update["operation"]  # "add" or "remove"
                notes = update.get("notes", "Bulk update")
                
                # Get current product
                product_result = supabase.table("products").select("*").eq("id", product_id).execute()
                if not product_result.data:
                    results["failed"].append({
                        "product_id": product_id,
                        "error": "Product not found"
                    })
                    continue
                
                product = product_result.data[0]
                current_units = product["units"]
                low_threshold = product["low_stock_threshold"]
                
                # Calculate new units
                if operation == "add":
                    new_units = current_units + quantity
                elif operation == "remove":
                    if quantity > current_units:
                        results["failed"].append({
                            "product_id": product_id,
                            "product_name": product["name"],
                            "error": f"Cannot remove {quantity} units. Only {current_units} available"
                        })
                        continue
                    new_units = current_units - quantity
                else:
                    results["failed"].append({
                        "product_id": product_id,
                        "error": "Invalid operation. Use 'add' or 'remove'"
                    })
                    continue
                
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
                    "updated_by": user_id,
                    "updated_at": datetime.utcnow().isoformat()
                }
                
                supabase.table("products").update(product_update).eq("id", product_id).execute()
                
                # Log stock entry
                stock_entry = {
                    "product_id": product_id,
                    "quantity": quantity,
                    "entry_type": operation,
                    "notes": notes,
                    "entered_by": user_id
                }
                
                supabase.table("stock_entries").insert(stock_entry).execute()
                
                results["successful"].append({
                    "product_id": product_id,
                    "product_name": product["name"],
                    "previous_units": current_units,
                    "new_units": new_units,
                    "operation": operation,
                    "quantity": quantity,
                    "new_status": new_status
                })
                
            except Exception as e:
                results["failed"].append({
                    "product_id": update.get("product_id", "unknown"),
                    "error": str(e)
                })
        
        # Invalidate relevant caches
        redis_client.delete_pattern("products:list:*")
        redis_client.delete_pattern("inventory:dashboard:*")
        redis_client.delete(CacheKeys.LOW_STOCK_ALERTS)
        
        return results
    
    @staticmethod
    async def get_reorder_suggestions(threshold_multiplier: float = 1.5) -> Dict[str, Any]:
        """Generate reorder suggestions based on actual sales velocity and current stock"""
        # Get ALL products, not just low stock ones - sales could make healthy stock become low quickly
        products_result = supabase.table("products").select("*, categories(name)").execute()
        all_products = products_result.data
        
        # Get comprehensive sales data for the last 30 days
        thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
        
        # Get all order items to calculate real sales velocity
        all_sales_result = supabase.table("order_items").select(
            "product_id, quantity, orders!inner(created_at, status)"
        ).gte("orders.created_at", thirty_days_ago).neq("orders.status", "cancelled").execute()
        
        # Calculate sales velocity per product
        product_sales_velocity = defaultdict(lambda: {"total_sold": 0, "daily_velocity": 0})
        
        for sale in all_sales_result.data:
            product_id = sale["product_id"]
            product_sales_velocity[product_id]["total_sold"] += sale["quantity"]
        
        # Calculate daily velocities
        for product_id, data in product_sales_velocity.items():
            data["daily_velocity"] = data["total_sold"] / 30
        
        suggestions = []
        
        for product in all_products:
            product_id = product["id"]
            current_stock = product["units"]
            threshold = product["low_stock_threshold"]
            
            # Get actual sales velocity for this product
            sales_data = product_sales_velocity.get(product_id, {"total_sold": 0, "daily_velocity": 0})
            daily_velocity = sales_data["daily_velocity"]
            total_sold_30_days = sales_data["total_sold"]
            
            # Skip if no sales and stock is adequate
            if daily_velocity == 0 and current_stock >= threshold:
                continue
            
            # Calculate days until stock runs out based on actual sales
            days_until_empty = (current_stock / daily_velocity) if daily_velocity > 0 else 999
            
            # Determine if reorder is needed based on sales-driven logic
            needs_reorder = False
            reorder_reason = ""
            
            if current_stock <= 0:
                needs_reorder = True
                reorder_reason = "Out of stock"
            elif current_stock <= threshold:
                needs_reorder = True
                reorder_reason = "Below threshold"
            elif daily_velocity > 0 and days_until_empty < 14:  # Will run out in 2 weeks
                needs_reorder = True
                reorder_reason = f"Will run out in {days_until_empty:.1f} days at current sales rate"
            elif daily_velocity > (current_stock / 7):  # High sales velocity vs stock
                needs_reorder = True
                reorder_reason = "High sales velocity vs current stock"
            
            if needs_reorder:
                # Calculate suggested quantity based on sales velocity
                days_of_stock = 30  # Target 30 days of stock
                safety_buffer = max(threshold * threshold_multiplier, daily_velocity * 7)  # 1 week buffer minimum
                
                suggested_quantity = max(
                    int((daily_velocity * days_of_stock) + safety_buffer - current_stock),
                    threshold - current_stock if current_stock < threshold else int(daily_velocity * 14)  # Minimum 2 weeks supply
                )
                
                if suggested_quantity > 0:
                    # Calculate urgency score based on sales impact
                    if current_stock <= 0:
                        urgency_score = 100
                    elif days_until_empty < 3:
                        urgency_score = 95
                    elif days_until_empty < 7:
                        urgency_score = 85
                    elif daily_velocity > 3 and current_stock < threshold:
                        urgency_score = 75
                    else:
                        urgency_score = min(100, max(0, 100 - (days_until_empty * 5)))
                    
                    suggestions.append({
                        "product_id": product["id"],
                        "product_name": product["name"],
                        "category": product["categories"]["name"],
                        "current_stock": current_stock,
                        "threshold": threshold,
                        "suggested_quantity": suggested_quantity,
                        "daily_sales_velocity": round(daily_velocity, 2),
                        "total_sold_30_days": total_sold_30_days,
                        "days_until_empty": round(days_until_empty, 1) if days_until_empty < 999 else "No recent sales",
                        "urgency_score": round(urgency_score),
                        "status": product["status"],
                        "unit_price": float(product["price"]),
                        "estimated_cost": float(product["price"]) * suggested_quantity,
                        "reorder_reason": reorder_reason
                    })
        
        # Sort by urgency score (highest first)
        suggestions.sort(key=lambda x: x["urgency_score"], reverse=True)
        
        # Calculate total estimated cost
        total_estimated_cost = sum(s["estimated_cost"] for s in suggestions)
        
        return {
            "suggestions": suggestions,
            "summary": {
                "total_products_analyzed": len(all_products),
                "products_needing_reorder": len(suggestions),
                "high_priority_count": len([s for s in suggestions if s["urgency_score"] > 80]),
                "medium_priority_count": len([s for s in suggestions if 50 <= s["urgency_score"] <= 80]),
                "low_priority_count": len([s for s in suggestions if s["urgency_score"] < 50]),
                "total_estimated_cost": sum(s["estimated_cost"] for s in suggestions),
                "sales_driven_alerts": len([s for s in suggestions if "sales" in s["reorder_reason"].lower()]),
                "out_of_stock_alerts": len([s for s in suggestions if s["current_stock"] <= 0])
            },
            "sales_impact_analysis": {
                "products_with_high_velocity": len([s for s in suggestions if s["daily_sales_velocity"] > 3]),
                "products_selling_but_low_stock": len([s for s in suggestions if s["daily_sales_velocity"] > 0 and s["current_stock"] < s["threshold"]]),
                "revenue_at_risk": sum(
                    s["daily_sales_velocity"] * s["unit_price"] * 7  # 1 week of lost sales
                    for s in suggestions if s["current_stock"] <= 0
                )
            },
            "timestamp": datetime.utcnow().isoformat()
        }
    
    @staticmethod
    async def get_product_performance(days: int = 30) -> Dict[str, Any]:
        """Analyze product performance based on sales data"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Get order items with product and order details
        order_items_result = supabase.table("order_items").select(
            "*, orders!inner(created_at, status), products!inner(name, price, categories(name))"
        ).gte("orders.created_at", start_date.isoformat()).neq("orders.status", "cancelled").execute()
        
        order_items = order_items_result.data
        
        # Aggregate product performance
        product_performance = {}
        
        for item in order_items:
            product_id = item["product_id"]
            product_name = item["products"]["name"]
            category_name = item["products"]["categories"]["name"]
            quantity = item["quantity"]
            revenue = float(item["total_price"])
            
            if product_id not in product_performance:
                product_performance[product_id] = {
                    "product_name": product_name,
                    "category": category_name,
                    "total_quantity_sold": 0,
                    "total_revenue": 0,
                    "order_frequency": 0,
                    "current_price": float(item["products"]["price"])
                }
            
            product_performance[product_id]["total_quantity_sold"] += quantity
            product_performance[product_id]["total_revenue"] += revenue
            product_performance[product_id]["order_frequency"] += 1
        
        # Convert to list and calculate additional metrics
        performance_list = []
        for product_id, data in product_performance.items():
            avg_quantity_per_order = data["total_quantity_sold"] / data["order_frequency"]
            daily_avg_sales = data["total_quantity_sold"] / days
            
            performance_list.append({
                "product_id": product_id,
                **data,
                "average_quantity_per_order": round(avg_quantity_per_order, 2),
                "daily_average_sales": round(daily_avg_sales, 2),
                "revenue_per_unit": round(data["total_revenue"] / data["total_quantity_sold"], 2) if data["total_quantity_sold"] > 0 else 0
            })
        
        # Sort by different metrics
        top_by_quantity = sorted(performance_list, key=lambda x: x["total_quantity_sold"], reverse=True)[:10]
        top_by_revenue = sorted(performance_list, key=lambda x: x["total_revenue"], reverse=True)[:10]
        top_by_frequency = sorted(performance_list, key=lambda x: x["order_frequency"], reverse=True)[:10]
        
        # Category performance summary
        category_performance = {}
        for item in performance_list:
            category = item["category"]
            if category not in category_performance:
                category_performance[category] = {
                    "total_quantity": 0,
                    "total_revenue": 0,
                    "product_count": 0
                }
            
            category_performance[category]["total_quantity"] += item["total_quantity_sold"]
            category_performance[category]["total_revenue"] += item["total_revenue"]
            category_performance[category]["product_count"] += 1
        
        category_summary = [
            {
                "category": k,
                **v,
                "average_revenue_per_product": round(v["total_revenue"] / v["product_count"], 2)
            }
            for k, v in category_performance.items()
        ]
        
        return {
            "period": {"start": start_date.date(), "end": end_date.date(), "days": days},
            "top_performers": {
                "by_quantity": top_by_quantity,
                "by_revenue": top_by_revenue,
                "by_frequency": top_by_frequency
            },
            "category_performance": sorted(category_summary, key=lambda x: x["total_revenue"], reverse=True),
            "total_products_sold": len(performance_list),
            "overall_metrics": {
                "total_quantity_sold": sum(p["total_quantity_sold"] for p in performance_list),
                "total_revenue": sum(p["total_revenue"] for p in performance_list),
                "average_order_value": sum(p["total_revenue"] for p in performance_list) / sum(p["order_frequency"] for p in performance_list) if performance_list else 0
            }
        }
    
    @staticmethod
    async def get_wastage_analysis(days: int = 30) -> Dict[str, Any]:
        """Analyze product wastage and expired items"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Get stock entries marked as wastage/expired
        wastage_entries = supabase.table("stock_entries").select(
            "*, products(name, price, categories(name))"
        ).eq("entry_type", "remove").ilike("notes", "%waste%").gte("created_at", start_date.isoformat()).execute()
        
        expired_entries = supabase.table("stock_entries").select(
            "*, products(name, price, categories(name))"
        ).eq("entry_type", "remove").ilike("notes", "%expired%").gte("created_at", start_date.isoformat()).execute()
        
        # Combine wastage entries
        all_wastage = wastage_entries.data + expired_entries.data
        
        if not all_wastage:
            return {
                "period": {"start": start_date.date(), "end": end_date.date(), "days": days},
                "total_wastage": {"quantity": 0, "value": 0},
                "by_product": [],
                "by_category": [],
                "daily_breakdown": [],
                "recommendations": []
            }
        
        # Analyze wastage by product
        product_wastage = {}
        daily_wastage = {}
        
        for entry in all_wastage:
            product_name = entry["products"]["name"]
            category_name = entry["products"]["categories"]["name"]
            quantity = entry["quantity"]
            unit_price = float(entry["products"]["price"])
            value = quantity * unit_price
            entry_date = entry["created_at"][:10]
            
            # Product wastage
            if product_name not in product_wastage:
                product_wastage[product_name] = {
                    "category": category_name,
                    "total_quantity": 0,
                    "total_value": 0,
                    "unit_price": unit_price,
                    "entries_count": 0
                }
            
            product_wastage[product_name]["total_quantity"] += quantity
            product_wastage[product_name]["total_value"] += value
            product_wastage[product_name]["entries_count"] += 1
            
            # Daily wastage
            if entry_date not in daily_wastage:
                daily_wastage[entry_date] = {"quantity": 0, "value": 0}
            
            daily_wastage[entry_date]["quantity"] += quantity
            daily_wastage[entry_date]["value"] += value
        
        # Category summary
        category_wastage = {}
        for product_name, data in product_wastage.items():
            category = data["category"]
            if category not in category_wastage:
                category_wastage[category] = {"quantity": 0, "value": 0}
            
            category_wastage[category]["quantity"] += data["total_quantity"]
            category_wastage[category]["value"] += data["total_value"]
        
        # Generate recommendations
        recommendations = []
        high_wastage_products = sorted(
            product_wastage.items(),
            key=lambda x: x[1]["total_value"],
            reverse=True
        )[:5]
        
        for product_name, data in high_wastage_products:
            if data["total_value"] > 50:  # Arbitrary threshold
                recommendations.append(
                    f"Monitor {product_name}: ${data['total_value']:.2f} wasted in {days} days"
                )
        
        total_quantity = sum(data["total_quantity"] for data in product_wastage.values())
        total_value = sum(data["total_value"] for data in product_wastage.values())
        
        return {
            "period": {"start": start_date.date(), "end": end_date.date(), "days": days},
            "total_wastage": {
                "quantity": total_quantity,
                "value": round(total_value, 2)
            },
            "by_product": [
                {"product": k, **v, "total_value": round(v["total_value"], 2)}
                for k, v in sorted(product_wastage.items(), key=lambda x: x[1]["total_value"], reverse=True)
            ],
            "by_category": [
                {"category": k, **v, "value": round(v["value"], 2)}
                for k, v in sorted(category_wastage.items(), key=lambda x: x[1]["value"], reverse=True)
            ],
            "daily_breakdown": [
                {"date": k, **v, "value": round(v["value"], 2)}
                for k, v in sorted(daily_wastage.items())
            ],
            "recommendations": recommendations
        }
    

    @staticmethod
    async def get_individual_inventory_analytics(staff_id: str, days: int = 30) -> Dict[str, Any]:
        """Get individual inventory staff performance analytics"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Stock entries by this staff
        stock_entries = supabase.table("stock_entries").select("*, products(name, categories(name))").eq("entered_by", staff_id).gte("created_at", start_date.isoformat()).execute()
        
        # Products created/updated by this staff  
        products_created = supabase.table("products").select("*").eq("created_by", staff_id).gte("created_at", start_date.isoformat()).execute()
        products_updated = supabase.table("products").select("*").eq("updated_by", staff_id).gte("updated_at", start_date.isoformat()).execute()
        
        # Activity logs
        activities = supabase.table("activity_logs").select("*").eq("user_id", staff_id).gte("created_at", start_date.isoformat()).execute()
        
        # Calculate metrics
        total_units_added = sum(e["quantity"] for e in stock_entries.data if e["entry_type"] == "add")
        total_units_removed = sum(e["quantity"] for e in stock_entries.data if e["entry_type"] == "remove")
        
        # Category breakdown
        category_work = defaultdict(int)
        for entry in stock_entries.data:
            if entry["products"] and entry["products"]["categories"]:
                category_work[entry["products"]["categories"]["name"]] += 1
        
        return {
            "staff_id": staff_id,
            "period": {"start": start_date.date(), "end": end_date.date(), "days": days},
            "stock_management": {
                "total_entries": len(stock_entries.data),
                "units_added": total_units_added,
                "units_removed": total_units_removed,
                "net_stock_change": total_units_added - total_units_removed,
                "daily_average_entries": round(len(stock_entries.data) / days, 2)
            },
            "product_management": {
                "products_created": len(products_created.data),
                "products_updated": len(products_updated.data),
                "total_product_actions": len(products_created.data) + len(products_updated.data)
            },
            "category_focus": dict(category_work),
            "activity_summary": {
                "total_actions": len(activities.data),
                "actions_per_day": round(len(activities.data) / days, 2)
            }
        }