# Add to services.py or create email_templates.py

def get_otp_email_template(pin: str, customer_name: str = "Customer") -> str:
    """4-digit OTP template for website customers"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                margin: 0;
                padding: 0;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                background-color: #ffffff;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                padding: 40px 20px;
            }}
            .logo {{
                text-align: center;
                margin-bottom: 40px;
            }}
            .content {{
                background: #ffffff;
                border: 1px solid #f0f0f0;
                border-radius: 12px;
                padding: 40px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.05);
            }}
            h1 {{
                color: #393939;
                font-size: 24px;
                margin: 0 0 16px 0;
                font-weight: 600;
            }}
            p {{
                color: #393939;
                font-size: 16px;
                line-height: 1.6;
                margin: 0 0 24px 0;
            }}
            .otp-box {{
                background: linear-gradient(135deg, #FE1B01 0%, #ff4d36 100%);
                border-radius: 12px;
                padding: 32px;
                text-align: center;
                margin: 32px 0;
            }}
            .otp-code {{
                font-size: 48px;
                font-weight: 700;
                color: #ffffff;
                letter-spacing: 12px;
                font-family: 'Courier New', monospace;
            }}
            .otp-label {{
                color: #ffffff;
                font-size: 14px;
                margin-top: 12px;
                opacity: 0.9;
            }}
            .info-box {{
                background: #f9f9f9;
                border-left: 4px solid #FE1B01;
                padding: 16px 20px;
                border-radius: 4px;
                margin: 24px 0;
            }}
            .info-box p {{
                margin: 0;
                font-size: 14px;
                color: #666;
            }}
            .footer {{
                text-align: center;
                margin-top: 40px;
                padding-top: 32px;
                border-top: 1px solid #e0e0e0;
            }}
            .footer p {{
                color: #999;
                font-size: 14px;
                margin: 8px 0;
            }}
            .social-links {{
                margin: 20px 0;
            }}
            .social-links a {{
                display: inline-block;
                margin: 0 8px;
                text-decoration: none;
            }}
            .social-icon {{
                width: 32px;
                height: 32px;
                background: #393939;
                border-radius: 50%;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                transition: background 0.3s;
            }}
            .social-icon:hover {{
                background: #FE1B01;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">
                <svg width="88" height="56" viewBox="0 0 88 56" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M22.0078 27.5694C22.5293 27.0777 23.1949 27.3945 23.1062 28.0174C22.7621 30.312 22.3962 32.9016 22.5626 34.6936C22.6401 35.4802 22.3406 35.8409 21.6417 35.8628C18.2359 35.8628 9.76036 34.0817 7.43069 32.9563C5.16757 31.8636 2.83789 30.3885 1.14056 29.1647C0.441658 28.6511 0.108847 28.0174 0.253065 27.4492C0.619157 25.679 1.39572 19.1011 1.39572 13.7253C1.39572 8.34935 0.608063 3.30123 0.241972 1.18145C0.131035 0.471217 0.463846 0.110636 1.16275 0.230829C1.86165 0.351022 2.63821 0.449363 3.90289 0.46029C5.23413 0.482142 6.04397 0.361949 6.83162 0.230829C7.46397 0.121562 7.86334 0.602337 7.71912 1.46554C7.35303 4.01147 6.57648 9.68242 6.57648 15.703C6.57648 18.544 7.08679 25.6135 7.08679 25.6135C11.5021 27.9518 18.4246 30.6944 22.0078 27.5694ZM14.93 25.6353C13.0552 25.3186 11.6574 24.8158 10.1597 24.2039C9.50521 23.9309 9.16131 23.6031 9.27225 22.8382C9.63834 20.8714 10.2374 15.6702 10.2374 12.4359C10.2374 8.84106 9.64944 3.67274 9.27225 1.45462C9.16131 0.55863 9.46083 0.143416 10.1597 0.230829C11.6352 0.42751 13.5322 0.547703 15.4514 0.547703C17.526 0.547703 19.6005 0.416583 21.3422 0.198049C22.0078 0.110636 22.3629 0.580483 22.3073 1.56388C22.2075 3.15918 22.2519 4.89652 22.3073 6.30606C22.3516 7.36596 21.9745 7.61726 21.2755 7.15835C18.9792 5.56305 16.6496 5.72694 15.4625 5.72694C15.4625 5.72694 15.2074 8.64438 15.0521 10.7642C16.2724 10.8625 17.7478 10.5128 18.6464 10.0321C19.2677 9.70426 19.5451 9.9228 19.5007 10.8079C19.4674 11.4962 19.423 12.1846 19.423 12.9713C19.423 13.6597 19.423 14.2935 19.4563 14.9709C19.5007 15.8888 19.2343 16.1182 18.5687 15.7467C17.5814 15.2113 16.1282 14.7196 15.0188 14.6103C15.1297 16.7738 15.4625 20.161 15.4625 20.161C18.0585 20.6418 20.2328 20.0299 21.797 18.7516C22.4293 18.2271 22.729 18.4238 22.6844 19.3635C22.618 21.1118 22.5736 22.8599 22.6844 24.4554C22.74 25.2529 22.3962 25.5479 21.7193 25.6135C18.9128 25.8976 17.0046 25.9631 14.9411 25.6135L14.93 25.6353Z" fill="#FE1B01"/>
                    <path d="M35.4754 12.2503C36.8399 11.0046 38.2932 8.66633 38.2932 6.53562C38.2932 1.85901 35.2534 0.0779584 30.7051 0.00147157C29.2518 -0.0203818 26.6225 0.209078 24.892 0.165372C24.2152 0.143519 23.8603 0.646146 24.0044 1.53121C24.3039 3.94601 24.892 8.74282 24.892 13.5506C24.892 18.3584 24.3372 22.4667 24.0044 24.4882C23.8936 25.3842 24.2264 25.7775 24.892 25.5918C25.4687 25.4388 26.2343 25.2203 27.3325 25.1219C28.564 25.0126 30.2613 24.8487 31.5925 24.3898C35.6639 22.9912 39.5134 20.3252 39.5134 15.6266C39.5134 13.0807 37.4389 11.8788 35.4754 12.2394V12.2503ZM29.6623 7.22401C29.9285 5.71613 30.7384 4.59067 31.5815 4.5142C32.6909 4.41586 33.545 5.48667 33.545 8.08721C33.545 10.0103 32.3248 11.704 30.3944 12.0973C30.0949 12.1519 29.9508 12.1847 29.6511 12.2503C29.6511 10.2616 29.3295 9.03784 29.6511 7.22401H29.6623ZM31.7812 20.4671C30.8603 20.7621 30.0616 20.3252 29.7844 19.2433C29.4847 18.0743 29.7067 17.0908 29.7067 15.4955C30.0172 15.419 30.1726 15.3862 30.4831 15.3098C32.4468 14.829 33.8557 15.4518 33.8557 16.9815C33.8557 19.0249 32.8904 20.1176 31.7812 20.478V20.4671Z" fill="#FE1B01"/>
                </svg>
            </div>
            
            <div class="content">
                <h1>Verify Your Account</h1>
                <p>Hi {customer_name},</p>
                <p>Welcome back! Please use the verification code below to complete your login:</p>
                
                <div class="otp-box">
                    <div class="otp-code">{pin}</div>
                    <div class="otp-label">VERIFICATION CODE</div>
                </div>
                
                <div class="info-box">
                    <p>⏱️ This code will expire in <strong>10 minutes</strong></p>
                    <p>🔒 Never share this code with anyone</p>
                </div>
                
                <p>If you didn't request this code, please ignore this email or contact our support team.</p>
            </div>
            
            <div class="footer">
                <div class="social-links">
                    <a href="https://www.lebanstreet.com" target="_blank">
                        <div class="social-icon">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="#ffffff">
                                <path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/>
                            </svg>
                        </div>
                    </a>
                    <a href="https://www.instagram.com/lebanstreet.ng?igsh=YmMyZTdlMjB5MDE=" target="_blank">
                        <div class="social-icon">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="#ffffff">
                                <path d="M12 2c2.717 0 3.056.01 4.122.06 1.065.05 1.79.217 2.428.465.66.254 1.216.598 1.772 1.153a4.908 4.908 0 0 1 1.153 1.772c.247.637.415 1.363.465 2.428.047 1.066.06 1.405.06 4.122 0 2.717-.01 3.056-.06 4.122-.05 1.065-.218 1.79-.465 2.428a4.883 4.883 0 0 1-1.153 1.772 4.915 4.915 0 0 1-1.772 1.153c-.637.247-1.363.415-2.428.465-1.066.047-1.405.06-4.122.06-2.717 0-3.056-.01-4.122-.06-1.065-.05-1.79-.218-2.428-.465a4.89 4.89 0 0 1-1.772-1.153 4.904 4.904 0 0 1-1.153-1.772c-.248-.637-.415-1.363-.465-2.428C2.013 15.056 2 14.717 2 12c0-2.717.01-3.056.06-4.122.05-1.066.217-1.79.465-2.428a4.88 4.88 0 0 1 1.153-1.772A4.897 4.897 0 0 1 5.45 2.525c.638-.248 1.362-.415 2.428-.465C8.944 2.013 9.283 2 12 2zm0 5a5 5 0 1 0 0 10 5 5 0 0 0 0-10zm6.5-.25a1.25 1.25 0 0 0-2.5 0 1.25 1.25 0 0 0 2.5 0zM12 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6z"/>
                            </svg>
                        </div>
                    </a>
                    <a href="https://x.com/lebanstreet" target="_blank">
                        <div class="social-icon">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="#ffffff">
                                <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
                            </svg>
                        </div>
                    </a>
                </div>
                <p><strong>LebanStreet Kitchen</strong></p>
                <p>www.lebanstreet.com</p>
                <p style="font-size: 12px; color: #bbb;">© 2025 LebanStreet. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """

def get_forgot_password_template(reset_link: str, user_name: str) -> str:
    """Password reset template for staff/admin"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                margin: 0;
                padding: 0;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                background-color: #ffffff;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                padding: 40px 20px;
            }}
            .logo {{
                text-align: center;
                margin-bottom: 40px;
            }}
            .content {{
                background: #ffffff;
                border: 1px solid #f0f0f0;
                border-radius: 12px;
                padding: 40px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.05);
            }}
            h1 {{
                color: #393939;
                font-size: 24px;
                margin: 0 0 16px 0;
                font-weight: 600;
            }}
            p {{
                color: #393939;
                font-size: 16px;
                line-height: 1.6;
                margin: 0 0 24px 0;
            }}
            .button-container {{
                text-align: center;
                margin: 40px 0;
            }}
            .reset-button {{
                display: inline-block;
                padding: 16px 48px;
                background: linear-gradient(135deg, #FE1B01 0%, #ff4d36 100%);
                color: #ffffff;
                text-decoration: none;
                border-radius: 8px;
                font-weight: 600;
                font-size: 16px;
                box-shadow: 0 4px 12px rgba(254, 27, 1, 0.3);
                transition: transform 0.2s;
            }}
            .reset-button:hover {{
                transform: translateY(-2px);
                box-shadow: 0 6px 16px rgba(254, 27, 1, 0.4);
            }}
            .info-box {{
                background: #f9f9f9;
                border-left: 4px solid #f0f0f0;
                padding: 16px 20px;
                border-radius: 4px;
                margin: 24px 0;
            }}
            .info-box p {{
                margin: 0;
                font-size: 14px;
                color: #666;
            }}
            .alt-link {{
                background: #f5f5f5;
                padding: 16px;
                border-radius: 6px;
                word-break: break-all;
                font-size: 12px;
                color: #666;
                margin: 24px 0;
            }}
            .footer {{
                text-align: center;
                margin-top: 40px;
                padding-top: 32px;
                border-top: 1px solid #e0e0e0;
            }}
            .footer p {{
                color: #999;
                font-size: 14px;
                margin: 8px 0;
            }}
            .social-links {{
                margin: 20px 0;
            }}
            .social-links a {{
                display: inline-block;
                margin: 0 8px;
                text-decoration: none;
            }}
            .social-icon {{
                width: 32px;
                height: 32px;
                background: #393939;
                border-radius: 50%;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                transition: background 0.3s;
            }}
            .social-icon:hover {{
                background: #FE1B01;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">
                <svg width="88" height="56" viewBox="0 0 88 56" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M22.0078 27.5694C22.5293 27.0777 23.1949 27.3945 23.1062 28.0174C22.7621 30.312 22.3962 32.9016 22.5626 34.6936C22.6401 35.4802 22.3406 35.8409 21.6417 35.8628C18.2359 35.8628 9.76036 34.0817 7.43069 32.9563C5.16757 31.8636 2.83789 30.3885 1.14056 29.1647C0.441658 28.6511 0.108847 28.0174 0.253065 27.4492C0.619157 25.679 1.39572 19.1011 1.39572 13.7253C1.39572 8.34935 0.608063 3.30123 0.241972 1.18145C0.131035 0.471217 0.463846 0.110636 1.16275 0.230829C1.86165 0.351022 2.63821 0.449363 3.90289 0.46029C5.23413 0.482142 6.04397 0.361949 6.83162 0.230829C7.46397 0.121562 7.86334 0.602337 7.71912 1.46554C7.35303 4.01147 6.57648 9.68242 6.57648 15.703C6.57648 18.544 7.08679 25.6135 7.08679 25.6135C11.5021 27.9518 18.4246 30.6944 22.0078 27.5694ZM14.93 25.6353C13.0552 25.3186 11.6574 24.8158 10.1597 24.2039C9.50521 23.9309 9.16131 23.6031 9.27225 22.8382C9.63834 20.8714 10.2374 15.6702 10.2374 12.4359C10.2374 8.84106 9.64944 3.67274 9.27225 1.45462C9.16131 0.55863 9.46083 0.143416 10.1597 0.230829C11.6352 0.42751 13.5322 0.547703 15.4514 0.547703C17.526 0.547703 19.6005 0.416583 21.3422 0.198049C22.0078 0.110636 22.3629 0.580483 22.3073 1.56388C22.2075 3.15918 22.2519 4.89652 22.3073 6.30606C22.3516 7.36596 21.9745 7.61726 21.2755 7.15835C18.9792 5.56305 16.6496 5.72694 15.4625 5.72694C15.4625 5.72694 15.2074 8.64438 15.0521 10.7642C16.2724 10.8625 17.7478 10.5128 18.6464 10.0321C19.2677 9.70426 19.5451 9.9228 19.5007 10.8079C19.4674 11.4962 19.423 12.1846 19.423 12.9713C19.423 13.6597 19.423 14.2935 19.4563 14.9709C19.5007 15.8888 19.2343 16.1182 18.5687 15.7467C17.5814 15.2113 16.1282 14.7196 15.0188 14.6103C15.1297 16.7738 15.4625 20.161 15.4625 20.161C18.0585 20.6418 20.2328 20.0299 21.797 18.7516C22.4293 18.2271 22.729 18.4238 22.6844 19.3635C22.618 21.1118 22.5736 22.8599 22.6844 24.4554C22.74 25.2529 22.3962 25.5479 21.7193 25.6135C18.9128 25.8976 17.0046 25.9631 14.9411 25.6135L14.93 25.6353Z" fill="#FE1B01"/>
                    <path d="M35.4754 12.2503C36.8399 11.0046 38.2932 8.66633 38.2932 6.53562C38.2932 1.85901 35.2534 0.0779584 30.7051 0.00147157C29.2518 -0.0203818 26.6225 0.209078 24.892 0.165372C24.2152 0.143519 23.8603 0.646146 24.0044 1.53121C24.3039 3.94601 24.892 8.74282 24.892 13.5506C24.892 18.3584 24.3372 22.4667 24.0044 24.4882C23.8936 25.3842 24.2264 25.7775 24.892 25.5918C25.4687 25.4388 26.2343 25.2203 27.3325 25.1219C28.564 25.0126 30.2613 24.8487 31.5925 24.3898C35.6639 22.9912 39.5134 20.3252 39.5134 15.6266C39.5134 13.0807 37.4389 11.8788 35.4754 12.2394V12.2503ZM29.6623 7.22401C29.9285 5.71613 30.7384 4.59067 31.5815 4.5142C32.6909 4.41586 33.545 5.48667 33.545 8.08721C33.545 10.0103 32.3248 11.704 30.3944 12.0973C30.0949 12.1519 29.9508 12.1847 29.6511 12.2503C29.6511 10.2616 29.3295 9.03784 29.6511 7.22401H29.6623ZM31.7812 20.4671C30.8603 20.7621 30.0616 20.3252 29.7844 19.2433C29.4847 18.0743 29.7067 17.0908 29.7067 15.4955C30.0172 15.419 30.1726 15.3862 30.4831 15.3098C32.4468 14.829 33.8557 15.4518 33.8557 16.9815C33.8557 19.0249 32.8904 20.1176 31.7812 20.478V20.4671Z" fill="#FE1B01"/>
                </svg>
            </div>
            
            <div class="content">
                <h1>Reset Your Password</h1>
                <p>Hi {user_name},</p>
                <p>We received a request to reset your password. Click the button below to create a new password:</p>
                
                <div class="button-container">
                    <a href="{reset_link}" class="reset-button">Reset Password</a>
                </div>
                
                <div class="info-box">
                    <p>⏱️ This link will expire in <strong>30 minutes</strong></p>
                    <p>🔒 For security, you'll be logged out of all devices after resetting</p>
                </div>
                
                <p style="font-size: 14px;">If the button doesn't work, copy and paste this link into your browser:</p>
                <div class="alt-link">{reset_link}</div>
                
                <p style="font-size: 14px; color: #666;">If you didn't request a password reset, please ignore this email or contact support if you have concerns.</p>
            </div>
            
            <div class="footer">
                <div class="social-links">
                    <a href="https://www.lebanstreet.com" target="_blank">
                        <div class="social-icon">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="#ffffff">
                                <path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/>
                            </svg>
                        </div>
                    </a>
                    <a href="https://www.instagram.com/lebanstreet.ng?igsh=YmMyZTdlMjB5MDE=" target="_blank">
                        <div class="social-icon">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="#ffffff">
                                <path d="M12 2c2.717 0 3.056.01 4.122.06 1.065.05 1.79.217 2.428.465.66.254 1.216.598 1.772 1.153a4.908 4.908 0 0 1 1.153 1.772c.247.637.415 1.363.465 2.428.047 1.066.06 1.405.06 4.122 0 2.717-.01 3.056-.06 4.122-.05 1.065-.218 1.79-.465 2.428a4.883 4.883 0 0 1-1.153 1.772 4.915 4.915 0 0 1-1.772 1.153c-.637.247-1.363.415-2.428.465-1.066.047-1.405.06-4.122.06-2.717 0-3.056-.01-4.122-.06-1.065-.05-1.79-.218-2.428-.465a4.89 4.89 0 0 1-1.772-1.153 4.904 4.904 0 0 1-1.153-1.772c-.248-.637-.415-1.363-.465-2.428C2.013 15.056 2 14.717 2 12c0-2.717.01-3.056.06-4.122.05-1.066.217-1.79.465-2.428a4.88 4.88 0 0 1 1.153-1.772A4.897 4.897 0 0 1 5.45 2.525c.638-.248 1.362-.415 2.428-.465C8.944 2.013 9.283 2 12 2zm0 5a5 5 0 1 0 0 10 5 5 0 0 0 0-10zm6.5-.25a1.25 1.25 0 0 0-2.5 0 1.25 1.25 0 0 0 2.5 0zM12 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6z"/>
                            </svg>
                        </div>
                    </a>
                    <a href="https://x.com/lebanstreet" target="_blank">
                        <div class="social-icon">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="#ffffff">
                                <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
                            </svg>
                        </div>
                    </a>
                </div>
                <p><strong>LebanStreet Kitchen</strong></p>
                <p>www.lebanstreet.com</p>
                <p style="font-size: 12px; color: #bbb;">© 2025 LebanStreet. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """

def get_invitation_email_template(invitation_link: str, role: str, invited_by_name: str) -> str:
    """Staff invitation template"""
    role_display = role.replace('_', ' ').title()
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                margin: 0;
                padding: 0;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                background-color: #ffffff;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                padding: 40px 20px;
            }}
            .logo {{
                text-align: center;
                margin-bottom: 40px;
            }}
            .content {{
                background: #ffffff;
                border: 1px solid #f0f0f0;
                border-radius: 12px;
                padding: 40px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.05);
            }}
            h1 {{
                color: #393939;
                font-size: 28px;
                margin: 0 0 8px 0;
                font-weight: 600;
            }}
            .subtitle {{
                color: #FE1B01;
                font-size: 16px;
                font-weight: 600;
                margin: 0 0 24px 0;
            }}
            p {{
                color: #393939;
                font-size: 16px;
                line-height: 1.6;
                margin: 0 0 24px 0;
            }}
            .role-badge {{
                display: inline-block;
                background: linear-gradient(135deg, #FE1B01 0%, #ff4d36 100%);
                color: #ffffff;
                padding: 8px 20px;
                border-radius: 20px;
                font-weight: 600;
                font-size: 14px;
                margin: 16px 0;
            }}
            .button-container {{
                text-align: center;
                margin: 40px 0;
            }}
            .invite-button {{
                display: inline-block;
                padding: 16px 48px;
                background: linear-gradient(135deg, #FE1B01 0%, #ff4d36 100%);
                color: #ffffff;
                text-decoration: none;
                border-radius: 8px;
                font-weight: 600;
                font-size: 16px;
                box-shadow: 0 4px 12px rgba(254, 27, 1, 0.3);
                transition: transform 0.2s;
            }}
            .invite-button:hover {{
                transform: translateY(-2px);
                box-shadow: 0 6px 16px rgba(254, 27, 1, 0.4);
            }}
            .info-box {{
                background: #f9f9f9;
                border-left: 4px solid #FE1B01;
                padding: 16px 20px;
                border-radius: 4px;
                margin: 24px 0;
            }}
            .info-box p {{
                margin: 0;
                font-size: 14px;
                color: #666;
            }}
            .features {{
                background: #f9f9f9;
                border-radius: 8px;
                padding: 24px;
                margin: 24px 0;
            }}
            .features ul {{
                margin: 0;
                padding: 0 0 0 20px;
                color: #666;
            }}
            .features li {{
                margin: 8px 0;
                font-size: 14px;
            }}
            .alt-link {{
                background: #f5f5f5;
                padding: 16px;
                border-radius: 6px;
                word-break: break-all;
                font-size: 12px;
                color: #666;
                margin: 24px 0;
            }}
            .footer {{
                text-align: center;
                margin-top: 40px;
                padding-top: 32px;
                border-top: 1px solid #e0e0e0;
            }}
            .footer p {{
                color: #999;
                font-size: 14px;
                margin: 8px 0;
            }}
            .social-links {{
                margin: 20px 0;
            }}
            .social-links a {{
                display: inline-block;
                margin: 0 8px;
                text-decoration: none;
            }}
            .social-icon {{
                width: 32px;
                height: 32px;
                background: #393939;
                border-radius: 50%;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                transition: background 0.3s;
            }}
            .social-icon:hover {{
                background: #FE1B01;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">
                <svg width="88" height="56" viewBox="0 0 88 56" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M22.0078 27.5694C22.5293 27.0777 23.1949 27.3945 23.1062 28.0174C22.7621 30.312 22.3962 32.9016 22.5626 34.6936C22.6401 35.4802 22.3406 35.8409 21.6417 35.8628C18.2359 35.8628 9.76036 34.0817 7.43069 32.9563C5.16757 31.8636 2.83789 30.3885 1.14056 29.1647C0.441658 28.6511 0.108847 28.0174 0.253065 27.4492C0.619157 25.679 1.39572 19.1011 1.39572 13.7253C1.39572 8.34935 0.608063 3.30123 0.241972 1.18145C0.131035 0.471217 0.463846 0.110636 1.16275 0.230829C1.86165 0.351022 2.63821 0.449363 3.90289 0.46029C5.23413 0.482142 6.04397 0.361949 6.83162 0.230829C7.46397 0.121562 7.86334 0.602337 7.71912 1.46554C7.35303 4.01147 6.57648 9.68242 6.57648 15.703C6.57648 18.544 7.08679 25.6135 7.08679 25.6135C11.5021 27.9518 18.4246 30.6944 22.0078 27.5694ZM14.93 25.6353C13.0552 25.3186 11.6574 24.8158 10.1597 24.2039C9.50521 23.9309 9.16131 23.6031 9.27225 22.8382C9.63834 20.8714 10.2374 15.6702 10.2374 12.4359C10.2374 8.84106 9.64944 3.67274 9.27225 1.45462C9.16131 0.55863 9.46083 0.143416 10.1597 0.230829C11.6352 0.42751 13.5322 0.547703 15.4514 0.547703C17.526 0.547703 19.6005 0.416583 21.3422 0.198049C22.0078 0.110636 22.3629 0.580483 22.3073 1.56388C22.2075 3.15918 22.2519 4.89652 22.3073 6.30606C22.3516 7.36596 21.9745 7.61726 21.2755 7.15835C18.9792 5.56305 16.6496 5.72694 15.4625 5.72694C15.4625 5.72694 15.2074 8.64438 15.0521 10.7642C16.2724 10.8625 17.7478 10.5128 18.6464 10.0321C19.2677 9.70426 19.5451 9.9228 19.5007 10.8079C19.4674 11.4962 19.423 12.1846 19.423 12.9713C19.423 13.6597 19.423 14.2935 19.4563 14.9709C19.5007 15.8888 19.2343 16.1182 18.5687 15.7467C17.5814 15.2113 16.1282 14.7196 15.0188 14.6103C15.1297 16.7738 15.4625 20.161 15.4625 20.161C18.0585 20.6418 20.2328 20.0299 21.797 18.7516C22.4293 18.2271 22.729 18.4238 22.6844 19.3635C22.618 21.1118 22.5736 22.8599 22.6844 24.4554C22.74 25.2529 22.3962 25.5479 21.7193 25.6135C18.9128 25.8976 17.0046 25.9631 14.9411 25.6135L14.93 25.6353Z" fill="#FE1B01"/>
                    <path d="M35.4754 12.2503C36.8399 11.0046 38.2932 8.66633 38.2932 6.53562C38.2932 1.85901 35.2534 0.0779584 30.7051 0.00147157C29.2518 -0.0203818 26.6225 0.209078 24.892 0.165372C24.2152 0.143519 23.8603 0.646146 24.0044 1.53121C24.3039 3.94601 24.892 8.74282 24.892 13.5506C24.892 18.3584 24.3372 22.4667 24.0044 24.4882C23.8936 25.3842 24.2264 25.7775 24.892 25.5918C25.4687 25.4388 26.2343 25.2203 27.3325 25.1219C28.564 25.0126 30.2613 24.8487 31.5925 24.3898C35.6639 22.9912 39.5134 20.3252 39.5134 15.6266C39.5134 13.0807 37.4389 11.8788 35.4754 12.2394V12.2503ZM29.6623 7.22401C29.9285 5.71613 30.7384 4.59067 31.5815 4.5142C32.6909 4.41586 33.545 5.48667 33.545 8.08721C33.545 10.0103 32.3248 11.704 30.3944 12.0973C30.0949 12.1519 29.9508 12.1847 29.6511 12.2503C29.6511 10.2616 29.3295 9.03784 29.6511 7.22401H29.6623ZM31.7812 20.4671C30.8603 20.7621 30.0616 20.3252 29.7844 19.2433C29.4847 18.0743 29.7067 17.0908 29.7067 15.4955C30.0172 15.419 30.1726 15.3862 30.4831 15.3098C32.4468 14.829 33.8557 15.4518 33.8557 16.9815C33.8557 19.0249 32.8904 20.1176 31.7812 20.478V20.4671Z" fill="#FE1B01"/>
                </svg>
            </div>
            
            <div class="content">
                <h1>🎉 You're Invited!</h1>
                <p class="subtitle">Join the LebanStreet team</p>
                
                <p>You've been invited by <strong>{invited_by_name}</strong> to join LebanStreet Kitchen's management system.</p>
                
                <div class="role-badge">Your Role: {role_display}</div>
                
                <p>Click the button below to set up your account and get started:</p>
                
                <div class="button-container">
                    <a href="{invitation_link}" class="invite-button">Accept Invitation</a>
                </div>
                
                <div class="info-box">
                    <p>⏱️ This invitation expires in <strong>7 days</strong></p>
                    <p>🔒 You'll create your own secure password during setup</p>
                </div>
                
                <div class="features">
                    <p style="font-weight: 600; margin-bottom: 12px;">What you'll have access to:</p>
                    <ul>
                        <li>Dashboard and analytics</li>
                        <li>Order management system</li>
                        <li>Inventory tracking</li>
                        <li>Customer management</li>
                        <li>Reporting tools</li>
                    </ul>
                </div>
                
                <p style="font-size: 14px;">If the button doesn't work, copy and paste this link into your browser:</p>
                <div class="alt-link">{invitation_link}</div>
                
                <p style="font-size: 14px; color: #666;">If you didn't expect this invitation, you can safely ignore this email.</p>
            </div>
            
            <div class="footer">
                <div class="social-links">
                    <a href="https://www.lebanstreet.com" target="_blank">
                        <div class="social-icon">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="#ffffff">
                                <path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/>
                            </svg>
                        </div>
                    </a>
                    <a href="https://www.instagram.com/lebanstreet.ng?igsh=YmMyZTdlMjB5MDE=" target="_blank">
                        <div class="social-icon">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="#ffffff">
                                <path d="M12 2c2.717 0 3.056.01 4.122.06 1.065.05 1.79.217 2.428.465.66.254 1.216.598 1.772 1.153a4.908 4.908 0 0 1 1.153 1.772c.247.637.415 1.363.465 2.428.047 1.066.06 1.405.06 4.122 0 2.717-.01 3.056-.06 4.122-.05 1.065-.218 1.79-.465 2.428a4.883 4.883 0 0 1-1.153 1.772 4.915 4.915 0 0 1-1.772 1.153c-.637.247-1.363.415-2.428.465-1.066.047-1.405.06-4.122.06-2.717 0-3.056-.01-4.122-.06-1.065-.05-1.79-.218-2.428-.465a4.89 4.89 0 0 1-1.772-1.153 4.904 4.904 0 0 1-1.153-1.772c-.248-.637-.415-1.363-.465-2.428C2.013 15.056 2 14.717 2 12c0-2.717.01-3.056.06-4.122.05-1.066.217-1.79.465-2.428a4.88 4.88 0 0 1 1.153-1.772A4.897 4.897 0 0 1 5.45 2.525c.638-.248 1.362-.415 2.428-.465C8.944 2.013 9.283 2 12 2zm0 5a5 5 0 1 0 0 10 5 5 0 0 0 0-10zm6.5-.25a1.25 1.25 0 0 0-2.5 0 1.25 1.25 0 0 0 2.5 0zM12 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6z"/>
                            </svg>
                        </div>
                    </a>
                    <a href="https://x.com/lebanstreet" target="_blank">
                        <div class="social-icon">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="#ffffff">
                                <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
                            </svg>
                        </div>
                    </a>
                </div>
                <p><strong>LebanStreet Kitchen</strong></p>
                <p>www.lebanstreet.com</p>
                <p style="font-size: 12px; color: #bbb;">© 2025 LebanStreet. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """