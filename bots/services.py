import os
from django.conf import settings as django_settings
from celery import shared_task
from django.utils import timezone
from datetime import timedelta
import sendgrid
from sendgrid.helpers.mail import Mail, Email, To, Content
from .models import Notification, NotificationSettings
from django.contrib.auth import get_user_model
from .notification_types import NOTIFICATION_EVENT_TYPES

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")

def sendgrid_email(to_email, subject, message):
    if not SENDGRID_API_KEY:
        raise Exception("SENDGRID_API_KEY not set in environment")
    sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
    from_email = django_settings.DEFAULT_FROM_EMAIL or "no-reply@flowbotic.com"
    mail = Mail(
        from_email=Email(from_email),
        to_emails=To(to_email),
        subject=subject,
        plain_text_content=Content("text/plain", message),
    )
    try:
        sg.send(mail)
    except Exception as e:
        # Optionally log error
        pass

class NotificationService:
    @staticmethod
    def create_and_send(user, type, title, message, bot=None, data=None, force_email=False):
        try:
            notif_settings = NotificationSettings.get_for_user(user)
        except NotificationSettings.DoesNotExist:
            notif_settings = NotificationSettings.objects.create(user=user)
        
        # Map event type to field for bot activity
        event_type_to_field = {
            "bot_online": "bot_online_offline",
            "bot_offline": "bot_online_offline",
            "new_message": "new_messages",
            "message_failure": "failed_delivery",
            "new_chat": "new_chat_started",
            # Add more as needed
        }
        
        # Check specific notification type settings FIRST
        if type in event_type_to_field:
            field = event_type_to_field[type]
            if not getattr(notif_settings, field, True):
                return  # User has this bot activity type off
        
        # Check marketing/updates settings
        if type == "marketing_emails" and not notif_settings.marketing_emails:
            return
        if type == "platform_updates" and not notif_settings.platform_updates:
            return
        
        # Only proceed with delivery if the specific type is enabled
        # Email notifications
        if (notif_settings.email_notifications or force_email):
            NotificationService.send_notification_email.delay(user.id, type, title, message, data)
        
        # In-app/browser notifications
        if notif_settings.in_app_notifications:
            Notification.objects.create_notification(user=user, bot=bot, type=type, title=title, message=message, data=data)
        
        # For SMS (future)
        # if type == "sms" and notif_settings.sms_notifications:
        #     # Send SMS notification
        #     pass

    @staticmethod
    @shared_task
    def send_notification_email(user_id, type, title, message, data=None):
        User = get_user_model()
        user = User.objects.get(id=user_id)
        sendgrid_email(user.email, subject=title, message=message)

    @staticmethod
    @shared_task
    def send_summary_email(user_id):
        User = get_user_model()
        user = User.objects.get(id=user_id)
        notif_settings = NotificationSettings.get_for_user(user)
        unread_count = Notification.objects.filter(user=user, type="new_message", is_read=False).count()
        if unread_count == 0:
            return
        last_login = user.last_login or user.date_joined
        inactive_minutes = (timezone.now() - last_login).total_seconds() / 60
        if inactive_minutes < notif_settings.inactivity_threshold_minutes:
            return
        NotificationService.send_notification_email.delay(
            user.id,
            "unread_message_summary",
            "You have unread messages",
            f"You have {unread_count} unread customer messages in your Flowbotic account.",
        )

    @staticmethod
    @shared_task
    def send_summaries_to_inactive_users():
        User = get_user_model()
        for user in User.objects.filter(is_active=True):
            NotificationService.send_summary_email.delay(user.id)
