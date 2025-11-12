from typing import List, Dict, Optional, Any
from decimal import Decimal
from datetime import datetime, timedelta
import re
import uuid
import ssl
import resend
import os
import httpx
from uuid import uuid4
import random
import string
import hashlib
import json
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
import math
import requests
import base64

import pytz
NIGERIA_TZ = pytz.timezone('Africa/Lagos')

from datetime import datetime, timedelta
from ..database import supabase
from ..services.redis import redis_client
from ..core.cache import CacheKeys
from ..config import settings
from ..email_templates.email_templates import get_otp_email_template



resend.api_key = os.getenv("RESEND_API_KEY")




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
                "last_seen": datetime.utcnow().replace(tzinfo=pytz.UTC).astimezone(NIGERIA_TZ).isoformat()
            }).eq("id", existing.data[0]["id"]).execute()
            
            return existing.data[0]
        
        # Create new customer
        if not full_name:
            full_name = CustomerService.extract_name_from_email(email)
        
        customer_data = {
            "email": email,
            "full_name": full_name,
            "phone": phone,
            "last_seen": datetime.utcnow().replace(tzinfo=pytz.UTC).astimezone(NIGERIA_TZ).isoformat()
        }
        
        result = supabase.table("website_customers").insert(customer_data).execute()
        return result.data[0]
    
    @staticmethod
    def generate_pin() -> str:
        """Generate 4-digit PIN"""
        return ''.join(random.choices(string.digits, k=4))
    
    @staticmethod
    def send_login_pin(email: str) -> bool:
        pin = CustomerService.generate_pin()
        redis_client.set(f"login_pin:{email}", pin, 600)
        
        try:
            resend.Emails.send({
                "from": "noreply@lebanstreet.com",
                "to": email,
                "subject": "Your Verification Code",
                "html": get_otp_email_template(pin, email.split('@')[0].title())
            })
            print(f"✅ PIN sent to {email}: {pin}")
            return True
        except Exception as e:
            print(f"❌ Email send failed: {str(e)}")
            return False


    @staticmethod
    async def verify_pin(email: str, pin: str) -> bool:
        """Verify login PIN"""
        stored_pin = redis_client.get(f"login_pin:{email}")
        
        # 1. Convert to string if it exists (handles int/bytes/str)
        if stored_pin is None:
            return False

        # Ensure we have a string to strip/compare
        stored_pin_str = str(stored_pin)
        
        # 2. Perform stripping and comparison
        if stored_pin_str.strip() == pin.strip():
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
            "created_at": datetime.utcnow().replace(tzinfo=pytz.UTC).astimezone(NIGERIA_TZ).isoformat()
        }
        
        redis_client.set(f"customer_session:{session_token}", session_data, 60*60*24*365*5)
        
        return session_token

    

    @staticmethod
    async def check_email_and_handle_auth(email: str, phone: str = None, full_name: str = None) -> Dict[str, Any]:
        """Check if email exists and handle authentication accordingly"""
        existing = supabase.table("website_customers").select("*").eq("email", email).execute()
        
        if len(existing.data) > 0:
            # Email exists - send PIN for verification
            CustomerService.send_login_pin(email)
            
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
                "last_seen": datetime.utcnow().replace(tzinfo=pytz.UTC).astimezone(NIGERIA_TZ).isoformat()
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
    
        

    @staticmethod
    def calculate_delivery_estimate(order_items: List[Dict], delivery_area_time: str) -> Dict[str, Any]:
        """
        Calculate total delivery estimate
        - Cooking time = longest prep time (kitchen cooks in parallel)
        - Delivery time = area's estimated time
        - Total = cooking + delivery
        
        Args:
            order_items: List of items (needs product_id to fetch prep times)
            delivery_area_time: String like "20-30 minutes"
        
        Returns:
            {
                "cooking_time_minutes": int,
                "delivery_time_range": str,
                "total_estimate_min": int,
                "total_estimate_max": int,
                "total_estimate_display": str
            }
        """
        import re
        
        # Fetch preparation times from database
        product_ids = [item.get("product_id") for item in order_items if item.get("product_id")]
        
        cooking_time = 15  # Default fallback
        
        if product_ids:
            # Batch fetch all product prep times
            products = supabase.table("products").select(
                "id, preparation_time_minutes"
            ).in_("id", product_ids).execute()
            
            # Create prep time map
            prep_time_map = {
                p["id"]: p.get("preparation_time_minutes", 15) 
                for p in products.data
            }
            
            # Find longest cooking time (parallel cooking)
            prep_times = [
                prep_time_map.get(item.get("product_id"), 15) 
                for item in order_items
            ]
            cooking_time = max(prep_times) if prep_times else 15
        
        # Parse delivery time range (e.g., "20-30 minutes" or "25 minutes")
        time_numbers = re.findall(r'\d+', delivery_area_time)
        
        if len(time_numbers) >= 2:
            delivery_min = int(time_numbers[0])
            delivery_max = int(time_numbers[1])
        elif len(time_numbers) == 1:
            delivery_min = delivery_max = int(time_numbers[0])
        else:
            # Default if parsing fails
            delivery_min = delivery_max = 30
        
        # Calculate total estimates
        total_min = cooking_time + delivery_min
        total_max = cooking_time + delivery_max
        
        return {
            "cooking_time_minutes": cooking_time,
            "delivery_time_range": delivery_area_time,
            "delivery_time_min": delivery_min,
            "delivery_time_max": delivery_max,
            "total_estimate_min": total_min,
            "total_estimate_max": total_max,
            "total_estimate_display": f"{total_max} minutes"
            # "total_estimate_display": f"{total_min}-{total_max} minutes"
        }

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
    async def calculate_checkout_total(orders: List[Dict]) -> Dict[str, Any]:
        """Single source of truth for all checkout calculations"""
        total_subtotal = Decimal('0')
        total_vat = Decimal('0')
        delivery_fees_by_area = {}
        
        for order in orders:
            processed_items = await CartService.validate_cart_items(order.get("items", []))
            totals = CartService.calculate_order_total(processed_items)
            
            total_subtotal += totals["subtotal"]
            total_vat += totals["tax"]
            
            address = supabase.table("customer_addresses").select(
                "area_id, delivery_areas(delivery_fee)"
            ).eq("id", order.get("delivery_address_id")).execute()
            
            if not address.data:
                raise ValueError("Address not found")
            
            area_id = address.data[0]["area_id"]
            if area_id not in delivery_fees_by_area:
                # delivery_fees_by_area[area_id] = Decimal(str(address.data[0]["delivery_areas"]["delivery_fee"]))
                delivery_fees_by_area[area_id] = Decimal(str(address.data[0]["delivery_areas"]["delivery_fee"] or 0))
                
        
        total_delivery = sum(delivery_fees_by_area.values())
        grand_total = total_subtotal + total_vat + total_delivery
        
        return {
            "subtotal": total_subtotal,  # Return Decimal
            "vat": total_vat,
            "delivery": total_delivery,
            "total": grand_total,
            # Also include float versions for JSON response
            "subtotal_float": float(total_subtotal),
            "vat_float": float(total_vat),
            "delivery_float": float(total_delivery),
            "total_float": float(grand_total)
        }

    
    
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
        
        
        street_address = address_data.get("street_address") or address_data.get("address") or address_data.get("full_address", "")
        
        full_address = f"{street_address}, {area.data[0]['name']}"
        
        address_entry = {
            "customer_id": customer_id,
            "name": address_data.get("name", "N/A"),
            "area_id": address_data["area_id"],
            "street_address": street_address, # Save the street part explicitly
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


    class TLSAdapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            ctx = ssl.create_default_context()
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            kwargs['ssl_context'] = ctx
            return super().init_poolmanager(*args, **kwargs)



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
        
        ssl_context = ssl.create_default_context()
        ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
        
        async with httpx.AsyncClient(verify=ssl_context, timeout=30.0) as client:
            response = await client.post(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            print(f"DEBUG Access Token Response: {data}")
            return data["responseBody"]["accessToken"]


    
    
    

    @staticmethod
    async def create_virtual_account(
        amount: Decimal,
        customer_email: str,
        customer_name: str,
        customer_phone: str,
        payment_reference: str
    ) -> Dict[str, Any]:
        access_token = await MonnifyService.get_access_token()
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        # Check if customer already has a reserved account
        account_reference = f"CUST-{customer_email.split('@')[0]}"
        
        # SSL context
        ssl_context = ssl.create_default_context()
        ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
        
        # Try to get existing account first
        async with httpx.AsyncClient(verify=ssl_context, timeout=30.0) as client:
            try:
                get_response = await client.get(
                    f"{MonnifyService.get_base_url()}/api/v2/bank-transfer/reserved-accounts/{account_reference}",
                    headers=headers
                )
                
                if get_response.status_code == 200:
                    # Account exists, return it
                    data = get_response.json()["responseBody"]
                    account = data["accounts"][0]
                    
                    return {
                        "payment_reference": payment_reference,
                        "account_reference": account_reference,
                        "account_number": account["accountNumber"],
                        "account_name": account["accountName"],
                        "bank_name": account["bankName"],
                        "amount": amount,
                        "expires_at": datetime.utcnow().replace(tzinfo=pytz.UTC).astimezone(NIGERIA_TZ) + timedelta(minutes=5)
                    }
            except:
                pass  # Account doesn't exist, create new one

        # Create new account
        payload = {
            "accountReference": account_reference,
            "accountName": "LEBANST KITCHEN",
            "currencyCode": "NGN",
            "contractCode": settings.MONNIFY_CONTRACT_CODE,
            "customerEmail": customer_email,
            "customerName": customer_name,
            "preferredBanks": ["50515"], 
            "getAllAvailableBanks": False
        }

        async with httpx.AsyncClient(verify=ssl_context, timeout=30.0) as client:
            response = await client.post(
                f"{MonnifyService.get_base_url()}/api/v2/bank-transfer/reserved-accounts",
                headers=headers,
                json=payload
            )

        response.raise_for_status()
        data = response.json()["responseBody"]
        account = data["accounts"][0]

        return {
            "payment_reference": payment_reference,
            "account_reference": account_reference,
            "account_number": account["accountNumber"],
            "account_name": account["accountName"],
            "bank_name": account["bankName"],
            "amount": amount,
            "expires_at": datetime.utcnow() + timedelta(hours=1)
        }




    
   
        


    @staticmethod
    async def verify_payment(account_reference: str) -> Dict[str, Any]:
        """Verify payment status by checking account transactions"""
        access_token = await MonnifyService.get_access_token()
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        # Create session with TLS adapter
        session = requests.Session()
        session.mount('https://', MonnifyService.TLSAdapter())
        
        try:
            # Get account details which includes transaction info
            account_response = session.get(
                f"{MonnifyService.get_base_url()}/api/v2/bank-transfer/reserved-accounts/{account_reference}",
                headers=headers,
                timeout=30
            )
            
            print(f"📊 Account Response: {account_response.text}")
            
            if account_response.status_code == 200:
                data = account_response.json()["responseBody"]
                
                # Check if there are transactions
                if data.get("transactionCount", 0) > 0 and data.get("totalAmount", 0) > 0:
                    # Account has transactions - payment is PAID
                    return {
                        "paymentStatus": "PAID",
                        "transactionReference": account_reference,
                        "amountPaid": data.get("totalAmount"),
                        "paidOn": data.get("createdOn")
                    }
            
            return {"paymentStatus": "PENDING"}
            
        except Exception as e:
            print(f"❌ Verification error: {str(e)}")
            return {"paymentStatus": "PENDING"}


    @staticmethod
    async def process_webhook_payment(payload: Dict, account_reference: str, transaction_reference: str):
        """Background task for webhook processing"""
        try:
            payment_status = payload.get("paymentStatus")
            
            # Only process PAID status
            if payment_status != "PAID":
                return
            
            # Get payment session
            payment_session = redis_client.get(f"payment:{account_reference}")
            
            if not payment_session:
                print(f"⚠️ Payment session not found: {account_reference}")
                return
            
            # Check if already completed
            if payment_session.get("status") == "completed":
                print(f"ℹ️ Payment already completed: {account_reference}")
                return
            
            # Update session with webhook data
            payment_session["webhook_status"] = payment_status
            payment_session["webhook_data"] = payload
            payment_session["transaction_reference"] = transaction_reference
            payment_session["webhook_received_at"] = datetime.utcnow().replace(tzinfo=pytz.UTC).astimezone(NIGERIA_TZ).isoformat()
            
            redis_client.set(f"payment:{account_reference}", payment_session, 3600)
            
            # Mark as fully processed
            redis_client.set(f"webhook_processed:{transaction_reference}", "completed", 86400)  # 24 hours
            
            print(f"✅ Webhook processed successfully: {transaction_reference}")
            
        except Exception as e:
            print(f"❌ Webhook processing error: {str(e)}")
            # Remove processing lock so it can be retried
            redis_client.delete(f"webhook_processed:{transaction_reference}")

    
    @staticmethod
    def verify_monnify_signature(payload: dict, signature: str) -> bool:
        payload_string = json.dumps(payload, separators=(",", ":"))
        computed_hash = hashlib.sha512(
            (settings.MONNIFY_SECRET_KEY + payload_string).encode()
        ).hexdigest()
        return computed_hash == signature
    




class EmailService:
    @staticmethod
    async def send_welcome_email_task(customer_id: str, customer_email: str, customer_name: str):
        """Background task to send welcome email"""
        try:
            
            orders = supabase.table("orders").select("id").eq("website_customer_id", customer_id).eq("payment_status", "paid").execute()
            
            if len(orders.data) != 1:  
                print(f"ℹ️ Not first order for {customer_email}, welcome email skipped.")
                return
            
            # Check if already sent
            email_sent_key = f"welcome_email_sent:{customer_id}"
            if redis_client.get(email_sent_key):
                print(f"ℹ️ Welcome email already sent to {customer_email}, skipped.")
                return
            
            
            logo_insta_svg = "data:image/svg+xml;base64,PHN2ZyBmaWxsPSIjMDAwMDAwIiB3aWR0aD0iODAwcHgiIGhlaWdodD0iODAwcHgiIHZpZXdCb3g9IjAgMCAzMiAzMiIgaWQ9IkNhbWFkYV8xIiB2ZXJzaW9uPSIxLjEiIHhtbDpzcGFjZT0icHJlc2VydmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyIgeG1sbnM6eGxpbms9Imh0dHA6Ly93d3cudzMub3JnLzE5OTkveGxpbmsiPjxnPjxwYXRoIGQ9Ik0yMi4zLDguNGMtMC44LDAtMS40LDAuNi0xLjQsMS40YzAsMC44LDAuNiwxLjQsMS40LDEuNGMwLjgsMCwxLjQtMC42LDEuNC0xLjRDMjMuNyw5LDIzLjEsOC40LDIyLjMsOC40eiIvPjxwYXRoIGQ9Ik0xNiwxMC4yYy0zLjMsMC01LjksMi43LTUuOSw1LjlzMi43LDUuOSw1LjksNS45czUuOS0yLjcsNS45LTUuOVMxOS4zLDEwLjIsMTYsMTAuMnogTTE2LDE5LjljLTIuMSwwLTMuOC0xLjctMy44LTMuOGMwLTIuMSwxLjctMy44LDMuOC0zLjhjMi4xLDAsMy44LDEuNywzLjgsMy44QzE5LjgsMTguMiwxOC4xLDE5LjksMTYsMTkuOXoiLz48cGF0aCBkPSJNMjAuOCw0aC05LjVDNy4yLDQsNCw3LjIsNCwxMS4ydjkuNWMwLDQsMy4yLDcuMiw3LjIsNy4yaDkuNWM0LDAsNy4yLTMuMiw3LjItNy4ydi05LjVDMjgsNy4yLDI0LjgsNCwyMC44LDR6IE0yNS43LDIwLjhjMCwyLjctMi4yLDUtNSw1aC05LjVjLTIuNywwLTUtMi4yLTUtNXYtOS41YzAtMi43LDIuMi01LDUtNWg5LjVjMi43LDAsNSwyLjIsNSw1VjIwLjh6Ii8+PC9nPjwvc3ZnPg=="

            
            
            html_content = f"""
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Welcome to Leban Street!</title>
                <style>
                    body {{
                        margin: 0;
                        padding: 0;
                        background-color: #f4f4f4;
                        font-family: Arial, sans-serif;
                    }}
                    .container {{
                        width: 100%;
                        max-width: 600px;
                        margin: 0 auto;
                        padding: 20px;
                    }}
                    .card {{
                        background-color: #ffffff;
                        border-radius: 16px;
                        overflow: hidden;
                        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
                    }}
                    .header {{
                        text-align: center;
                        padding: 40px 20px 20px 20px;
                    }}
                    .content {{
                        padding: 20px 40px 30px 40px;
                        color: #333333;
                        font-size: 16px;
                        line-height: 1.6;
                    }}
                    .content h1 {{
                        color: #000000;
                        font-size: 24px;
                        margin-top: 0;
                        margin-bottom: 20px;
                    }}
                    .content p {{
                        margin-bottom: 20px;
                    }}
                    .cta-button {{
                        background-color: #FE1B01;
                        color: #ffffff;
                        padding: 14px 28px;
                        text-decoration: none;
                        border-radius: 8px;
                        display: inline-block;
                        font-weight: bold;
                        font-size: 16px;
                    }}
                    .footer {{
                        text-align: center;
                        padding: 30px 20px;
                        color: #777777;
                        font-size: 12px;
                    }}
                    .socials img {{
                        width: 24px;
                        height: 24px;
                        margin: 0 10px;
                    }}
                </style>
            </head>
            <body style="margin: 0; padding: 0; background-color: #f4f4f4; font-family: Arial, sans-serif;">
                <table class="container" cellpadding="0" cellspacing="0" border="0" style="width: 100%; max-width: 600px; margin: 0 auto; padding: 20px;">
                    <tr>
                        <td>
                            <table class="card" cellpadding="0" cellspacing="0" border="0" style="width: 100%; background-color: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.05);">
                                <tr>
                                    <td class="header" style="text-align: center; padding: 40px 20px 20px 20px;">
                                        <div class="logo">
                                            <svg width="61" height="72" viewBox="0 0 61 72" fill="none" xmlns="http://www.w3.org/2000/svg">
                                                <path d="M19.447 71.0973C13.3529 71.0973 7.07968 71.3943 2.38965 71.8993C0.597282 72.1074 -0.298902 71.216 0.089445 69.4333C1.07525 63.6696 3.16634 50.8942 3.16634 36.9004C3.16634 22.9069 1.10512 10.2204 0.089445 4.57541C-0.209282 2.70366 0.6869 1.6935 2.47927 1.9906C4.48074 2.28772 6.57183 2.49568 9.94745 2.49568C13.5322 2.49568 15.6233 2.28772 17.7144 1.90147C19.5964 1.6935 20.612 2.70366 20.1938 4.57541C19.208 10.1313 17.1169 23.0256 17.1169 36.9004C17.1169 43.4367 18.7002 58.9159 18.7002 58.9159C22.494 58.9159 49.5886 59.2131 59.0881 52.9738C60.1934 52.1715 60.6714 51.7854 60.7909 51.7854L61 51.8745C60.1038 57.7275 60.0142 63.5804 60.6116 69.5225C60.8208 71.3051 60.0142 72.1074 58.1322 71.9885C48.8717 71.3051 25.7203 71.0973 19.447 71.0973ZM26.4074 52.3499C24.7046 52.3499 23.8084 51.4587 24.0175 49.765C24.4058 46.2889 24.615 42.1294 24.615 38.6533C24.5253 36.5737 25.5112 36.0684 27.2139 37.0787C31.0078 39.0692 36.4744 41.0302 39.3722 41.0302C42.5686 41.0302 45.257 40.0498 45.257 37.5541C45.257 35.0583 38.5656 32.2062 33.6962 28.9379C27.0048 24.3626 23.7188 20.322 23.7188 14.0531C23.7188 5.25876 32.5013 0 43.1661 0C48.6625 0 51.142 0.891314 55.1152 0.802183C56.8177 0.802183 57.7139 1.60437 57.5048 3.38699C57.1165 7.16023 56.8177 12.419 56.9074 16.5785C56.997 18.8662 56.0112 19.1633 54.4281 17.5589C50.7537 13.9936 46.9598 12.003 44.1517 12.003C41.1646 12.003 38.8643 13.4886 38.8643 15.6574C38.8643 18.4205 43.9426 20.4111 48.4236 23.085C54.3982 26.7394 60.3727 31.3148 60.3727 38.2672C60.3727 46.8831 52.1876 53.0332 40.1489 53.0332C34.6522 53.0332 30.7689 52.439 26.3775 52.3499H26.4074Z" fill="#FF0000"/>
                                                </svg>
                                        </div>
                                    </td>
                                </tr>
                                <tr>
                                    <td class="content" style="padding: 20px 40px 30px 40px; color: #333333; font-size: 16px; line-height: 1.6;">
                                        <h1 style="color: #000000; font-size: 24px; margin-top: 0; margin-bottom: 20px;">Welcome to Leban Street!</h1>
                                        <p style="margin-bottom: 20px;">Hi there,</p>
                                        <p style="margin-bottom: 20px;">We’re so excited you chose us for your first order and we can’t wait for you to enjoy the bold, authentic flavors we’re known for.</p>
                                        <p style="margin-bottom: 20px;">At Leban Street, we’re all about great food, good vibes, and keeping things fresh. New dishes and special offers drop regularly, so make sure to check back soon (or follow us on social media so you never miss a thing).</p>
                                        <p style="margin-bottom: 30px;">Thanks again for joining the family, we’re glad to have you at our table.</p>
                                        <p style="margin-bottom: 20px;">Warmly,<br>The Leban Street Team</p>
                                    </td>
                                </tr>
                                <tr>
                                    <td style="padding-bottom: 40px; text-align: center;">
                                        <a href="https://lebanstreet.com" target="_blank" class="cta-button" style="background-color: #FE1B01; color: #ffffff; padding: 14px 28px; text-decoration: none; border-radius: 8px; display: inline-block; font-weight: bold; font-size: 16px;">
                                            Order Again
                                        </a>
                                    </td>
                                </tr>
                            </table>
                            </td>
                    </tr>
                    <tr>
                        <td class="footer" style="text-align: center; padding: 30px 20px; color: #777777; font-size: 12px;">
                            <div class="socials" style="margin-bottom: 15px;">
                                <a href="https://x.com/LebanStreetNG" target="_blank" style="text-decoration: none;">
                                    <img src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA1MCA1MCIgd2lkdGg9IjUwcHgiIGhlaWdodD0iNTBweCI+PHBhdGggZmlsbD0iIzAwMDAwMCIgZD0iTSA2LjkxOTkyMTkgNiBMIDIxLjEzNjcxOSAyNi43MjY1NjIgTCA2LjIyODUxNTYgNDQgTCA5LjQwNjI5IDQ0IEwgMjIuNTQ0OTIyIDI4Ljc3NzM0NCBMIDMyLjk4NjMyOCA0NCBMIDQzIDQ4IEwgMjguMTIzMDQ3IDIyLjMxMjUgTCA0Mi4yMDMxMjUgNiBMIDM5LjAyNzM0NCA2IEwgMjYuNzE2Nzk3IDIwLjI2MTcxOSBMIDE2LjkzMzU5NCA2IEwgNi45MTk5MjE5IDYgeiIvPjwvc3ZnPg==" alt="X" style="width: 24px; height: 24px; margin: 0 10px;">
                                </a>
                                <a href="https://instagram.com/lebanstreet.ng" target="_blank" style="text-decoration: none;">
                                    <img src="{logo_insta_svg}" alt="Instagram" style="width: 24px; height: 24px; margin: 0 10px;">
                                </a>
                            </div>
                            <p style="margin: 5px 0;">&copy; {datetime.now().year} Leban Street. All rights reserved.</p>
                            <a href="https://lebanstreet.com" target="_blank" style="color: #FE1B01; text-decoration: none; font-weight: bold;">lebanstreet.com</a>
                        </td>
                    </tr>
                </table>
            </body>
            </html>
            """
            
            resend.api_key = os.getenv("RESEND_API_KEY") 
            
            resend.Emails.send({
                "from": "noreply@lebanstreet.com",
                "to": customer_email,
                "subject": "Welcome to Leban Street!", 
                "html": html_content
            })
            
            # Mark as sent
            redis_client.set(email_sent_key, "true", 86400 * 365)  # 1 year
            
            print(f"✅ Welcome email sent to {customer_email}")
            
        except Exception as e:
            print(f"❌ Welcome email failed for {customer_email}: {str(e)}")



    @staticmethod
    def _get_base_email_template(title: str, content: str, cta_text: str = None, cta_link: str = None) -> str:
        """Base email template with header, footer, and styling"""
        logo_insta_svg = "data:image/svg+xml;base64,PHN2ZyBmaWxsPSIjMDAwMDAwIiB3aWR0aD0iODAwcHgiIGhlaWdodD0iODAwcHgiIHZpZXdCb3g9IjAgMCAzMiAzMiIgaWQ9IkNhbWFkYV8xIiB2ZXJzaW9uPSIxLjEiIHhtbDpzcGFjZT0icHJlc2VydmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyIgeG1sbnM6eGxpbms9Imh0dHA6Ly93d3cudzMub3JnLzE5OTkveGxpbmsiPjxnPjxwYXRoIGQ9Ik0yMi4zLDguNGMtMC44LDAtMS40LDAuNi0xLjQsMS40YzAsMC44LDAuNiwxLjQsMS40LDEuNGMwLjgsMCwxLjQtMC42LDEuNC0xLjRDMjMuNyw5LDIzLjEsOC40LDIyLjMsOC40eiIvPjxwYXRoIGQ9Ik0xNiwxMC4yYy0zLjMsMC01LjksMi43LTUuOSw1LjlzMi43LDUuOSw1LjksNS45czUuOS0yLjcsNS45LTUuOVMxOS4zLDEwLjIsMTYsMTAuMnogTTE2LDE5LjljLTIuMSwwLTMuOC0xLjctMy44LTMuOGMwLTIuMSwxLjctMy44LDMuOC0zLjhjMi4xLDAsMy44LDEuNywzLjgsMy44QzE5LjgsMTguMiwxOC4xLDE5LjksMTYsMTkuOXoiLz48cGF0aCBkPSJNMjAuOCw0aC05LjVDNy4yLDQsNCw3LjIsNCwxMS4ydjkuNWMwLDQsMy4yLDcuMiw3LjIsNy4yaDkuNWM0LDAsNy4yLTMuMiw3LjItNy4ydi05LjVDMjgsNy4yLDI0LjgsNCwyMC44LDR6IE0yNS43LDIwLjhjMCwyLjctMi4yLDUtNSw1aC05LjVjLTIuNywwLTUtMi4yLTUtNXYtOS41YzAtMi43LDIuMi01LDUtNWg5LjVjMi43LDAsNSwyLjIsNSw1VjIwLjh6Ii8+PC9nPjwvc3ZnPg=="
        
        cta_button = ""
        if cta_text and cta_link:
            cta_button = f"""
            <tr>
                <td style="padding-bottom: 40px; text-align: center;">
                    <a href="{cta_link}" target="_blank" class="cta-button" style="background-color: #FE1B01; color: #ffffff; padding: 14px 28px; text-decoration: none; border-radius: 8px; display: inline-block; font-weight: bold; font-size: 16px;">
                        {cta_text}
                    </a>
                </td>
            </tr>
            """
        
        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{title}</title>
            <style>
                body {{
                    margin: 0;
                    padding: 0;
                    background-color: #f4f4f4;
                    font-family: Arial, sans-serif;
                }}
                .container {{
                    width: 100%;
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                .card {{
                    background-color: #ffffff;
                    border-radius: 16px;
                    overflow: hidden;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.05);
                }}
                .header {{
                    text-align: center;
                    padding: 40px 20px 20px 20px;
                }}
                .content {{
                    padding: 20px 40px 30px 40px;
                    color: #333333;
                    font-size: 16px;
                    line-height: 1.6;
                }}
                .content h1 {{
                    color: #000000;
                    font-size: 24px;
                    margin-top: 0;
                    margin-bottom: 20px;
                }}
                .content p {{
                    margin-bottom: 20px;
                }}
                .cta-button {{
                    background-color: #FE1B01;
                    color: #ffffff;
                    padding: 14px 28px;
                    text-decoration: none;
                    border-radius: 8px;
                    display: inline-block;
                    font-weight: bold;
                    font-size: 16px;
                }}
                .footer {{
                    text-align: center;
                    padding: 30px 20px;
                    color: #777777;
                    font-size: 12px;
                }}
                .socials img {{
                    width: 24px;
                    height: 24px;
                    margin: 0 10px;
                }}
            </style>
        </head>
        <body style="margin: 0; padding: 0; background-color: #f4f4f4; font-family: Arial, sans-serif;">
            <table class="container" cellpadding="0" cellspacing="0" border="0" style="width: 100%; max-width: 600px; margin: 0 auto; padding: 20px;">
                <tr>
                    <td>
                        <table class="card" cellpadding="0" cellspacing="0" border="0" style="width: 100%; background-color: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.05);">
                            <tr>
                                <td class="header" style="text-align: center; padding: 40px 20px 20px 20px;">
                                    <div class="logo">
                                        <svg width="61" height="72" viewBox="0 0 61 72" fill="none" xmlns="http://www.w3.org/2000/svg">
                                            <path d="M19.447 71.0973C13.3529 71.0973 7.07968 71.3943 2.38965 71.8993C0.597282 72.1074 -0.298902 71.216 0.089445 69.4333C1.07525 63.6696 3.16634 50.8942 3.16634 36.9004C3.16634 22.9069 1.10512 10.2204 0.089445 4.57541C-0.209282 2.70366 0.6869 1.6935 2.47927 1.9906C4.48074 2.28772 6.57183 2.49568 9.94745 2.49568C13.5322 2.49568 15.6233 2.28772 17.7144 1.90147C19.5964 1.6935 20.612 2.70366 20.1938 4.57541C19.208 10.1313 17.1169 23.0256 17.1169 36.9004C17.1169 43.4367 18.7002 58.9159 18.7002 58.9159C22.494 58.9159 49.5886 59.2131 59.0881 52.9738C60.1934 52.1715 60.6714 51.7854 60.7909 51.7854L61 51.8745C60.1038 57.7275 60.0142 63.5804 60.6116 69.5225C60.8208 71.3051 60.0142 72.1074 58.1322 71.9885C48.8717 71.3051 25.7203 71.0973 19.447 71.0973ZM26.4074 52.3499C24.7046 52.3499 23.8084 51.4587 24.0175 49.765C24.4058 46.2889 24.615 42.1294 24.615 38.6533C24.5253 36.5737 25.5112 36.0684 27.2139 37.0787C31.0078 39.0692 36.4744 41.0302 39.3722 41.0302C42.5686 41.0302 45.257 40.0498 45.257 37.5541C45.257 35.0583 38.5656 32.2062 33.6962 28.9379C27.0048 24.3626 23.7188 20.322 23.7188 14.0531C23.7188 5.25876 32.5013 0 43.1661 0C48.6625 0 51.142 0.891314 55.1152 0.802183C56.8177 0.802183 57.7139 1.60437 57.5048 3.38699C57.1165 7.16023 56.8177 12.419 56.9074 16.5785C56.997 18.8662 56.0112 19.1633 54.4281 17.5589C50.7537 13.9936 46.9598 12.003 44.1517 12.003C41.1646 12.003 38.8643 13.4886 38.8643 15.6574C38.8643 18.4205 43.9426 20.4111 48.4236 23.085C54.3982 26.7394 60.3727 31.3148 60.3727 38.2672C60.3727 46.8831 52.1876 53.0332 40.1489 53.0332C34.6522 53.0332 30.7689 52.439 26.3775 52.3499H26.4074Z" fill="#FF0000"/>
                                        </svg>
                                    </div>
                                </td>
                            </tr>
                            <tr>
                                <td class="content" style="padding: 20px 40px 30px 40px; color: #333333; font-size: 16px; line-height: 1.6;">
                                    {content}
                                </td>
                            </tr>
                            {cta_button}
                        </table>
                    </td>
                </tr>
                <tr>
                    <td class="footer" style="text-align: center; padding: 30px 20px; color: #777777; font-size: 12px;">
                        <div class="socials" style="margin-bottom: 15px;">
                            <a href="https://x.com/LebanStreetNG" target="_blank" style="text-decoration: none;">
                                <img src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA1MCA1MCIgd2lkdGg9IjUwcHgiIGhlaWdodD0iNTBweCI+PHBhdGggZmlsbD0iIzAwMDAwMCIgZD0iTSA2LjkxOTkyMTkgNiBMIDIxLjEzNjcxOSAyNi43MjY1NjIgTCA2LjIyODUxNTYgNDQgTCA5LjQwNjI5IDQ0IEwgMjIuNTQ0OTIyIDI4Ljc3NzM0NCBMIDMyLjk4NjMyOCA0NCBMIDQzIDQ4IEwgMjguMTIzMDQ3IDIyLjMxMjUgTCA0Mi4yMDMxMjUgNiBMIDM5LjAyNzM0NCA2IEwgMjYuNzE2Nzk3IDIwLjI2MTcxOSBMIDE2LjkzMzU5NCA2IEwgNi45MTk5MjE5IDYgeiIvPjwvc3ZnPg==" alt="X" style="width: 24px; height: 24px; margin: 0 10px;">
                            </a>
                            <a href="https://instagram.com/lebanstreet.ng" target="_blank" style="text-decoration: none;">
                                <img src="{logo_insta_svg}" alt="Instagram" style="width: 24px; height: 24px; margin: 0 10px;">
                            </a>
                        </div>
                        <p style="margin: 5px 0;">&copy; {datetime.now().year} Leban Street. All rights reserved.</p>
                        <a href="https://lebanstreet.com" target="_blank" style="color: #FE1B01; text-decoration: none; font-weight: bold;">lebanstreet.com</a>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """



    @staticmethod
    async def send_order_confirmation_batch(customer_email: str, orders: List[Dict]):
        """Send single email with all orders from same payment"""
        try:
            all_item_rows = ""
            total_subtotal = 0
            total_tax = 0
            total_delivery = 0
            grand_total = 0
            order_numbers = []
            
            for order_data in orders:
                order_numbers.append(order_data["order_number"])
                
                # Fetch items for this order
                items_result = supabase.table("order_items").select("*").eq("order_id", order_data["id"]).execute()
                items = items_result.data or []
                
                # Add order header
                all_item_rows += f"""
                <tr>
                    <td colspan="2" style="padding: 15px 0 10px 0; font-weight: bold; font-size: 16px; color: #FE1B01;">
                        Order {order_data['order_number']}
                    </td>
                </tr>
                """
                
                # Add items for this order
                for item in items:
                    all_item_rows += f"""
                    <tr>
                        <td style="padding: 8px 0 8px 15px; text-align: left; border-bottom: 1px solid #eeeeee;">
                            {item['product_name']} (x{item['quantity']})
                        </td>
                        <td style="padding: 8px 0; text-align: right; border-bottom: 1px solid #eeeeee; font-weight: bold;">
                            ₦{item['total_price']:,.2f}
                        </td>
                    </tr>
                    """
                
                # Accumulate totals
                total_subtotal += order_data.get("subtotal", 0)
                total_tax += order_data.get("tax", 0)
                total_delivery += order_data.get("delivery_fee", 0)
                grand_total += order_data.get("total", 0)
            
            # Fetch delivery address from first order
            delivery_address = "N/A"
            if orders and orders[0].get("delivery_address_id"):
                address_result = supabase.table("customer_addresses").select("full_address").eq("id", orders[0]["delivery_address_id"]).execute()
                if address_result.data:
                    delivery_address = address_result.data[0]["full_address"]
            
            # Build email content
            content = f"""
            <h1 style="color: #000000; font-size: 24px; margin-top: 0; margin-bottom: 20px;">Your Orders are Confirmed!</h1>
            <p style="margin-bottom: 20px;">Hi there,</p>
            <p style="margin-bottom: 20px;">Thanks for your orders! We've received them and our chefs are getting started. Your Order IDs: <strong>{', '.join(order_numbers)}</strong>.</p>
            <p style="margin-bottom: 20px;">We will notify you again as soon as your orders are sent out for delivery.</p>
            
            <div class="summary-bubble" style="background-color: #f9f9f9; border-radius: 8px; padding: 20px; margin-top: 20px; margin-bottom: 20px; border: 1px solid #eeeeee;">
                <h2 style="font-size: 20px; color: #000; margin-top: 0; margin-bottom: 15px;">Order Summary</h2>
                
                <table class="order-summary" cellpadding="0" cellspacing="0" border="0" style="width: 100%; border-collapse: collapse; margin-bottom: 10px;">
                    <thead>
                        <tr>
                            <th style="padding: 12px 0; text-align: left; border-bottom: 1px solid #eeeeee; color: #777; font-size: 14px; text-transform: uppercase;">Item</th>
                            <th style="padding: 12px 0; text-align: right; border-bottom: 1px solid #eeeeee; color: #777; font-size: 14px; text-transform: uppercase;">Price</th>
                        </tr>
                    </thead>
                    <tbody>
                        {all_item_rows}
                    </tbody>
                </table>

                <table class="totals-summary" cellpadding="0" cellspacing="0" border="0" style="width: 100%; margin-bottom: 0;">
                    <tbody>
                        <tr>
                            <td class="label" style="padding: 5px 0; color: #555555;">Subtotal</td>
                            <td class="value" style="padding: 5px 0; text-align: right; font-weight: bold; color: #000000;">₦{total_subtotal:,.2f}</td>
                        </tr>
                        <tr>
                            <td class="label" style="padding: 5px 0; color: #555555;">VAT</td>
                            <td class="value" style="padding: 5px 0; text-align: right; font-weight: bold; color: #000000;">₦{total_tax:,.2f}</td>
                        </tr>
                        <tr>
                            <td class="label" style="padding: 5px 0; color: #555555;">Delivery Fee</td>
                            <td class="value" style="padding: 5px 0; text-align: right; font-weight: bold; color: #000000;">₦{total_delivery:,.2f}</td>
                        </tr>
                        <tr class="grand-total">
                            <td class="label" style="padding: 5px 0; color: #555555; padding-top: 10px; font-size: 18px; border-top: 2px solid #333333;"><strong>Total</strong></td>
                            <td class="value" style="padding: 5px 0; text-align: right; font-weight: bold; color: #000000; padding-top: 10px; font-size: 18px; border-top: 2px solid #333333;"><strong>₦{grand_total:,.2f}</strong></td>
                        </tr>
                    </tbody>
                </table>
            </div>
            
            <div class="address-box" style="background-color: #f9f9f9; padding: 20px; border-radius: 8px; margin-top: 20px; border: 1px solid #eeeeee;">
                <h3 style="margin-top: 0; margin-bottom: 10px; font-size: 16px; color: #000;">Delivering To</h3>
                <p style="margin: 0; line-height: 1.5; color: #333;">
                    {delivery_address}
                </al>
            </div>
            """
            
            # Get full HTML template
            html_content = EmailService._get_base_email_template(
                title=f"Your Leban Street Orders are Confirmed!",
                content=content,
                cta_text="Track your orders",
                cta_link="https://www.lebanstreet.com/track-order"
            )
            
            resend.api_key = os.getenv("RESEND_API_KEY")
            resend.Emails.send({
                "from": "noreply@lebanstreet.com",
                "to": customer_email,
                "subject": f"Your Leban Street Order is Confirmed! ({', '.join(order_numbers)})",
                "html": html_content
            })
            print(f"✅ Batch order confirmation sent to {customer_email}")

        except Exception as e:
            print(f"❌ Batch order confirmation email failed for {customer_email}: {str(e)}")




    @staticmethod
    async def send_ready_for_delivery(customer_email: str, order_number: str):
        """Notify customer order is ready for delivery"""
        try:
            # 1. Fetch order and related delivery info
            order_result = supabase.table("orders").select(
                "*, customer_addresses(full_address, delivery_areas(estimated_time))"
            ).eq("order_number", order_number).execute()
            
            if not order_result.data:
                print(f"❌ Could not find order {order_number} to send delivery email.")
                return

            order_data = order_result.data[0]
            
            # 2. Extract address and time
            delivery_address = "N/A"
            estimated_time = "30-45 minutes" # Fallback

            if order_data.get("customer_addresses"):
                delivery_address = order_data["customer_addresses"]["full_address"]
                if order_data["customer_addresses"].get("delivery_areas"):
                    estimated_time = order_data["customer_addresses"]["delivery_areas"]["estimated_time"]
            
            # 3. Build content
            content = f"""
            <h1 style="color: #000000; font-size: 24px; margin-top: 0; margin-bottom: 20px;">Your Order is Out for Delivery!</h1>
            <p style="margin-bottom: 20px;">Hi there,</p>
            <p style="margin-bottom: 20px;">Get ready! Your order <strong>{order_number}</strong> has left our kitchen and is on its way to you right now.</p>
            
            <div class="address-box" style="background-color: #f9f9f9; padding: 20px; border-radius: 8px; margin-top: 20px; border: 1px solid #eeeeee;">
                <h3 style="margin-top: 0; margin-bottom: 10px; font-size: 16px; color: #000;">Delivering To</h3>
                <p style="margin: 0; line-height: 1.5; color: #333;">
                    {delivery_address}
                </p>
            </div>

            <div class="estimate-box" style="background-color: #FFF8F7; border: 1px solid #FDDAD7; padding: 20px; border-radius: 8px; margin-top: 20px; text-align: center;">
                <h3 style="margin-top: 0; margin-bottom: 10px; font-size: 16px; color: #000;">Estimated Arrival</h3>
                <p style="font-size: 20px; font-weight: bold; color: #FE1B01; margin: 0;">
                    {estimated_time}
                </p>
            </div>

            <p style="margin-top: 30px;">Thanks again for choosing Leban Street.</p>
            """

            # 4. Get full HTML and send
            html_content = EmailService._get_base_email_template(
                title=f"Your Leban Street Order ({order_number}) is Out for Delivery!",
                content=content,
                cta_text="Track your order",
                cta_link="https://www.lebanstreet.com/track-order"
            )

            resend.api_key = os.getenv("RESEND_API_KEY")
            resend.Emails.send({
                "from": "noreply@lebanstreet.com",
                "to": customer_email,
                "subject": f"Your Order is Out for Delivery! ({order_number})",
                "html": html_content
            })
            print(f"✅ 'Out for delivery' email sent to {customer_email}")

        except Exception as e:
            print(f"❌ 'Out for delivery' email failed for {customer_email}: {str(e)}")