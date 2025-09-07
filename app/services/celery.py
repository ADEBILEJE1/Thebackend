from celery import Celery
from datetime import date
import csv
import io
from ..config import settings
import sendgrid
from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType
import base64

celery_app = Celery(
    "restaurant",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND
)

@celery_app.task
def send_invitation_email(email: str, token: str):
    sg = sendgrid.SendGridAPIClient(api_key=settings.SENDGRID_API_KEY)
    
    invitation_link = f"{settings.FRONTEND_URL}/setup-password?token={token}"
    
    message = Mail(
        from_email=settings.FROM_EMAIL,
        to_emails=email,
        subject="You're invited to join our restaurant system",
        html_content=f"""
        <h2>Welcome to Restaurant Management System</h2>
        <p>You've been invited to join our team!</p>
        <p>Please click the button below to set up your password:</p>
        <a href="{invitation_link}" style="display: inline-block; padding: 12px 24px; background-color: #4CAF50; color: white; text-decoration: none; border-radius: 4px;">Set Up Password</a>
        <p>Or copy this link: {invitation_link}</p>
        <p><small>This link will expire in 7 days.</small></p>
        """
    )
    
    sg.send(message)

@celery_app.task
def generate_report_task(report_type: str, date_from: date, date_to: date, user_id: str):
    from ..database import supabase
    
    # Generate report based on type
    if report_type == "sales":
        # Get orders data
        orders = supabase.table("orders").select("*, order_items(*)").gte("created_at", date_from.isoformat()).lte("created_at", f"{date_to.isoformat()}T23:59:59").execute()
        
        # Create CSV
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Order Number", "Date", "Type", "Customer", "Status", "Total", "Items"])
        
        for order in orders.data:
            items = ", ".join([f"{i['product_name']} x{i['quantity']}" for i in order["order_items"]])
            writer.writerow([
                order["order_number"],
                order["created_at"][:10],
                order["order_type"],
                order.get("customer_name", "Walk-in"),
                order["status"],
                order["total"],
                items
            ])
        
        csv_content = output.getvalue()
        
    elif report_type == "inventory":
        # Get inventory data
        products = supabase.table("products").select("*, categories(name)").execute()
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Product", "Category", "Units", "Price", "Value", "Status"])
        
        for product in products.data:
            writer.writerow([
                product["name"],
                product["categories"]["name"],
                product["units"],
                product["price"],
                float(product["price"]) * product["units"],
                product["status"]
            ])
        
        csv_content = output.getvalue()
        
    elif report_type == "activity":
        # Get activity logs
        logs = supabase.table("activity_logs").select("*").gte("created_at", date_from.isoformat()).lte("created_at", date_to.isoformat()).execute()
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Date", "User", "Role", "Action", "Resource", "Details"])
        
        for log in logs.data:
            writer.writerow([
                log["created_at"],
                log["user_email"],
                log["user_role"],
                log["action"],
                log["resource"],
                str(log.get("details", ""))
            ])
        
        csv_content = output.getvalue()
    
    # Get user email
    user = supabase.table("profiles").select("email").eq("id", user_id).execute()
    user_email = user.data[0]["email"]
    
    # Send email with attachment
    sg = sendgrid.SendGridAPIClient(api_key=settings.SENDGRID_API_KEY)
    
    message = Mail(
        from_email=settings.FROM_EMAIL,
        to_emails=user_email,
        subject=f"Your {report_type} report is ready",
        html_content=f"""
        <h2>Report Generated Successfully</h2>
        <p>Your {report_type} report for {date_from} to {date_to} is attached.</p>
        <p>Generated at: {date.today().isoformat()}</p>
        """
    )
    
    # Add CSV attachment
    encoded = base64.b64encode(csv_content.encode()).decode()
    attachment = Attachment(
        FileContent(encoded),
        FileName(f"{report_type}_report_{date_from}_{date_to}.csv"),
        FileType("text/csv")
    )
    message.attachment = attachment
    
    sg.send(message)
    
    # Save report record
    supabase.table("reports").insert({
        "report_type": report_type,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "generated_by": user_id
    }).execute()

@celery_app.task
def send_low_stock_alert(products: list):
    """Send low stock alert to managers"""
    from ..database import supabase
    
    # Get all managers and super admins
    managers = supabase.table("profiles").select("email").in_("role", ["manager", "super_admin"]).eq("is_active", True).execute()
    
    if not managers.data:
        return
    
    # Create email content
    product_list = "\n".join([f"• {p['name']}: {p['units']} units remaining (threshold: {p['threshold']})" for p in products])
    
    sg = sendgrid.SendGridAPIClient(api_key=settings.SENDGRID_API_KEY)
    
    for manager in managers.data:
        message = Mail(
            from_email=settings.FROM_EMAIL,
            to_emails=manager["email"],
            subject="Low Stock Alert - Immediate Attention Required",
            html_content=f"""
            <h2>Low Stock Alert</h2>
            <p>The following products are running low on stock:</p>
            <pre>{product_list}</pre>
            <p>Please restock these items as soon as possible.</p>
            <p><a href="{settings.FRONTEND_URL}/inventory" style="display: inline-block; padding: 10px 20px; background-color: #FF5722; color: white; text-decoration: none; border-radius: 4px;">View Inventory</a></p>
            """
        )
        
        sg.send(message)

@celery_app.task
def send_order_ready_notification(order_number: str, customer_email: str):
    """Notify customer that order is ready"""
    if not customer_email:
        return
    
    sg = sendgrid.SendGridAPIClient(api_key=settings.SENDGRID_API_KEY)
    
    message = Mail(
        from_email=settings.FROM_EMAIL,
        to_emails=customer_email,
        subject=f"Your Order {order_number} is Ready!",
        html_content=f"""
        <h2>Your Order is Ready for Pickup!</h2>
        <p>Order Number: <strong>{order_number}</strong></p>
        <p>Please come to the counter to collect your order.</p>
        <p>Thank you for your patience!</p>
        """
    )
    
    sg.send(message)

@celery_app.task
def daily_sales_summary():
    """Send daily sales summary to managers"""
    from ..database import supabase
    from datetime import datetime, timedelta
    
    yesterday = date.today() - timedelta(days=1)
    start_of_day = f"{yesterday.isoformat()}T00:00:00"
    end_of_day = f"{yesterday.isoformat()}T23:59:59"
    
    # Get yesterday's orders
    orders = supabase.table("orders").select("*").gte("created_at", start_of_day).lte("created_at", end_of_day).execute()
    
    if not orders.data:
        return
    
    # Calculate metrics
    total_orders = len(orders.data)
    completed_orders = len([o for o in orders.data if o["status"] == "completed"])
    cancelled_orders = len([o for o in orders.data if o["status"] == "cancelled"])
    total_revenue = sum(float(o["total"]) for o in orders.data if o["status"] == "completed")
    
    # Get managers
    managers = supabase.table("profiles").select("email").in_("role", ["manager", "super_admin"]).eq("is_active", True).execute()
    
    sg = sendgrid.SendGridAPIClient(api_key=settings.SENDGRID_API_KEY)
    
    for manager in managers.data:
        message = Mail(
            from_email=settings.FROM_EMAIL,
            to_emails=manager["email"],
            subject=f"Daily Sales Summary - {yesterday.isoformat()}",
            html_content=f"""
            <h2>Daily Sales Summary for {yesterday.strftime('%B %d, %Y')}</h2>
            <table style="border-collapse: collapse; width: 100%;">
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;">Total Orders:</td>
                    <td style="padding: 10px; border: 1px solid #ddd;"><strong>{total_orders}</strong></td>
                </tr>
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;">Completed Orders:</td>
                    <td style="padding: 10px; border: 1px solid #ddd;"><strong>{completed_orders}</strong></td>
                </tr>
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;">Cancelled Orders:</td>
                    <td style="padding: 10px; border: 1px solid #ddd;"><strong>{cancelled_orders}</strong></td>
                </tr>
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;">Total Revenue:</td>
                    <td style="padding: 10px; border: 1px solid #ddd;"><strong>${total_revenue:.2f}</strong></td>
                </tr>
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;">Average Order Value:</td>
                    <td style="padding: 10px; border: 1px solid #ddd;"><strong>${(total_revenue/completed_orders if completed_orders else 0):.2f}</strong></td>
                </tr>
            </table>
            <p style="margin-top: 20px;">
                <a href="{settings.FRONTEND_URL}/dashboard" style="display: inline-block; padding: 10px 20px; background-color: #2196F3; color: white; text-decoration: none; border-radius: 4px;">View Dashboard</a>
            </p>
            """
        )
        
        sg.send(message)

# Celery Beat Schedule for periodic tasks
celery_app.conf.beat_schedule = {
    'daily-sales-summary': {
        'task': 'app.services.celery.daily_sales_summary',
        'schedule': 60 * 60 * 24,  # Daily at midnight
    },
}

celery_app.conf.timezone = 'UTC'