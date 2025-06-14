from django.contrib import admin
from .models import Bot

@admin.register(Bot)
class BotAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'phone_number', 'status', 'whatsapp_connected', 'created_at', 'last_updated')
    search_fields = ('name', 'user__email', 'phone_number')
    list_filter = ('status', 'whatsapp_connected', 'created_at', 'last_updated')
