import stripe
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
import logging
from django.db import models
from datetime import datetime, timezone as dt_timezone
from .models import Invoice, Subscription
from subscription.models import UserCreditBalance

logger = logging.getLogger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY

class StripeService:
    @staticmethod
    def create_customer(user):
        """Create a Stripe customer for the user"""
        try:
            customer = stripe.Customer.create(
                email=user.email,
                name=user.full_name,
                metadata={'user_id': user.id}
            )
            return customer
        except stripe.error.StripeError as e:
            raise Exception(f"Failed to create Stripe customer: {str(e)}")

    @staticmethod
    def create_subscription(user, plan, payment_method_id=None, trial_from_plan=True):
        """Create a subscription in Stripe"""
        try:
            # Get or create customer
            customer = StripeService.get_or_create_customer(user)
            
            # Prepare subscription data
            subscription_data = {
                'customer': customer.id,
                'items': [{'price': plan.stripe_price_id}],
                'metadata': {
                    'user_id': user.id,
                    'plan_id': plan.id
                }
            }
            
            # Add trial if enabled
            if trial_from_plan and plan.trial_days > 0:
                subscription_data['trial_period_days'] = plan.trial_days
            
            # Add payment method if provided
            if payment_method_id:
                subscription_data['default_payment_method'] = payment_method_id
            
            # Create subscription
            stripe_subscription = stripe.Subscription.create(**subscription_data)
            
            # Use get_or_create to prevent duplicates
            subscription, created = Subscription.objects.get_or_create(
                stripe_subscription_id=stripe_subscription.id,
                defaults={
                    'user': user,
                    'plan': plan,
                    'stripe_customer_id': customer.id,
                    'status': stripe_subscription.status,
                    'current_period_start': datetime.fromtimestamp(stripe_subscription.get('current_period_start'), tz=dt_timezone.utc) if stripe_subscription.get('current_period_start') else timezone.now(),
                    'current_period_end': datetime.fromtimestamp(stripe_subscription.get('current_period_end'), tz=dt_timezone.utc) if stripe_subscription.get('current_period_end') else timezone.now() + timedelta(days=30),
                    'trial_start': datetime.fromtimestamp(stripe_subscription.get('trial_start'), tz=dt_timezone.utc) if stripe_subscription.get('trial_start') else None,
                    'trial_end': datetime.fromtimestamp(stripe_subscription.get('trial_end'), tz=dt_timezone.utc) if stripe_subscription.get('trial_end') else None,
                }
            )
            
            if not created:
                print(f"Subscription {stripe_subscription.id} already exists, returning existing")
            
            return subscription
            
        except stripe.error.StripeError as e:
            raise Exception(f"Failed to create subscription: {str(e)}")
        except Exception as e:
            raise Exception(f"An error occurred while creating subscription: {str(e)}")

    @staticmethod
    def upgrade_subscription(user, new_plan, payment_method_id=None):
        """Upgrade an existing subscription with proration"""
        try:
            print(f"Starting upgrade for user {user.id} to plan {new_plan.id}")
            
            # Get current active subscription
            current_subscription = Subscription.objects.filter(user=user, status__in=['trialing', 'active']).first()
            if not current_subscription:
                raise Exception("No active subscription to upgrade.")
            
            print(f"Found current subscription: {current_subscription.id}")
            
            # Get current subscription to verify it exists and get items
            print(f"Retrieving Stripe subscription: {current_subscription.stripe_subscription_id}")
            stripe_subscription = stripe.Subscription.retrieve(current_subscription.stripe_subscription_id)
            print(f"Stripe subscription retrieved: {stripe_subscription.id}")
            
            # Get the existing subscription item ID using the correct approach
            print("Getting existing subscription items...")
            # Access items directly from the subscription object
            subscription_items = stripe_subscription['items']['data']
            print(f"Found {len(subscription_items)} subscription items")
            
            if not subscription_items:
                raise Exception("No subscription items found.")
            
            # Get the first (and usually only) subscription item
            existing_item = subscription_items[0]
            existing_item_id = existing_item['id']
            print(f"Existing item ID: {existing_item_id}")
            print(f"New plan price ID: {new_plan.stripe_price_id}")
            
            # Determine if this is an upgrade or downgrade based on price
            current_price = current_subscription.plan.price if current_subscription.plan else 0
            new_price = new_plan.price
            is_upgrade = new_price > current_price
            
            # Choose proration behavior based on upgrade/downgrade
            if is_upgrade:
                # For upgrades: immediately invoice the prorated amount so user gets immediate access
                proration_behavior = 'always_invoice'
                print(f"This is an upgrade (${current_price} → ${new_price}). Using 'always_invoice' for immediate access.")
            else:
                # For downgrades: create prorations but don't invoice until next cycle
                proration_behavior = 'create_prorations'
                print(f"This is a downgrade (${current_price} → ${new_price}). Using 'create_prorations' for end-of-cycle change.")
            
            # Update the existing subscription item with the new price
            print("Modifying Stripe subscription...")
            stripe_subscription = stripe.Subscription.modify(
                current_subscription.stripe_subscription_id,
                cancel_at_period_end=False,
                proration_behavior=proration_behavior,
                items=[{
                    'id': existing_item_id,  # Use existing item ID
                    'price': new_plan.stripe_price_id,  # Update to new price
                }],
                default_payment_method=payment_method_id or None
            )
            print(f"Stripe subscription modified successfully: {stripe_subscription.id}")
            
            # Sync local subscription
            print("Updating local subscription...")
            Subscription.objects.filter(id=current_subscription.id).update(
                plan=new_plan,
                status=stripe_subscription.status,
                current_period_start=datetime.fromtimestamp(stripe_subscription.get('current_period_start'), tz=dt_timezone.utc) if stripe_subscription.get('current_period_start') else timezone.now(),
                current_period_end=datetime.fromtimestamp(stripe_subscription.get('current_period_end'), tz=dt_timezone.utc) if stripe_subscription.get('current_period_end') else timezone.now() + timedelta(days=30),
                trial_start=datetime.fromtimestamp(stripe_subscription.get('trial_start'), tz=dt_timezone.utc) if stripe_subscription.get('trial_start') else None,
                trial_end=datetime.fromtimestamp(stripe_subscription.get('trial_end'), tz=dt_timezone.utc) if stripe_subscription.get('trial_end') else None,
            )
            
            # Optionally sync invoices
            print("Syncing invoice history...")
            StripeService.get_invoice_history(current_subscription)
            
            result = Subscription.objects.get(id=current_subscription.id)
            print(f"Upgrade completed successfully for subscription {result.id}")
            return result
            
        except stripe.error.StripeError as e:
            print(f"Stripe error in upgrade: {str(e)}")
            raise Exception(f"Failed to upgrade subscription: {str(e)}")
        except Exception as e:
            print(f"General error in upgrade: {str(e)}")
            import traceback
            traceback.print_exc()
            raise Exception(f"An error occurred while upgrading subscription: {str(e)}")

    @staticmethod
    def get_or_create_customer(user):
        """Get existing customer or create new one"""
        try:
            # Check if user already has a subscription with customer ID
            existing_subscription = Subscription.objects.filter(user=user).first()
            if existing_subscription:
                return stripe.Customer.retrieve(existing_subscription.stripe_customer_id)
            
            # Create new customer
            return StripeService.create_customer(user)
            
        except stripe.error.StripeError as e:
            raise Exception(f"Failed to get/create customer: {str(e)}")

    @staticmethod
    def cancel_subscription(subscription, cancel_at_period_end=True):
        """Cancel a subscription"""
        try:
            if cancel_at_period_end:
                stripe_subscription = stripe.Subscription.modify(
                    subscription.stripe_subscription_id,
                    cancel_at_period_end=True
                )
            else:
                stripe_subscription = stripe.Subscription.cancel(
                    subscription.stripe_subscription_id
                )
            
            # Update local record
            subscription.status = stripe_subscription.status
            subscription.canceled_at = timezone.now()
            subscription.save()
            
            return subscription
            
        except stripe.error.StripeError as e:
            raise Exception(f"Failed to cancel subscription: {str(e)}")

    @staticmethod
    def update_subscription_payment_method(subscription, payment_method_id):
        """Update subscription payment method"""
        try:
            stripe.Subscription.modify(
                subscription.stripe_subscription_id,
                default_payment_method=payment_method_id
            )
            
            # Update local payment method
            PaymentMethod.objects.filter(user=subscription.user, is_default=True).update(is_default=False)
            PaymentMethod.objects.filter(stripe_payment_method_id=payment_method_id).update(is_default=True)
            
        except stripe.error.StripeError as e:
            raise Exception(f"Failed to update payment method: {str(e)}")

    @staticmethod
    def sync_subscription_from_stripe(stripe_subscription_id):
        """Sync subscription data from Stripe"""
        try:
            stripe_subscription = stripe.Subscription.retrieve(stripe_subscription_id)
            subscription = Subscription.objects.get(stripe_subscription_id=stripe_subscription_id)
            
            subscription.status = stripe_subscription.status
            subscription.current_period_start = datetime.fromtimestamp(stripe_subscription.get('current_period_start'), tz=dt_timezone.utc) if stripe_subscription.get('current_period_start') else timezone.now()
            subscription.current_period_end = datetime.fromtimestamp(stripe_subscription.get('current_period_end'), tz=dt_timezone.utc) if stripe_subscription.get('current_period_end') else timezone.now() + timedelta(days=30)
            subscription.trial_start = datetime.fromtimestamp(stripe_subscription.get('trial_start'), tz=dt_timezone.utc) if stripe_subscription.get('trial_start') else None
            subscription.trial_end = datetime.fromtimestamp(stripe_subscription.get('trial_end'), tz=dt_timezone.utc) if stripe_subscription.get('trial_end') else None
            subscription.canceled_at = datetime.fromtimestamp(stripe_subscription.get('canceled_at'), tz=dt_timezone.utc) if stripe_subscription.get('canceled_at') else None
            subscription.save()
            
            return subscription
            
        except stripe.error.StripeError as e:
            raise Exception(f"Failed to sync subscription: {str(e)}")

    @staticmethod
    def create_payment_method(user, payment_method_id):
        """Create payment method record"""
        try:
            payment_method = stripe.PaymentMethod.retrieve(payment_method_id)
            
            # Attach to customer
            customer = StripeService.get_or_create_customer(user)
            payment_method.attach(customer=customer.id)
            
            # Create local record
            pm = PaymentMethod.objects.create(
                user=user,
                stripe_payment_method_id=payment_method_id,
                card_brand=payment_method.card.brand,
                card_last4=payment_method.card.last4,
                card_exp_month=payment_method.card.exp_month,
                card_exp_year=payment_method.card.exp_year,
                is_default=True
            )
            
            # Set as default for customer
            stripe.Customer.modify(
                customer.id,
                invoice_settings={'default_payment_method': payment_method_id}
            )
            
            return pm
            
        except stripe.error.StripeError as e:
            raise Exception(f"Failed to create payment method: {str(e)}")

    @staticmethod
    def get_invoice_history(subscription):
        """Get invoice history for subscription"""
        try:
            invoices = stripe.Invoice.list(
                subscription=subscription.stripe_subscription_id,
                limit=100
            )
            
            for invoice_data in invoices.data:
                Invoice.objects.get_or_create(
                    stripe_invoice_id=invoice_data.id,
                    defaults={
                        'subscription': subscription,
                        'amount': invoice_data.amount_paid / 100,  # Convert from cents
                        'currency': invoice_data.currency,
                        'status': invoice_data.status,
                        'invoice_pdf': invoice_data.invoice_pdf,
                        'hosted_invoice_url': invoice_data.hosted_invoice_url,
                    }
                )
            
            return subscription.invoices.all()
            
        except stripe.error.StripeError as e:
            raise Exception(f"Failed to get invoice history: {str(e)}") 

# Credit System Service
class CreditService:
    @staticmethod
    def get_or_create_credit_balance(user):
        """Get or create credit balance for user"""
        balance, created = UserCreditBalance.objects.get_or_create(
            user=user,
            defaults={
                'credits_remaining': 0,
                'credits_used_this_period': 0,
                'credits_reset_date': timezone.now() + timedelta(days=30),
                'is_trial_user': False,
                'trial_credits_allocated': False
            }
        )
        return balance
    
    @staticmethod
    def allocate_trial_credits(user):
        """Allocate trial credits for new users"""
        try:
            # Get or create credit balance
            credit_balance, created = UserCreditBalance.objects.get_or_create(
                user=user,
                defaults={
                    'credits_remaining': 500,  # Trial credits
                    'credits_used_this_period': 0,
                    'credits_reset_date': timezone.now() + timedelta(days=14),  # 14-day trial
                    'is_trial_user': True,
                    'trial_credits_allocated': True
                }
            )
            
            if not created:
                # Update existing credit balance for trial
                credit_balance.credits_remaining = 500
                credit_balance.credits_used_this_period = 0
                credit_balance.credits_reset_date = timezone.now() + timedelta(days=14)
                credit_balance.is_trial_user = True
                credit_balance.trial_credits_allocated = True
                credit_balance.save()
            
            logger.info(f"Allocated 500 trial credits for user {user.email}")
            return credit_balance
            
        except Exception as e:
            logger.error(f"Error allocating trial credits for user {user.email}: {e}")
            raise
    
    @staticmethod
    def check_trial_expiry(user):
        """Check if trial has expired and reset credits if needed"""
        balance = CreditService.get_or_create_credit_balance(user)
        
        if balance.is_trial_user and balance.credits_reset_date and timezone.now() > balance.credits_reset_date:
            # Trial has expired, reset credits to 0
            balance.reset_trial_credits()
            return True
        
        return False
    
    @staticmethod
    def is_trial_user(user):
        """Check if user is in trial period"""
        balance = CreditService.get_or_create_credit_balance(user)
        return balance.is_trial_user and not CreditService.check_trial_expiry(user)
    
    @staticmethod
    def get_trial_model_restrictions():
        """Get model restrictions for trial users"""
        return {
            'allowed_models': ['gpt-4o-mini'],
            'restricted_models': ['gpt-4o', 'claude-3-sonnet', 'claude-3-haiku', 'claude-3-opus', 'gemini-pro', 'gemini-pro-vision']
        }
    
    @staticmethod
    def get_ai_model(model_name):
        """Get AI model by name"""
        from .models import AIModel
        
        try:
            return AIModel.objects.get(name=model_name, is_active=True)
        except AIModel.DoesNotExist:
            return None
    
    @staticmethod
    def calculate_credits_needed(model_name, input_tokens, output_tokens):
        """Calculate credits needed for a request"""
        model = CreditService.get_ai_model(model_name)
        if not model:
            raise ValueError(f"AI model '{model_name}' not found or inactive")
        
        return model.calculate_credits(input_tokens, output_tokens)
    
    @staticmethod
    def deduct_credits(user, model_name, input_tokens, output_tokens, bot_id=None, request_id=None):
        """Deduct credits for a request"""
        from .models import CreditUsageLog
        
        # Check if user is in trial and validate model restrictions
        if CreditService.is_trial_user(user):
            trial_restrictions = CreditService.get_trial_model_restrictions()
            if model_name not in trial_restrictions['allowed_models']:
                raise ValueError(f"Model '{model_name}' is not available during trial. Only {', '.join(trial_restrictions['allowed_models'])} is allowed.")
        
        # Get or create credit balance
        balance = CreditService.get_or_create_credit_balance(user)
        
        # Get AI model
        model = CreditService.get_ai_model(model_name)
        if not model:
            raise ValueError(f"AI model '{model_name}' not found or inactive")
        
        # Calculate credits needed
        credits_needed = model.calculate_credits(input_tokens, output_tokens)
        
        # Check if user has sufficient credits
        if not balance.has_sufficient_credits(credits_needed):
            raise ValueError(f"Insufficient credits. Required: {credits_needed}, Available: {balance.credits_remaining}")
        
        # Calculate cost in USD
        from decimal import Decimal
        
        # Convert to Decimal for precise calculations
        input_tokens_decimal = Decimal(str(input_tokens))
        output_tokens_decimal = Decimal(str(output_tokens))
        
        cost_usd = (
            (input_tokens_decimal / Decimal('1000')) * model.cost_per_1k_tokens +
            (output_tokens_decimal / Decimal('1000')) * model.cost_per_1k_tokens
        )
        
        # Deduct credits
        if not balance.deduct_credits(credits_needed):
            raise ValueError("Failed to deduct credits")
        
        # Log the usage
        usage_log = CreditUsageLog.objects.create(
            user=user,
            model=model,
            bot_id=bot_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            credits_deducted=credits_needed,
            request_id=request_id
        )
        
        logger.info(f"Credits deducted for user {user.email}: {credits_needed} credits for {model_name}")
        
        return {
            'credits_deducted': credits_needed,
            'credits_remaining': balance.credits_remaining,
            'cost_usd': cost_usd,
            'usage_log_id': usage_log.id
        }
    
    @staticmethod
    def add_credits(user, credits_to_add, reason=None):
        """Add credits to user balance (admin function)"""
        balance = CreditService.get_or_create_credit_balance(user)
        
        if balance.add_credits(credits_to_add):
            logger.info(f"Credits added for user {user.email}: {credits_to_add} credits. Reason: {reason}")
            return True
        return False
    
    @staticmethod
    def get_usage_summary(user):
        """Get credit usage summary for user"""
        from .models import CreditUsageLog
        
        balance = CreditService.get_or_create_credit_balance(user)
        
        # Get usage by model
        usage_by_model = CreditUsageLog.objects.filter(user=user).values(
            'model__display_name', 'model__provider'
        ).annotate(
            total_credits=models.Sum('credits_deducted'),
            total_cost=models.Sum('cost_usd'),
            request_count=models.Count('id')
        )
        
        return {
            'credits_remaining': balance.credits_remaining,
            'credits_used_this_period': balance.credits_used_this_period,
            'credits_reset_date': balance.credits_reset_date,
            'usage_by_model': list(usage_by_model)
        }
    
    @staticmethod
    def reset_credits_for_billing_cycle(user, subscription):
        """Reset credits for new billing cycle"""
        balance = CreditService.get_or_create_credit_balance(user)
        
        # Get credits from subscription plan
        if subscription.plan:
            # Use the new credits_per_month field
            credits_allocation = subscription.plan.credits_per_month
        else:
            # Trial period
            credits_allocation = 100  # Trial credits
        
        balance.credits_remaining = credits_allocation
        balance.credits_used_this_period = 0
        balance.credits_reset_date = subscription.current_period_end
        balance.save()
        
        logger.info(f"Credits reset for user {user.email}: {credits_allocation} credits")
        return balance
    
    @staticmethod
    def is_billing_cycle_renewal(subscription, invoice_data):
        """Check if this payment is for a billing cycle renewal vs new subscription"""
        try:
            # Check if this is the first invoice for this subscription
            existing_invoices = Invoice.objects.filter(subscription=subscription).count()
            
            # If this is the first invoice, it's a new subscription, not a renewal
            if existing_invoices == 0:
                return False
            
            # Check if the invoice period matches the subscription's current period
            invoice_period_start = datetime.fromtimestamp(invoice_data.get('period_start', 0), tz=dt_timezone.utc)
            invoice_period_end = datetime.fromtimestamp(invoice_data.get('period_end', 0), tz=dt_timezone.utc)
            
            # If invoice period matches subscription period, it's a renewal
            if (invoice_period_start == subscription.current_period_start and 
                invoice_period_end == subscription.current_period_end):
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking billing cycle renewal: {e}")
            return False
    
    @staticmethod
    def allocate_credits_for_new_subscription(user, subscription):
        """Allocate credits for a new subscription"""
        try:
            # Get or create credit balance
            credit_balance, created = UserCreditBalance.objects.get_or_create(
                user=user,
                defaults={
                    'credits_remaining': 0,
                    'credits_used_this_period': 0,
                    'credits_reset_date': subscription.current_period_end,
                    'is_trial_user': False,
                    'trial_credits_allocated': False
                }
            )
            
            # For trial-to-paid conversion, give fresh credits
            if subscription.plan:
                credits_to_allocate = subscription.plan.credits_per_month
                credit_balance.credits_remaining = credits_to_allocate
                credit_balance.credits_used_this_period = 0
                credit_balance.credits_reset_date = subscription.current_period_end
                credit_balance.is_trial_user = False
                credit_balance.trial_credits_allocated = False
                credit_balance.save()
                
                logger.info(f"Allocated {credits_to_allocate} credits for user {user.email} on plan {subscription.plan.name}")
            else:
                logger.warning(f"No plan found for subscription {subscription.id}")
                
        except Exception as e:
            logger.error(f"Error allocating credits for user {user.email}: {e}")
            raise
    
    @staticmethod
    def prorate_credits_for_upgrade(user, subscription, new_plan):
        """Prorate credits when upgrading/downgrading subscription"""
        try:
            # For trial users, give fresh start (no proration)
            if subscription.is_trial_user:
                credits_to_allocate = new_plan.credits_per_month
                balance = CreditService.get_or_create_credit_balance(user)
                balance.credits_remaining = credits_to_allocate
                balance.credits_used_this_period = 0
                balance.credits_reset_date = subscription.current_period_end
                balance.is_trial_user = False
                balance.trial_credits_allocated = False
                balance.save()
                
                logger.info(f"Fresh credit allocation for trial user {user.email} upgrading to {new_plan.name}: {credits_to_allocate} credits")
                return balance
            
            # For existing paid subscriptions, calculate proration
            old_plan = subscription.plan
            if not old_plan:
                logger.warning(f"No old plan found for subscription {subscription.id}")
                return None
            
            # Calculate remaining days in current period
            now = timezone.now()
            days_remaining = (subscription.current_period_end - now).days
            total_days = (subscription.current_period_end - subscription.current_period_start).days
            
            if days_remaining <= 0:
                # Period has ended, give full new allocation
                credits_to_allocate = new_plan.credits_per_month
            else:
                # Prorate based on remaining days
                old_credits_remaining = CreditService.get_or_create_credit_balance(user).credits_remaining
                prorated_old_credits = (old_credits_remaining * days_remaining) / total_days
                new_credits_full = new_plan.credits_per_month
                prorated_new_credits = (new_credits_full * days_remaining) / total_days
                credits_to_allocate = int(prorated_old_credits + prorated_new_credits)
            
            # Update credit balance
            balance = CreditService.get_or_create_credit_balance(user)
            balance.credits_remaining = credits_to_allocate
            balance.credits_reset_date = subscription.current_period_end
            balance.save()
            
            logger.info(f"Prorated credits for user {user.email} upgrading from {old_plan.name} to {new_plan.name}: {credits_to_allocate} credits")
            return balance
            
        except Exception as e:
            logger.error(f"Error prorating credits for user {user.email}: {e}")
            raise 

    @staticmethod
    def allocate_credits_for_plan_change(user, new_plan, old_plan=None):
        """Allocate full credits for plan change (no time-based proration)"""
        try:
            # Get or create credit balance
            balance = CreditService.get_or_create_credit_balance(user)
            
            # Determine if this is an upgrade or downgrade
            is_downgrade = False
            if old_plan:
                is_downgrade = new_plan.price < old_plan.price
            
            if is_downgrade:
                # For downgrades, don't change credits immediately
                # Credits will be adjusted at the next billing cycle
                logger.info(f"Downgrade detected for user {user.email} from {old_plan.name} to {new_plan.name}. Credits will be adjusted at next billing cycle.")
                return balance
            else:
                # For upgrades, allocate full credits immediately
                credits_to_allocate = new_plan.credits_per_month
                balance.credits_remaining = credits_to_allocate
                balance.credits_used_this_period = 0
                balance.credits_reset_date = timezone.now() + timedelta(days=30)  # Set to next billing cycle
                balance.is_trial_user = False
                balance.trial_credits_allocated = False
                balance.save()
                
                logger.info(f"Allocated {credits_to_allocate} credits for user {user.email} upgrading to {new_plan.name}")
                return balance
            
        except Exception as e:
            logger.error(f"Error allocating credits for plan change for user {user.email}: {e}")
            raise 