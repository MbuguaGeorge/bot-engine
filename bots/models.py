from django.db import models
from django.conf import settings

class Bot(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('disconnected', 'Disconnected'),
    ]

    name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20, unique=True, null=True, blank=True, help_text="WhatsApp phone number in international format (e.g., +1234567890)")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='bots'
    )
    flow_data = models.JSONField(default=dict)
    whatsapp_connected = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_updated']
        unique_together = ['user', 'name']  # Prevent duplicate bot names per user

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"
