from django.db import models
from django.conf import settings
from django.utils import timezone
import stripe

stripe.api_key = settings.STRIPE_SECRET_KEY

class WebhookEvent(models.Model):
    """Track processed webhook events to prevent duplicates"""
    stripe_event_id = models.CharField(max_length=255, unique=True, db_index=True)
    event_type = models.CharField(max_length=100)
    processed_at = models.DateTimeField(auto_now_add=True)
    data = models.JSONField(default=dict, blank=True)  # Store event data for debugging
    
    class Meta:
        ordering = ['-processed_at']
    
    def __str__(self):
        return f"{self.event_type} - {self.stripe_event_id}"

class SubscriptionPlan(models.Model):
    PLAN_TYPES = [
        ('basic', 'Basic'),
        ('pro', 'Professional'),
        ('enterprise', 'Enterprise'),
    ]
    
    name = models.CharField(max_length=100)
    plan_type = models.CharField(max_length=20, choices=PLAN_TYPES)
    stripe_price_id = models.CharField(max_length=100, unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='usd')
    interval = models.CharField(max_length=20, default='month')  # month, year
    trial_days = models.IntegerField(default=14)
    
    # Credit-based system - only credits matter
    credits_per_month = models.IntegerField(default=1000)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - ${self.price}/{self.interval}"
    
    def get_features_dict(self):
        """Get features as a dictionary for frontend compatibility"""
        return {
            "credits_per_month": self.credits_per_month,
            "support": {
                "chat": True,
                "email": True,
                "priority": "standard"
            },
            "api_access": False,
            "custom_branding": False,
            "credits_per_month": self.credits_per_month
        }

class Subscription(models.Model):
    STATUS_CHOICES = [
        ('trialing', 'Trialing'),
        ('active', 'Active'),
        ('past_due', 'Past Due'),
        ('canceled', 'Canceled'),
        ('unpaid', 'Unpaid'),
        ('incomplete', 'Incomplete'),
        ('incomplete_expired', 'Incomplete Expired'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='subscriptions')
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.CASCADE, related_name='subscriptions', null=True, blank=True)
    stripe_subscription_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    stripe_customer_id = models.CharField(max_length=100, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='incomplete')
    current_period_start = models.DateTimeField()
    current_period_end = models.DateTimeField()
    trial_start = models.DateTimeField(null=True, blank=True)
    trial_end = models.DateTimeField(null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Trial-specific fields
    is_trial_user = models.BooleanField(default=False)
    trial_credits_allocated = models.BooleanField(default=False)

    def __str__(self):
        plan_name = self.plan.name if self.plan else "Trial Period"
        return f"{self.user.email} - {plan_name} ({self.status})"

    @property
    def is_active(self):
        return self.status in ['trialing', 'active']

    @property
    def is_trialing(self):
        return self.status == 'trialing'

    @property
    def days_until_expiry(self):
        if self.current_period_end:
            delta = self.current_period_end - timezone.now()
            return max(0, delta.days)
        return 0
    
    @property
    def is_trial_expired(self):
        """Check if trial has expired"""
        if self.trial_end:
            return timezone.now() > self.trial_end
        return False

class PaymentMethod(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='payment_methods')
    stripe_payment_method_id = models.CharField(max_length=100, unique=True)
    card_brand = models.CharField(max_length=20)
    card_last4 = models.CharField(max_length=4)
    card_exp_month = models.IntegerField()
    card_exp_year = models.IntegerField()
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.email} - {self.card_brand} ****{self.card_last4}"

class Invoice(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('open', 'Open'),
        ('paid', 'Paid'),
        ('uncollectible', 'Uncollectible'),
        ('void', 'Void'),
    ]

    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name='invoices')
    stripe_invoice_id = models.CharField(max_length=100, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='usd')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    invoice_pdf = models.URLField(blank=True)
    hosted_invoice_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Invoice {self.stripe_invoice_id} - {self.subscription.user.email}"

# Credit System Models
class AIModel(models.Model):
    """AI models available for credit-based usage"""
    MODEL_PROVIDERS = [
        ('openai', 'OpenAI'),
        ('anthropic', 'Anthropic'),
        ('google', 'Google'),
    ]
    
    name = models.CharField(max_length=100, unique=True)  # e.g., "gpt-4o", "claude-3-sonnet", "gemini-pro"
    provider = models.CharField(max_length=20, choices=MODEL_PROVIDERS)
    display_name = models.CharField(max_length=100)  # e.g., "GPT-4o", "Claude 3 Sonnet", "Gemini Pro"
    is_active = models.BooleanField(default=True)
    cost_per_1k_tokens = models.DecimalField(max_digits=10, decimal_places=6)  # Cost in USD per 1K tokens
    credit_conversion_rate = models.DecimalField(max_digits=10, decimal_places=6)  # Credits per $0.002 worth of tokens
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['provider', 'name']
    
    def __str__(self):
        return f"{self.display_name} ({self.provider})"
    
    def calculate_credits(self, input_tokens, output_tokens):
        """Calculate credits needed for a request"""
        from decimal import Decimal
        
        # Convert to Decimal for precise calculations
        input_tokens = Decimal(str(input_tokens))
        output_tokens = Decimal(str(output_tokens))
        
        total_cost = (
            (input_tokens / Decimal('1000')) * self.cost_per_1k_tokens +
            (output_tokens / Decimal('1000')) * self.cost_per_1k_tokens
        )
        return round(total_cost / Decimal('0.002') * self.credit_conversion_rate, 6)

class UserCreditBalance(models.Model):
    """Track user's credit balance"""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='credit_balance')
    credits_remaining = models.IntegerField(default=0)
    credits_used_this_period = models.IntegerField(default=0)
    credits_reset_date = models.DateTimeField()  # When credits reset (usually billing cycle)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Trial-specific fields
    is_trial_user = models.BooleanField(default=False)
    trial_credits_allocated = models.BooleanField(default=False)
    
    def __str__(self):
        return f"{self.user.email} - {self.credits_remaining} credits remaining"
    
    def has_sufficient_credits(self, required_credits):
        """Check if user has enough credits"""
        return self.credits_remaining >= required_credits
    
    def deduct_credits(self, credits_to_deduct):
        """Deduct credits from balance"""
        from decimal import Decimal
        
        # Convert to Decimal for comparison, then to int for storage
        credits_to_deduct_decimal = Decimal(str(credits_to_deduct))
        credits_remaining_decimal = Decimal(str(self.credits_remaining))
        
        if credits_remaining_decimal >= credits_to_deduct_decimal:
            self.credits_remaining = int(credits_remaining_decimal - credits_to_deduct_decimal)
            self.credits_used_this_period = int(Decimal(str(self.credits_used_this_period)) + credits_to_deduct_decimal)
            self.save()
            return True
        return False
    
    def add_credits(self, credits_to_add):
        """Add credits to balance"""
        from decimal import Decimal
        
        # Convert to Decimal for calculation, then to int for storage
        credits_to_add_decimal = Decimal(str(credits_to_add))
        self.credits_remaining = int(Decimal(str(self.credits_remaining)) + credits_to_add_decimal)
        self.save()
        return True
    
    def reset_trial_credits(self):
        """Reset credits to 0 for expired trial users"""
        self.credits_remaining = 0
        self.credits_used_this_period = 0
        self.is_trial_user = False
        self.save()
        
        logger.info(f"Trial credits reset to 0 for user {self.user.email}")
        return True

class CreditUsageLog(models.Model):
    """Log all credit usage for auditing and analytics"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='credit_usage_logs')
    model = models.ForeignKey(AIModel, on_delete=models.CASCADE, related_name='usage_logs')
    bot = models.ForeignKey('bots.Bot', on_delete=models.CASCADE, related_name='credit_usage_logs', null=True, blank=True)
    input_tokens = models.IntegerField()
    output_tokens = models.IntegerField()
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6)
    credits_deducted = models.DecimalField(max_digits=10, decimal_places=6)
    request_id = models.CharField(max_length=100, blank=True)  # For tracking specific requests
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.email} - {self.model.name} - {self.credits_deducted} credits"
