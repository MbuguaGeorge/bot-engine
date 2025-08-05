from rest_framework import serializers
from .models import SubscriptionPlan, Subscription, PaymentMethod, Invoice, AIModel, UserCreditBalance, CreditUsageLog

class SubscriptionPlanSerializer(serializers.ModelSerializer):
    features = serializers.SerializerMethodField()
    
    def get_features(self, obj):
        return obj.get_features_dict()
    
    class Meta:
        model = SubscriptionPlan
        fields = [
            'id', 'name', 'plan_type', 'stripe_price_id', 'price', 
            'currency', 'interval', 'trial_days', 'features', 'is_active',
            'credits_per_month'
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
        if data['plan'] is None and instance.is_trialing:
            data['plan'] = {
                'id': None,
                'name': 'Trial Period',
                'plan_type': 'trial',
                'stripe_price_id': None,
                'price': 0,
                'currency': 'usd',
                'interval': 'month',
                'trial_days': 14,
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
                'is_active': True,
                'credits_per_month': 500
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

# Credit System Serializers
class AIModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIModel
        fields = [
            'id', 'name', 'provider', 'display_name', 'is_active',
            'cost_per_1k_tokens', 'credit_conversion_rate', 'created_at'
        ]

class UserCreditBalanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserCreditBalance
        fields = [
            'id', 'credits_remaining', 'credits_used_this_period',
            'credits_reset_date', 'created_at', 'updated_at'
        ]

class CreditUsageLogSerializer(serializers.ModelSerializer):
    model_name = serializers.CharField(source='model.display_name', read_only=True)
    model_provider = serializers.CharField(source='model.provider', read_only=True)
    
    class Meta:
        model = CreditUsageLog
        fields = [
            'id', 'model', 'model_name', 'model_provider', 'bot',
            'input_tokens', 'output_tokens', 'cost_usd', 'credits_deducted',
            'request_id', 'created_at'
        ]
        read_only_fields = ['id', 'cost_usd', 'credits_deducted', 'created_at']

class CreditUsageRequestSerializer(serializers.Serializer):
    """Serializer for credit usage requests"""
    model_name = serializers.CharField()
    input_tokens = serializers.IntegerField()
    output_tokens = serializers.IntegerField()
    bot_id = serializers.IntegerField(required=False)
    request_id = serializers.CharField(required=False)

class AdminCreditAdjustmentSerializer(serializers.Serializer):
    """Serializer for admin credit adjustments"""
    user_id = serializers.IntegerField()
    credits_to_add = serializers.IntegerField()
    reason = serializers.CharField(required=False) 