from django.db import models
from django.core.exceptions import ValidationError
from bots.models import Bot
from django.conf import settings

class Flow(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('archived', 'Archived')
    ]

    name = models.CharField(max_length=255)
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE, related_name='flows')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    is_active = models.BooleanField(default=False)
    flow_data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        unique_together = ['bot', 'name']

    def __str__(self):
        return f"{self.name} - {self.bot.name} ({self.get_status_display()})"

    def clean(self):
        if self.is_active:
            # Check if there's another active flow for this bot
            active_flows = Flow.objects.filter(bot=self.bot, is_active=True)
            if self.pk:
                active_flows = active_flows.exclude(pk=self.pk)
            if active_flows.exists():
                raise ValidationError("Only one flow can be active per bot.")

    def save(self, *args, **kwargs):
        # If this flow is being activated
        if self.is_active:
            # Deactivate all other flows for this bot
            Flow.objects.filter(bot=self.bot).exclude(pk=self.pk).update(is_active=False)
            # Set status to active
            self.status = 'active'
        elif self.status == 'active':
            # If status is active but is_active is False, sync them
            self.is_active = True
        
        self.clean()
        super().save(*args, **kwargs)


def flow_directory_path(instance, filename):
    """
    Generates a unique path for each uploaded file.
    Example: flows/<bot_id>/<flow_id>/<filename>
    """
    return f'flows/{instance.flow.bot.id}/{instance.flow.id}/{filename}'

class UploadedFile(models.Model):
    """
    Represents a file uploaded by a user for a specific flow,
    to be used in AI nodes for context.
    """
    flow = models.ForeignKey(Flow, on_delete=models.CASCADE, related_name='uploaded_files')
    node_id = models.CharField(max_length=255, null=True, blank=True, help_text="The ID of the node within the flow this file belongs to.")
    name = models.CharField(max_length=255, help_text="Original name of the file.")
    file = models.FileField(upload_to=flow_directory_path)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.name} for Flow ID {self.flow.id}"

    def delete(self, *args, **kwargs):
        # Delete the file from storage as well
        self.file.delete(save=False)
        super().delete(*args, **kwargs)


class GoogleDocCache(models.Model):
    link = models.URLField(unique=True)
    last_hash = models.CharField(max_length=128, blank=True, null=True)
    last_fetched = models.DateTimeField(auto_now=True)
    flow = models.ForeignKey(Flow, on_delete=models.CASCADE, related_name='gdoc_caches')
    node_id = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return self.link


class Conversation(models.Model):
    """
    Represents a WhatsApp chat conversation for handoff tracking.
    """
    conversation_id = models.CharField(max_length=255, unique=True, db_index=True)
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE, related_name='conversations')
    user_id = models.CharField(max_length=255, db_index=True)
    handoff_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        unique_together = ['bot', 'conversation_id']

    def __str__(self):
        return f"Conversation {self.conversation_id} (Bot {self.bot_id}) Handoff: {self.handoff_active}"


class GoogleOAuthToken(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='google_oauth_token')
    access_token = models.TextField()
    refresh_token = models.TextField()
    expires_at = models.DateTimeField()
    scope = models.TextField()
    token_type = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Google OAuth Token'
        verbose_name_plural = 'Google OAuth Tokens'

class GoogleUserFile(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='google_user_files')
    link = models.URLField()
    file_id = models.CharField(max_length=128)
    file_type = models.CharField(max_length=32)  # doc, sheet
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Google User File'
        verbose_name_plural = 'Google User Files'