import os
from supabase import create_client
from app.config import settings

def create_first_admin(email: str, password: str):
    supabase_admin = create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_SERVICE_KEY
    )
    
    # Create auth user
    auth_response = supabase_admin.auth.admin.create_user({
        "email": email,
        "password": password,
        "email_confirm": True
    })
    
    # Create profile
    profile_data = {
        "id": auth_response.user.id,
        "email": email,
        "role": "super_admin",
        "is_active": True
    }
    
    supabase_admin.table("profiles").insert(profile_data).execute()
    print(f"Super admin created: {email}")

if __name__ == "__main__":
    email = input("Admin email: ")
    password = input("Admin password: ")
    create_first_admin(email, password)



