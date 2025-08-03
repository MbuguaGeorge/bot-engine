#!/usr/bin/env python3
"""
Test script for Mailgun email service
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'API.settings')
django.setup()

from email_templates.email_service import email_service

def test_mailgun_email():
    """Test Mailgun email sending"""
    
    if not email_service:
        print("❌ Email service not available")
        return
    
    print("=== Mailgun Email Test ===\n")
    
    # Test email details
    test_email = "test@example.com"  # Replace with a real email for testing
    subject = "Mailgun Test Email"
    html_content = """
    <html>
        <body>
            <h1>Mailgun Test</h1>
            <p>This is a test email sent via Mailgun API.</p>
            <p>If you receive this, the Mailgun integration is working correctly!</p>
        </body>
    </html>
    """
    text_content = "Mailgun Test - This is a test email sent via Mailgun API."
    
    print(f"Testing email service with domain: {email_service.domain}")
    print(f"From email: {email_service.from_email}")
    print(f"To email: {test_email}")
    print(f"Subject: {subject}")
    print()
    
    # Test email validation
    print("1. Testing email validation...")
    is_valid = email_service.validate_email_address(test_email)
    print(f"   Email validation result: {'✅ Success' if is_valid else '❌ Failed'}")
    print()
    
    # Test email sending
    print("2. Testing email sending...")
    success = email_service.send_email(test_email, subject, html_content, text_content)
    print(f"   Email sending result: {'✅ Success' if success else '❌ Failed'}")
    print()
    
    # Test template email
    print("3. Testing template email...")
    context = {
        'user_name': 'Test User',
        'dashboard_url': 'https://example.com/dashboard',
    }
    template_success = email_service.send_template_email(
        test_email, 'welcome', context, "Welcome Test"
    )
    print(f"   Template email result: {'✅ Success' if template_success else '❌ Failed'}")
    print()
    
    print("=== Test Complete ===")

if __name__ == "__main__":
    test_mailgun_email() 