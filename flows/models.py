from django.db import models
from django.core.exceptions import ValidationError
from bots.models import Bot

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
