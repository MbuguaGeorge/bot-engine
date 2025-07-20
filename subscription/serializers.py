from rest_framework import serializers
from .models import SubscriptionPlan, Subscription, PaymentMethod, Invoice

class SubscriptionPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPlan
        fields = [
            'id', 'name', 'plan_type', 'stripe_price_id', 'price', 
            'currency', 'interval', 'trial_days', 'features', 'is_active'
        ]

class PaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentMethod
        fields = [
            'id', 'stripe_payment_method_id', 'card_brand', 'card_last4',
            'card_exp_month', 'card_exp_year', 'is_default', 'created_at'
        ]

class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = [
            'id', 'stripe_invoice_id', 'amount', 'currency', 'status',
            'invoice_pdf', 'hosted_invoice_url', 'created_at'
        ]

class SubscriptionSerializer(serializers.ModelSerializer):
    plan = SubscriptionPlanSerializer(read_only=True, allow_null=True)
    payment_methods = PaymentMethodSerializer(many=True, read_only=True)
    invoices = InvoiceSerializer(many=True, read_only=True)
    days_until_expiry = serializers.ReadOnlyField()
    is_active = serializers.ReadOnlyField()
    is_trialing = serializers.ReadOnlyField()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        
        # If plan is null (trial subscription), provide a default trial plan structure
        if data['plan'] is None:
            data['plan'] = {
                'id': None,
                'name': 'Trial Period',
                'plan_type': 'trial',
                'stripe_price_id': None,
                'price': 0,
                'currency': 'usd',
                'interval': 'month',
                'trial_days': 7,
                'features': {
                    'bots_limit': 3,
                    'messages_per_month': 1000,
                    'ai_requests_per_month': 500,
                    'support': {
                        'email': True,
                        'chat': False,
                        'phone': False
                    },
                    'advanced_analytics': False,
                    'custom_branding': False,
                    'api_access': False,
                    'priority_support': False
                },
                'is_active': True
            }
        
        return data

    class Meta:
        model = Subscription
        fields = [
            'id', 'plan', 'stripe_subscription_id', 'status', 'current_period_start',
            'current_period_end', 'trial_start', 'trial_end', 'canceled_at',
            'days_until_expiry', 'is_active', 'is_trialing', 'payment_methods',
            'invoices', 'created_at'
        ]

class CreateSubscriptionSerializer(serializers.Serializer):
    plan_id = serializers.IntegerField()
    payment_method_id = serializers.CharField(required=False)
    trial_from_plan = serializers.BooleanField(default=True)

class CancelSubscriptionSerializer(serializers.Serializer):
    cancel_at_period_end = serializers.BooleanField(default=True)

class UpdatePaymentMethodSerializer(serializers.Serializer):
    payment_method_id = serializers.CharField() 