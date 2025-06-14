from django.contrib import admin
from .models import Flow

@admin.register(Flow)
class FlowAdmin(admin.ModelAdmin):
    list_display = ('name', 'bot', 'status', 'is_active', 'created_at', 'updated_at')
    search_fields = ('name', 'bot__name')
    list_filter = ('status', 'is_active', 'created_at', 'updated_at')
