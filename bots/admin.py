from django.contrib import admin
from .models import Bot, WhatsAppBusinessAccount, Notification

@admin.register(Bot)
class BotAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'phone_number', 'status', 'whatsapp_connected', 'created_at', 'last_updated')
    search_fields = ('name', 'user__email', 'phone_number')
    list_filter = ('status', 'whatsapp_connected', 'created_at', 'last_updated')


@admin.register(WhatsAppBusinessAccount)
class WhatsAppBusinessAccountAdmin(admin.ModelAdmin):
    list_display = ('bot', 'user', 'business_name', 'business_id', 'phone_number', 'created_at', 'updated_at')
    search_fields = ('bot', 'user__email', 'phone_number')
    list_filter = ('created_at', 'updated_at')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('type', 'bot', 'title', 'message', 'is_read', 'created_at')
    search_fields = ('bot', 'user__email', 'type')
    list_filter = ('is_read', 'type', 'created_at')