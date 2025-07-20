from django.contrib import admin
from .models import SubscriptionPlan, Subscription, PaymentMethod, Invoice, WebhookEvent

@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ('stripe_event_id', 'event_type', 'processed_at')
    list_filter = ('event_type', 'processed_at')
    search_fields = ('stripe_event_id', 'event_type')
    readonly_fields = ('stripe_event_id', 'processed_at')
    date_hierarchy = 'processed_at'
    ordering = ['-processed_at']

@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'plan_type', 'price', 'currency', 'interval', 'trial_days', 'is_active')
    list_filter = ('plan_type', 'is_active', 'interval')
    search_fields = ('name', 'stripe_price_id')
    readonly_fields = ('created_at', 'updated_at')

@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'get_plan_display', 'status', 'current_period_start', 'current_period_end', 'is_active', 'is_trialing')
    list_filter = ('status', 'created_at')  # Removed 'plan' from list_filter to avoid NoneType errors
    search_fields = ('user__email', 'stripe_subscription_id')
    readonly_fields = ('stripe_subscription_id', 'stripe_customer_id', 'created_at', 'updated_at')
    date_hierarchy = 'created_at'

    def get_plan_display(self, obj):
        if obj.plan:
            return obj.plan.name
        else:
            return "Trial Period"
    get_plan_display.short_description = 'Plan'

    def is_active(self, obj):
        return obj.is_active
    is_active.boolean = True

    def is_trialing(self, obj):
        return obj.is_trialing
    is_trialing.boolean = True

    def get_queryset(self, request):
        """Override to handle null plans safely"""
        return super().get_queryset(request).select_related('user', 'plan')

@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ('user', 'card_brand', 'card_last4', 'card_exp_month', 'card_exp_year', 'is_default')
    list_filter = ('card_brand', 'is_default', 'created_at')
    search_fields = ('user__email', 'stripe_payment_method_id')
    readonly_fields = ('stripe_payment_method_id', 'created_at')

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('subscription', 'stripe_invoice_id', 'amount', 'currency', 'status', 'created_at')
    list_filter = ('status', 'currency', 'created_at')
    search_fields = ('stripe_invoice_id', 'subscription__user__email')
    readonly_fields = ('stripe_invoice_id', 'created_at')
    date_hierarchy = 'created_at'
