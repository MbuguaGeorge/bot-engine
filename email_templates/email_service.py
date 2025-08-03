import os
import requests
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

MAILGUN_API_KEY = os.getenv("MAILGUN_API_KEY")
MAILGUN_DOMAIN = os.getenv("MAILGUN_DOMAIN")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL")
FRONTEND_URL = os.getenv("FRONTEND_URL")

class EmailService:
    def __init__(self):
        if not MAILGUN_API_KEY:
            raise Exception("MAILGUN_API_KEY not set in environment")
        if not MAILGUN_DOMAIN:
            raise Exception("MAILGUN_DOMAIN not set in environment")
        if not DEFAULT_FROM_EMAIL:
            raise Exception("DEFAULT_FROM_EMAIL not set in environment")
        if not FRONTEND_URL:
            raise Exception("FRONTEND_URL not set in environment")
        
        self.api_key = MAILGUN_API_KEY
        self.domain = MAILGUN_DOMAIN
        self.from_email = DEFAULT_FROM_EMAIL
        self.api_url = f"https://api.mailgun.net/v3/{self.domain}/messages"
        
        logger.info(f"EmailService initialized with domain: {self.domain}, from_email: {self.from_email}")
        print("EmailService initialized successfully")
    
    def validate_email_address(self, email_address):
        """Validate if an email address can receive emails by attempting to send a test email"""
        try:
            # Create a minimal test email
            data = {
                'from': f"Wozza <{self.from_email}>",
                'to': email_address,
                'subject': "Email Validation Test",
                'html': "<h1>Email Validation</h1><p>This is a test email to validate your email address.</p>",
                'text': "Email Validation - This is a test email to validate your email address."
            }
            
            logger.info(f"Validating email address: {email_address}")
            response = requests.post(
                self.api_url,
                auth=("api", self.api_key),
                data=data
            )
            
            if response.status_code == 200:
                logger.info(f"Email validation successful for {email_address}")
                return True
            else:
                logger.error(f"Email validation failed for {email_address}: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Email validation failed for {email_address}: {str(e)}")
            return False
    
    def send_email(self, to_email, subject, html_content, text_content=None):
        """Send email using Mailgun"""
        try:
            if not text_content:
                # Convert HTML to plain text (basic conversion)
                text_content = self._html_to_text(html_content)
            
            print(f"Attempting to send email to {to_email}")
            print(f"From email: {self.from_email}")
            print(f"Subject: {subject}")
            print(f"HTML content length: {len(html_content)}")
            print(f"Text content length: {len(text_content)}")
            
            # Create data for Mailgun API
            data = {
                'from': f"Wozza <{self.from_email}>",
                'to': to_email,
                'subject': subject,
                'html': html_content,
                'text': text_content
            }
            
            print(f"Mailgun data prepared")
            
            logger.info(f"Attempting to send email to {to_email} with subject: {subject}")
            print("Calling Mailgun API...")
            
            response = requests.post(
                self.api_url,
                auth=("api", self.api_key),
                data=data
            )
            
            print(f"Mailgun response status: {response.status_code}")
            print(f"Mailgun response: {response.text}")
            
            if response.status_code == 200:
                logger.info(f"Email sent successfully to {to_email}")
                return True
            else:
                logger.error(f"Failed to send email to {to_email}: {response.text}")
                print(f"Email sending failed: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {str(e)}")
            print(f"Email sending failed: {e}")
            return False
    
    def send_template_email(self, to_email, template_name, context, subject=None):
        """Send email using a template"""
        try:
            # Add common context variables
            context.update({
                'recipient_email': to_email,
                'current_year': timezone.now().year,
                'frontend_url': FRONTEND_URL,
            })
            
            # Render HTML template - use template_name directly since Django will look in the email_templates directory
            template_path = f'{template_name}.html'
            logger.info(f"Rendering template: {template_path}")
            try:
                html_content = render_to_string(template_path, context)
                logger.info(f"Template rendered successfully, length: {len(html_content)}")
            except Exception as template_error:
                logger.error(f"Template rendering failed for {template_path}: {str(template_error)}")
                print(f"Template error: {template_error}")
                return False
            
            # Generate subject if not provided
            if not subject:
                subject = self._get_default_subject(template_name, context)
            
            logger.info(f"Template rendered successfully, sending email to {to_email}")
            return self.send_email(to_email, subject, html_content)
        except Exception as e:
            # logger.error(f"Failed to send template email {template_name} to {to_email}: {str(e)}")
            print('failed to send email', e)
            return False
    
    def send_welcome_email(self, user):
        """Send welcome email to new user"""
        try:
            context = {
                'user_name': user.full_name,
                'dashboard_url': f"{FRONTEND_URL}/dashboard",
            }
            logger.info(f"Sending welcome email to {user.email}")
            return self.send_template_email(
                user.email,
                'welcome',
                context,
                "Welcome to Wozza! 🎉"
            )
            print('welcome email sent')
        except Exception as e:
            logger.error(f"Failed to send welcome email to {user.email}: {str(e)}")
            return False
    
    def send_subscription_expired_email(self, subscription):
        """Send subscription expired email"""
        context = {
            'user_name': subscription.user.full_name,
            'plan_name': subscription.plan.name if subscription.plan else "Trial Period",
            'expiry_date': subscription.current_period_end.strftime('%B %d, %Y'),
            'billing_url': f"{FRONTEND_URL}/billing",
        }
        return self.send_template_email(
            subscription.user.email,
            'subscription_expired',
            context,
            "Your subscription has expired"
        )
    
    def send_trial_ending_email(self, subscription, days_left=3):
        """Send trial ending email"""
        context = {
            'user_name': subscription.user.full_name,
            'trial_end_date': subscription.trial_end.strftime('%B %d, %Y') if subscription.trial_end else subscription.current_period_end.strftime('%B %d, %Y'),
            'upgrade_url': f"{FRONTEND_URL}/billing",
            'bot_count': subscription.user.bots.count(),
            'flow_count': sum(bot.flows.count() for bot in subscription.user.bots.all()),
            'message_count': 0,  # TODO: Implement message counting
        }
        return self.send_template_email(
            subscription.user.email,
            'trial_ending',
            context,
            f"Your trial ends in {days_left} days"
        )
    
    def send_payment_failed_email(self, subscription, retry_date=None):
        """Send payment failed email"""
        context = {
            'user_name': subscription.user.full_name,
            'plan_name': subscription.plan.name if subscription.plan else "Subscription",
            'billing_url': f"{FRONTEND_URL}/billing",
            'retry_date': retry_date.strftime('%B %d, %Y') if retry_date else "3 days",
        }
        return self.send_template_email(
            subscription.user.email,
            'payment_failed',
            context,
            "Payment failed - Action required"
        )
    
    def send_payment_success_email(self, subscription, amount, transaction_id):
        """Send payment success email"""
        context = {
            'user_name': subscription.user.full_name,
            'plan_name': subscription.plan.name if subscription.plan else "Subscription",
            'amount': amount,
            'transaction_id': transaction_id,
            'next_billing_date': subscription.current_period_end.strftime('%B %d, %Y'),
            'dashboard_url': f"{FRONTEND_URL}/dashboard",
        }
        return self.send_template_email(
            subscription.user.email,
            'payment_success',
            context,
            "Payment successful! 🎉"
        )
    
    def send_notification_email(self, user, title, message, bot_name=None, action_url=None, action_text=None):
        """Send notification email"""
        context = {
            'user_name': user.full_name,
            'title': title,
            'message': message,
            'bot_name': bot_name,
            'timestamp': timezone.now().strftime('%B %d, %Y at %I:%M %p'),
            'action_url': action_url,
            'action_text': action_text,
        }
        return self.send_template_email(
            user.email,
            'notification',
            context,
            title
        )
    
    def send_password_reset_email(self, user, reset_url):
        """Send password reset email"""
        context = {
            'user_name': user.full_name,
            'reset_url': reset_url,
        }
        return self.send_template_email(
            user.email,
            'password_reset',
            context,
            "Reset your password"
        )
    
    def _html_to_text(self, html_content):
        """Convert HTML to plain text (basic implementation)"""
        import re
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', html_content)
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
    
    def _get_default_subject(self, template_name, context):
        """Get default subject based on template name"""
        subjects = {
            'welcome': f"Welcome to Wozza, {context.get('user_name', '')}! 🎉",
            'subscription_expired': "Your subscription has expired",
            'trial_ending': "Your trial is ending soon",
            'payment_failed': "Payment failed - Action required",
            'payment_success': "Payment successful! 🎉",
            'notification': context.get('title', 'Notification'),
            'password_reset': "Reset your password",
        }
        return subjects.get(template_name, "Notification from Wozza")