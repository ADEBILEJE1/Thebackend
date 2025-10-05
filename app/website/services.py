from typing import List, Dict, Optional, Any
from decimal import Decimal
from datetime import datetime, timedelta
import re
import uuid
import httpx
from uuid import uuid4
import random
import string
import math
import requests
import base64
from datetime import datetime, timedelta
from ..database import supabase
from ..services.redis import redis_client
from ..core.cache import CacheKeys
from ..config import settings


class CustomerService:
    @staticmethod
    def extract_name_from_email(email: str) -> str:
        """Extract full name from email address"""
        local_part = email.split('@')[0]
        
        # Remove numbers and common separators
        name_part = re.sub(r'[0-9_\.\-]+', ' ', local_part)
        
        # Split and capitalize
        words = name_part.split()
        if len(words) >= 2:
            return ' '.join(word.capitalize() for word in words)
        elif len(words) == 1:
            return words[0].capitalize() + " User"
        else:
            return "Customer User"
    
    @staticmethod
    async def get_or_create_customer(email: str, phone: str = None, full_name: str = None) -> Dict[str, Any]:
        """Get existing customer or create new one"""
        # Check if customer exists
        existing = supabase.table("website_customers").select("*").eq("email", email).execute()
        
        if existing.data:
            # Update last_seen
            supabase.table("website_customers").update({
                "last_seen": datetime.utcnow().isoformat()
            }).eq("id", existing.data[0]["id"]).execute()
            
            return existing.data[0]
        
        # Create new customer
        if not full_name:
            full_name = CustomerService.extract_name_from_email(email)
        
        customer_data = {
            "email": email,
            "full_name": full_name,
            "phone": phone,
            "last_seen": datetime.utcnow().isoformat()
        }
        
        result = supabase.table("website_customers").insert(customer_data).execute()
        return result.data[0]
    
    @staticmethod
    def generate_pin() -> str:
        """Generate 4-digit PIN"""
        return ''.join(random.choices(string.digits, k=4))
    
    @staticmethod
    async def send_login_pin(email: str) -> bool:
        """Generate and send login PIN to email"""
        pin = CustomerService.generate_pin()
        
        # Store PIN in Redis with 10-minute expiry
        redis_client.set(f"login_pin:{email}", pin, 600)
        
        # TODO: Send email with PIN
        # For now, just log it
        print(f"Login PIN for {email}: {pin}")
        
        return True
    
    @staticmethod
    async def verify_pin(email: str, pin: str) -> bool:
        """Verify login PIN"""
        stored_pin = redis_client.get(f"login_pin:{email}")
        
        if stored_pin == pin:
            redis_client.delete(f"login_pin:{email}")
            return True
        
        return False
    
    @staticmethod
    async def create_customer_session(customer_id: str) -> str:
        """Create 5-year customer session"""
        session_token = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
        
        # Store session with 5-year expiry
        session_data = {
            "customer_id": customer_id,
            "created_at": datetime.utcnow().isoformat()
        }
        
        redis_client.set(f"customer_session:{session_token}", session_data, 60*60*24*365*5)
        
        return session_token

    @staticmethod
    async def check_email_and_handle_auth(email: str, phone: str = None, full_name: str = None) -> Dict[str, Any]:
        """Check if email exists and handle authentication accordingly"""
        existing = supabase.table("website_customers").select("*").eq("email", email).execute()
        
        if len(existing.data) > 0:
            # Email exists - require PIN verification
            pin = CustomerService.generate_pin()
            redis_client.set(f"login_pin:{email}", pin, 600)
            print(f"PIN for {email}: {pin}")
            
            return {
                "requires_pin": True,
                "customer_id": existing.data[0]["id"],
                "message": "Email found. PIN sent for verification."
            }
        else:
            # New email - auto-register
            if not full_name:
                full_name = CustomerService.extract_name_from_email(email)
            
            customer_data = {
                "email": email,
                "full_name": full_name,
                "phone": phone,
                "last_seen": datetime.utcnow().isoformat()
            }
            
            result = supabase.table("website_customers").insert(customer_data).execute()
            session_token = await CustomerService.create_customer_session(result.data[0]["id"])
            
            return {
                "requires_pin": False,
                "customer": result.data[0],
                "session_token": session_token,
                "message": "Account created successfully."
            }


class DeliveryService:
    RESTAURANT_LAT = 7.3775  # Ibadan coordinates
    RESTAURANT_LNG = 3.9470
    
    @staticmethod
    def calculate_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """Calculate distance between two points in kilometers"""
        R = 6371  # Earth's radius in kilometers
        
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lng = math.radians(lng2 - lng1)
        
        a = (math.sin(delta_lat / 2) * math.sin(delta_lat / 2) +
             math.cos(lat1_rad) * math.cos(lat2_rad) *
             math.sin(delta_lng / 2) * math.sin(delta_lng / 2))
        
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        
        return R * c
    
    @staticmethod
    def calculate_delivery_fee(distance_km: float) -> Decimal:
        """Calculate delivery fee based on distance"""
        if distance_km <= 5:
            return Decimal('500')
        elif distance_km <= 10:
            return Decimal('1000')
        elif distance_km <= 15:
            return Decimal('1500')
        elif distance_km <= 20:
            return Decimal('2000')
        else:
            # ₦500 base + ₦250 per additional 5km
            extra_distance = distance_km - 20
            extra_fee = math.ceil(extra_distance / 5) * 250
            return Decimal('2000') + Decimal(str(extra_fee))
    
    @staticmethod
    def estimate_delivery_time(distance_km: float) -> str:
        """Estimate delivery time based on distance"""
        if distance_km <= 5:
            return "20-30 minutes"
        elif distance_km <= 10:
            return "30-45 minutes"
        elif distance_km <= 15:
            return "45-60 minutes"
        else:
            return "60-90 minutes"

class CartService:


    @staticmethod
    async def validate_cart_items(items: List[Dict]) -> List[Dict]:
        processed_items = []
        
        for item in items:
            # Validate main product
            product = supabase.table("products").select("*").eq("id", item["product_id"]).execute()
            
            if not product.data:
                raise ValueError(f"Product {item['product_id']} not found")
            
            product_data = product.data[0]
            
            if not product_data["is_available"] or product_data["status"] == "out_of_stock":
                raise ValueError(f"{product_data['name']} is not available")
            
            # Handle options with quantities
            options = item.get("options", [])
            
            if product_data.get("has_options") and not options:
                raise ValueError(f"{product_data['name']} requires option selection")
            
            # Calculate total quantity
            if options:
                total_quantity = sum(opt["quantity"] for opt in options)
            else:
                total_quantity = item.get("quantity", 1)
            
            if product_data["units"] < total_quantity:
                raise ValueError(f"Insufficient stock for {product_data['name']}. Available: {product_data['units']}")
            
            # Validate options
            if options:
                for opt in options:
                    option = supabase.table("product_options").select("*").eq("id", opt["option_id"]).eq("product_id", item["product_id"]).execute()
                    if not option.data:
                        raise ValueError(f"Invalid option for {product_data['name']}")
            
            final_price = Decimal(str(product_data["price"]))
            
            # Add main product
            processed_items.append({
                "product_id": item["product_id"],
                "product_name": product_data["name"],
                "options": options,
                "quantity": total_quantity,
                "unit_price": final_price,
                "tax_per_unit": Decimal(str(product_data.get("tax_per_unit", 0))),
                "total_price": final_price * total_quantity,
                "preparation_time_minutes": product_data.get("preparation_time_minutes", 15),
                "notes": item.get("notes"),
                "is_extra": False
            })
            
            # Validate and add extras
            extras = item.get("extras", [])
            for extra in extras:
                extra_product = supabase.table("products").select("*").eq("id", extra["id"]).execute()
                
                if not extra_product.data:
                    raise ValueError(f"Extra product {extra['id']} not found")
                
                extra_data = extra_product.data[0]
                
                if extra_data["product_type"] != "extra":
                    raise ValueError(f"{extra_data['name']} is not an extra")
                
                if extra_data["main_product_id"] != item["product_id"]:
                    raise ValueError(f"{extra_data['name']} is not valid for {product_data['name']}")
                
                if not extra_data["is_available"] or extra_data["status"] == "out_of_stock":
                    raise ValueError(f"Extra {extra_data['name']} is not available")
                
                extra_quantity = extra.get("quantity", 1)
                
                if extra_data["units"] < extra_quantity:
                    raise ValueError(f"Insufficient stock for {extra_data['name']}. Available: {extra_data['units']}")
                
                extra_price = Decimal(str(extra_data["price"]))
                
                processed_items.append({
                    "product_id": extra["id"],
                    "product_name": extra_data["name"],
                    "options": [],
                    "quantity": extra_quantity,
                    "unit_price": extra_price,
                    "tax_per_unit": Decimal(str(extra_data.get("tax_per_unit", 0))),
                    "total_price": extra_price * extra_quantity,
                    "preparation_time_minutes": extra_data.get("preparation_time_minutes", 15),
                    "notes": extra.get("notes"),
                    "is_extra": True
                })
        
        return processed_items

    
    
    @staticmethod
    def calculate_order_total(items: List[Dict]) -> Dict[str, Decimal]:
        """Calculate order totals using per-product tax rates"""
        subtotal = sum(item["total_price"] for item in items)
        
        # Calculate tax based on individual product tax rates
        vat = sum(
            Decimal(str(item["tax_per_unit"])) * item["quantity"] 
            for item in items
        )
        
        return {
            "subtotal": subtotal,
            "tax": vat,
            "total": subtotal + vat
        }
    
    @staticmethod
    def generate_batch_id() -> str:
        """Generate unique batch ID for grouping related orders"""
        import uuid
        return f"BATCH-{datetime.now().strftime('%Y%m%d%H%M%S')}-{str(uuid.uuid4())[:8]}"

class AddressService:
    @staticmethod
    async def save_customer_address(customer_id: str, address_data: Dict) -> Dict:
        """Save customer address with area"""
        if address_data.get("is_default"):
            supabase.table("customer_addresses").update({
                "is_default": False
            }).eq("customer_id", customer_id).execute()
        
        # Get area details for full address
        area = supabase.table("delivery_areas").select("name").eq("id", address_data["area_id"]).execute()
        if not area.data:
            raise ValueError("Invalid area selected")
        
        # Compose full address
        full_address = f"{address_data['street_address']}, {area.data[0]['name']}"
        
        address_entry = {
            "customer_id": customer_id,
            "name": address_data["name"],
            "area_id": address_data["area_id"],
            "street_address": address_data["street_address"],
            "full_address": full_address,
            "is_default": address_data.get("is_default", False)
        }
        
        result = supabase.table("customer_addresses").insert(address_entry).execute()
        return result.data[0]
    
    @staticmethod
    async def get_customer_addresses(customer_id: str) -> List[Dict]:
        """Get customer addresses with area details"""
        result = supabase.table("customer_addresses").select("*, delivery_areas(name, delivery_fee, estimated_time)").eq("customer_id", customer_id).order("is_default", desc=True).execute()
        return result.data
    
    @staticmethod
    async def update_customer_address(address_id: str, customer_id: str, update_data: Dict) -> Dict:
        existing = supabase.table("customer_addresses").select("*").eq("id", address_id).eq("customer_id", customer_id).execute()
        if not existing.data:
            raise ValueError("Address not found")
        
        if update_data.get("is_default"):
            supabase.table("customer_addresses").update({"is_default": False}).eq("customer_id", customer_id).execute()
        
        # If area_id is being updated, rebuild full_address
        if "area_id" in update_data or "street_address" in update_data:
            area_id = update_data.get("area_id", existing.data[0]["area_id"])
            street = update_data.get("street_address", existing.data[0]["street_address"])
            
            area = supabase.table("delivery_areas").select("name").eq("id", area_id).execute()
            if area.data:
                update_data["full_address"] = f"{street}, {area.data[0]['name']}"
        
        updates = {k: v for k, v in update_data.items() if v is not None}
        result = supabase.table("customer_addresses").update(updates).eq("id", address_id).execute()
        return result.data[0]

    @staticmethod
    async def delete_customer_address(address_id: str, customer_id: str) -> bool:
        """Delete customer address"""
        result = supabase.table("customer_addresses").delete().eq("id", address_id).eq("customer_id", customer_id).execute()
        return len(result.data) > 0

    @staticmethod
    async def set_default_address(address_id: str, customer_id: str) -> Dict:
        """Set address as default"""
        # Verify ownership
        existing = supabase.table("customer_addresses").select("*").eq("id", address_id).eq("customer_id", customer_id).execute()
        if not existing.data:
            raise ValueError("Address not found")
        
        # Unset all defaults
        supabase.table("customer_addresses").update({"is_default": False}).eq("customer_id", customer_id).execute()
        
        # Set new default
        result = supabase.table("customer_addresses").update({"is_default": True}).eq("id", address_id).execute()
        return result.data[0]
    
class MonnifyService:
    @staticmethod
    def get_base_url() -> str:
        """Get base URL based on environment"""
        return settings.MONNIFY_BASE_URL
    
    @staticmethod
    async def get_access_token() -> str:
        """Fetch access token from Monnify"""
        credentials = f"{settings.MONNIFY_API_KEY}:{settings.MONNIFY_SECRET_KEY}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()

        headers = {
            "Authorization": f"Basic {encoded_credentials}",
            "Content-Type": "application/json"
        }

        url = f"{settings.MONNIFY_BASE_URL}/api/v1/auth/login"
        response = requests.post(url, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()
        print(f"DEBUG Access Token Response: {data}")

        return data["responseBody"]["accessToken"]
    
    @staticmethod
    async def create_virtual_account(
        amount: Decimal,
        customer_email: str,
        customer_name: str,
        customer_phone: str
    ) -> Dict[str, Any]:
        """Create reserved account for bank transfer"""
        access_token = await MonnifyService.get_access_token()
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        payment_reference = f"ORDER-{uuid4().hex[:12]}"

        # payload = {
        #     "accountReference": payment_reference,
        #     "accountName": customer_name,
        #     "currencyCode": "NGN",
        #     "contractCode": settings.MONNIFY_CONTRACT_CODE,
        #     "customerEmail": customer_email,
        #     "customerName": customer_name,
        #     "getAllAvailableBanks": True
        # }

        payload = {
            "accountReference": payment_reference,
            "accountName": customer_name,
            "currencyCode": "NGN",
            "contractCode": settings.MONNIFY_CONTRACT_CODE,
            "customerEmail": customer_email,
            "customerName": customer_name,
            "preferredBanks": ["232"], # Moniepoint bank code
            "getAllAvailableBanks": False  
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{MonnifyService.get_base_url()}/api/v2/bank-transfer/reserved-accounts",
                headers=headers,
                json=payload,
                timeout=30
            )

        print(f"Monnify Response Status: {response.status_code}")
        print(f"Monnify Response Body: {response.text}")
        response.raise_for_status()

        data = response.json()["responseBody"]
        account = data["accounts"][0]

        return {
            "payment_reference": data["accountReference"],
            "account_number": account["accountNumber"],
            "account_name": account["accountName"],
            "bank_name": account["bankName"],
            "amount": amount,
            "expires_at": datetime.utcnow() + timedelta(hours=1)
        }
    
    @staticmethod
    async def verify_payment(payment_reference: str) -> Dict[str, Any]:
        """Verify payment status"""
        access_token = await MonnifyService.get_access_token()
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.get(
                f"{MonnifyService.get_base_url()}/api/v2/transactions/{payment_reference}",
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            
            return response.json()["responseBody"]
            
        except requests.RequestException as e:
            raise Exception(f"Failed to verify payment: {str(e)}")