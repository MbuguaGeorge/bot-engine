from django.contrib import admin
from .models import (
    SubscriptionPlan, Subscription, PaymentMethod, Invoice, WebhookEvent,
    AIModel, UserCreditBalance, CreditUsageLog
)

@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'plan_type', 'price', 'currency', 'interval', 'credits_per_month', 'is_active')
    list_filter = ('plan_type', 'is_active', 'interval')
    search_fields = ('name',)
    ordering = ('plan_type', 'price')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'plan_type', 'stripe_price_id', 'price', 'currency', 'interval', 'trial_days', 'is_active')
        }),
        ('Credit System', {
            'fields': ('credits_per_month',),
            'description': 'Number of credits allocated per billing cycle'
        }),
    )

@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'status', 'current_period_end', 'is_active')
    list_filter = ('status', 'plan', 'created_at')
    search_fields = ('user__email', 'user__full_name', 'stripe_subscription_id')
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'created_at'

@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ('user', 'card_brand', 'card_last4', 'is_default', 'created_at')
    list_filter = ('card_brand', 'is_default', 'created_at')
    search_fields = ('user__email', 'stripe_payment_method_id')
    readonly_fields = ('created_at',)

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('subscription', 'amount', 'currency', 'status', 'created_at')
    list_filter = ('status', 'currency', 'created_at')
    search_fields = ('stripe_invoice_id', 'subscription__user__email')
    readonly_fields = ('created_at',)

@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'stripe_event_id', 'processed_at')
    list_filter = ('event_type', 'processed_at')
    search_fields = ('stripe_event_id', 'event_type')
    readonly_fields = ('processed_at',)

# Credit System Admin
@admin.register(AIModel)
class AIModelAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'provider', 'name', 'cost_per_1k_tokens', 'credit_conversion_rate', 'is_active')
    list_filter = ('provider', 'is_active')
    search_fields = ('name', 'display_name')
    ordering = ('provider', 'display_name')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'provider', 'display_name', 'is_active')
        }),
        ('Pricing Configuration', {
            'fields': ('cost_per_1k_tokens', 'credit_conversion_rate'),
            'description': 'Configure pricing and credit conversion rates for this model'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ('created_at', 'updated_at')

@admin.register(UserCreditBalance)
class UserCreditBalanceAdmin(admin.ModelAdmin):
    list_display = ('user', 'credits_remaining', 'credits_used_this_period', 'credits_reset_date')
    list_filter = ('credits_reset_date', 'created_at')
    search_fields = ('user__email', 'user__full_name')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('User Information', {
            'fields': ('user',)
        }),
        ('Credit Balance', {
            'fields': ('credits_remaining', 'credits_used_this_period', 'credits_reset_date')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(CreditUsageLog)
class CreditUsageLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'model', 'input_tokens', 'output_tokens', 'credits_deducted', 'created_at')
    list_filter = ('model__provider', 'created_at', 'model')
    search_fields = ('user__email', 'model__name', 'request_id')
    readonly_fields = ('created_at',)
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Usage Information', {
            'fields': ('user', 'model', 'bot', 'request_id')
        }),
        ('Token Usage', {
            'fields': ('input_tokens', 'output_tokens')
        }),
        ('Cost Information', {
            'fields': ('cost_usd', 'credits_deducted')
        }),
        ('Timestamps', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        """Prevent manual creation of usage logs"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """Prevent editing of usage logs"""
        return False
