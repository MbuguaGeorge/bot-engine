from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import SupportTicket, SupportTicketAttachment

@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'subject', 'category', 'status', 'created_at')
    list_filter = ('status', 'category', 'created_at')
    search_fields = ('subject', 'user__email', 'user__full_name')
    readonly_fields = ('created_at', 'updated_at', 'resolved_at')
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'subject', 'description', 'category', 'status')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'resolved_at'),
            'classes': ('collapse',)
        }),
        ('Admin Information', {
            'fields': ('assigned_to', 'internal_notes'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'assigned_to')

@admin.register(SupportTicketAttachment)
class SupportTicketAttachmentAdmin(admin.ModelAdmin):
    list_display = ('filename', 'ticket', 'uploaded_at')
    search_fields = ('filename', 'ticket__subject')
    list_filter = ('uploaded_at',)

# SupportTicketResponse admin removed - responses will be handled via email
