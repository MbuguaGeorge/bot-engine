import stripe
from django.utils import timezone
from datetime import datetime, timedelta, timezone as dt_timezone
from .models import Subscription, SubscriptionPlan, PaymentMethod, Invoice
from django.conf import settings

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