from django.db import models
from django.conf import settings
from django.contrib.postgres.fields import JSONField

class Bot(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('disconnected', 'Disconnected'),
    ]

    name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=50, unique=True, null=True, blank=True, help_text="WhatsApp phone number in international format (e.g., +1234567890)")
    phone_number_id = models.CharField(max_length=255, unique=True, null=True, blank=True, help_text="WhatsApp phone number ID")
    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default='draft'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='bots'
    )
    whatsapp_connected = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    notification_settings = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-last_updated']
        unique_together = ['user', 'name']  # Prevent duplicate bot names per user

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"


class WhatsAppBusinessAccount(models.Model):
    bot = models.OneToOneField(
        Bot,
        on_delete=models.CASCADE,
        related_name='waba',
        help_text="The bot this WABA is connected to."
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='wabas',
        help_text="The user who owns this WABA."
    )
    business_id = models.CharField(null=True, blank=True, max_length=255, help_text="WABA Business ID from Meta")
    business_name = models.CharField(null=True, blank=True, max_length=128, help_text="WABA Business Name from Meta")
    access_token = models.TextField(null=True, blank=True, help_text="WABA Business Access Token from Meta")
    phone_number_id = models.CharField(null=True, blank=True, max_length=255, help_text="WhatsApp Phone Number ID from Meta")
    phone_number = models.CharField(null=True, blank=True, max_length=50, help_text="WhatsApp phone number in international format (e.g., +1234567890)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        unique_together = ['user', 'business_id', 'phone_number_id']

    def __str__(self):
        return f"{self.user.email} --> {self.business_id}"


class NotificationManager(models.Manager):
    def create_notification(self, *, user, bot=None, type, title, message, data=None):
        # Check bot notification settings if bot is provided
        if bot and hasattr(bot, 'notification_settings'):
            settings = bot.notification_settings or {}
            # If the notification type is disabled, do not create
            if settings.get(type) is False:
                return None
        notification = self.create(
            user=user,
            bot=bot,
            type=type,
            title=title,
            message=message,
            data=data or {}
        )
        return notification

class Notification(models.Model):
    NOTIFICATION_TYPES = [
        ('bot_online', 'Bot Online'),
        ('bot_offline', 'Bot Offline'),
        ('new_message', 'New Message'),
        ('message_failure', 'Message Failure'),
        ('new_chat', 'New Chat'),
        ('whatsapp_connected', 'WhatsApp Connected'),
        ('whatsapp_disconnected', 'WhatsApp Disconnected'),
        ('bot_created', 'Bot Created'),
        ('bot_deleted', 'Bot Deleted'),
        ('bot_duplicated', 'Bot Duplicated'),
        ('flow_published', 'Flow Published'),
        ('flow_archived', 'Flow Archived'),
        # Add more as needed
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    bot = models.ForeignKey('Bot', on_delete=models.CASCADE, null=True, blank=True, related_name='notifications')
    type = models.CharField(max_length=32, choices=NOTIFICATION_TYPES)
    title = models.CharField(max_length=128)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    data = models.JSONField(default=dict, blank=True)

    objects = NotificationManager()

    class Meta:
        ordering = ['-created_at']
