from django.contrib import admin
from .models import Flow, UploadedFile, GoogleDocCache

@admin.register(Flow)
class FlowAdmin(admin.ModelAdmin):
    list_display = ('name', 'bot', 'status', 'is_active', 'created_at', 'updated_at')
    search_fields = ('name', 'bot__name')
    list_filter = ('status', 'is_active', 'created_at', 'updated_at')

@admin.register(UploadedFile)
class UploadedFileAdmin(admin.ModelAdmin):
    list_display = ('name', 'flow', 'uploaded_at')
    search_fields = ('name', 'flow__name')
    list_filter = ('uploaded_at',)

@admin.register(GoogleDocCache)
class GoogleDocCacheAdmin(admin.ModelAdmin):
    list_display = ('link', 'flow', 'node_id', 'last_fetched')
    search_fields = ('link', 'flow__name')
    list_filter = ('last_fetched',)