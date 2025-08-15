from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.http import HttpResponse
from django.utils import timezone
from django.contrib.auth import get_user_model
import stripe
import json
from datetime import datetime, timedelta, timezone as dt_timezone
import logging
import traceback

from .models import Subscription, SubscriptionPlan, PaymentMethod, Invoice, WebhookEvent, AIModel, UserCreditBalance, CreditUsageLog
from .serializers import (
    SubscriptionSerializer, SubscriptionPlanSerializer, PaymentMethodSerializer,
    CreateSubscriptionSerializer, CancelSubscriptionSerializer, UpdatePaymentMethodSerializer,
    AIModelSerializer, UserCreditBalanceSerializer, CreditUsageLogSerializer,
    CreditUsageRequestSerializer, AdminCreditAdjustmentSerializer, InvoiceSerializer
)
from .services import StripeService, CreditService
from django.conf import settings
from bots.services import NotificationService
from email_templates.email_service import EmailService

logger = logging.getLogger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY

# Get the User model
User = get_user_model()

def is_event_processed(event_id):
    """Check if a webhook event has already been processed"""
    return WebhookEvent.objects.filter(stripe_event_id=event_id).exists()

def mark_event_processed(event_id, event_type, event_data=None):
    """Mark a webhook event as processed"""
    try:
        WebhookEvent.objects.create(
            stripe_event_id=event_id,
            event_type=event_type,
            data=event_data or {}
        )
        return True
    except Exception as e:
        print(f"Error marking event as processed: {str(e)}")
        return False

class SubscriptionPlanListView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        plans = SubscriptionPlan.objects.filter(is_active=True)
        serializer = SubscriptionPlanSerializer(plans, many=True)
        return Response(serializer.data)

class CurrentSubscriptionView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        # Get the most recent active subscription for the user
        subscription = Subscription.objects.filter(
            user=request.user,
            status__in=['trialing', 'active']
        ).order_by('-created_at').first()
        
        if subscription:
            # If this is a paid subscription, ensure it has the correct billing period
            if subscription.plan and not subscription.is_trialing:
                # Sync with Stripe to ensure we have the latest data
                try:
                    if subscription.stripe_subscription_id and not subscription.stripe_subscription_id.startswith('trial_'):
                        StripeService.sync_subscription_from_stripe(subscription.stripe_subscription_id)
                        subscription.refresh_from_db()
                        logger.info(f"  - Synced from Stripe, new current_period_end: {subscription.current_period_end}")
                except Exception as e:
                    logger.error(f"Error syncing subscription from Stripe: {e}")
            
            serializer = SubscriptionSerializer(subscription)
            return Response(serializer.data)
        return Response({'message': 'No active subscription'}, status=404)

class CreateSubscriptionView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        serializer = CreateSubscriptionSerializer(data=request.data)
        if serializer.is_valid():
            try:
                plan = get_object_or_404(SubscriptionPlan, id=serializer.validated_data['plan_id'])
                
                # Check if user already has an active subscription
                existing_subscription = Subscription.objects.filter(
                    user=request.user,
                    status__in=['trialing', 'active']
                ).first()
                
                # Allow trial users to create new subscriptions
                if existing_subscription and not (existing_subscription.stripe_subscription_id and existing_subscription.stripe_subscription_id.startswith('trial_')):
                    return Response(
                        {'error': 'You already have an active subscription'},
                        status=400
                    )
                
                # Check if this is a trial user
                is_trial_user = existing_subscription and existing_subscription.stripe_subscription_id and existing_subscription.stripe_subscription_id.startswith('trial_')
                
                # For new subscriptions without payment method, create checkout session
                if not serializer.validated_data.get('payment_method_id'):
                    try:
                        # For trial users, create a new Stripe customer instead of using the fake one
                        if is_trial_user:
                            # Create a new Stripe customer for trial users
                            customer = StripeService.create_customer(request.user)
                        else:
                            # Use existing customer for non-trial users
                            customer = StripeService.get_or_create_customer(request.user)
                        
                        # Set billing period based on plan (30 days for paid plans, 14 for trial)
                        billing_period = 30 if not is_trial_user else 14
                        
                        checkout_session = stripe.checkout.Session.create(
                            customer=customer.id,
                            payment_method_types=['card'],
                            line_items=[{
                                'price': plan.stripe_price_id,
                                'quantity': 1,
                            }],
                            mode='subscription',
                            success_url=f"{settings.FRONTEND_URL}/subscription/success",
                            cancel_url=f"{settings.FRONTEND_URL}/subscription/error?error=canceled",
                            metadata={
                                'user_id': request.user.id,
                                'plan_id': plan.id,
                                'is_trial_upgrade': 'true' if is_trial_user else 'false'
                            }
                        )
                        
                        return Response({
                            'checkout_url': checkout_session.url,
                            'session_id': checkout_session.id
                        })
                    except Exception as e:
                        logger.error(f"Error creating checkout session: {e}")
                        return Response(
                            {'error': 'Failed to create checkout session'},
                            status=500
                        )
                
                # For subscriptions with payment method
                payment_method_id = serializer.validated_data['payment_method_id']
                
                try:
                    # For trial users, create a new Stripe customer instead of using the fake one
                    if is_trial_user:
                        # Create a new Stripe customer for trial users
                        customer = StripeService.create_customer(request.user)
                    else:
                        # Use existing customer for non-trial users
                        customer = StripeService.get_or_create_customer(request.user)
                    
                    # Attach payment method to customer
                    stripe.PaymentMethod.attach(
                        payment_method_id,
                        customer=customer.id
                    )
                    
                    # Set as default payment method
                    stripe.Customer.modify(
                        customer.id,
                        invoice_settings={
                            'default_payment_method': payment_method_id
                        }
                    )
                    
                    # Create subscription
                    subscription = StripeService.create_subscription(
                        request.user,
                        plan,
                        payment_method_id,
                        serializer.validated_data.get('trial_from_plan', True)
                    )
                    
                    # Allocate credits for new subscription
                    CreditService.allocate_credits_for_new_subscription(request.user, subscription)
                    
                    serializer = SubscriptionSerializer(subscription)
                    return Response(serializer.data, status=201)
                    
                except Exception as e:
                    logger.error(f"Error creating subscription: {e}")
                    return Response(
                        {'error': 'Failed to create subscription'},
                        status=500
                    )
            except Exception as e:
                logger.error(f"Error in subscription creation: {e}")
                return Response(
                    {'error': 'Failed to create subscription'},
                    status=500
                )
        return Response(serializer.errors, status=400)

class CancelSubscriptionView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        serializer = CancelSubscriptionSerializer(data=request.data)
        if serializer.is_valid():
            try:
                subscription = Subscription.objects.get(user=request.user, status__in=['trialing', 'active'])
                
                # Cancel subscription in Stripe
                StripeService.cancel_subscription(
                    subscription,
                    cancel_at_period_end=serializer.validated_data['cancel_at_period_end']
                )
                
                # Update local subscription status
                if serializer.validated_data['cancel_at_period_end']:
                    subscription.status = 'canceled'
                else:
                    subscription.status = 'canceled'
                    subscription.canceled_at = timezone.now()
                
                subscription.save()
                
                return Response({'message': 'Subscription canceled successfully'})
            except Subscription.DoesNotExist:
                return Response({'error': 'No active subscription found'}, status=404)
            except Exception as e:
                logger.error(f"Error canceling subscription: {e}")
                return Response({'error': 'Failed to cancel subscription'}, status=500)
        return Response(serializer.errors, status=400)

class PaymentMethodListView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        payment_methods = PaymentMethod.objects.filter(user=request.user)
        serializer = PaymentMethodSerializer(payment_methods, many=True)
        return Response(serializer.data)

class CreatePaymentMethodView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            payment_method_id = request.data.get('payment_method_id')
            if not payment_method_id:
                return Response({'error': 'Payment method ID is required'}, status=400)
        
            try:
                customer = StripeService.get_or_create_customer(request.user)
            except Exception as e:
                logger.error(f"Error getting or creating customer: {e}")
                return Response({'error': 'Failed to get or create customer'}, status=500)
            
            # Attach payment method to customer
            stripe.PaymentMethod.attach(
                payment_method_id,
                customer=customer.id
            )
            
            # Set as default if no default exists
            existing_default = PaymentMethod.objects.filter(user=request.user, is_default=True).first()
            is_default = not existing_default
            
            if is_default:
                stripe.Customer.modify(
                    customer.id,
                    invoice_settings={'default_payment_method': payment_method_id}
                )
            
            # Save payment method
            payment_method_data = stripe.PaymentMethod.retrieve(payment_method_id)
            payment_method = PaymentMethod.objects.create(
                user=request.user,
                stripe_payment_method_id=payment_method_id,
                card_brand=payment_method_data.card.brand,
                card_last4=payment_method_data.card.last4,
                card_exp_month=payment_method_data.card.exp_month,
                card_exp_year=payment_method_data.card.exp_year,
                is_default=is_default
            )
            
            serializer = PaymentMethodSerializer(payment_method)
            return Response(serializer.data, status=201)
        except Exception as e:
            logger.error(f"Error creating payment method: {e}")
            return Response({'error': 'Failed to create payment method'}, status=500)

class UpdatePaymentMethodView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        serializer = UpdatePaymentMethodSerializer(data=request.data)
        if serializer.is_valid():
            try:
                payment_method_id = serializer.validated_data['payment_method_id']
                
                # Update default payment method in Stripe
                customer = StripeService.get_or_create_customer(request.user)
                stripe.Customer.modify(
                    customer.id,
                    invoice_settings={'default_payment_method': payment_method_id}
                )
                
                # Update local payment methods
                PaymentMethod.objects.filter(user=request.user).update(is_default=False)
                PaymentMethod.objects.filter(
                    user=request.user,
                    stripe_payment_method_id=payment_method_id
                ).update(is_default=True)
                
                return Response({'message': 'Default payment method updated'})
            except Exception as e:
                logger.error(f"Error updating payment method: {e}")
                return Response({'error': 'Failed to update payment method'}, status=500)
        return Response(serializer.errors, status=400)

class InvoiceHistoryView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            subscription = Subscription.objects.filter(user=request.user).first()
            if not subscription:
                return Response({'invoices': []})
        
            invoices = Invoice.objects.filter(subscription=subscription).order_by('-created_at')
            serializer = InvoiceSerializer(invoices, many=True)
            return Response({'invoices': serializer.data})
        except Exception as e:
            logger.error(f"Error fetching invoice history: {e}")
            return Response({'error': 'Failed to fetch invoice history'}, status=500)

class UpgradeSubscriptionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            new_plan_id = request.data.get('plan_id')
            payment_method_id = request.data.get('payment_method_id')
            if not new_plan_id:
                return Response({'error': 'Plan ID is required'}, status=400)
            
            new_plan = get_object_or_404(SubscriptionPlan, id=new_plan_id)
            
            # Get current subscription to determine if it's an upgrade or downgrade
            current_subscription = Subscription.objects.filter(
                user=request.user,
                status__in=['trialing', 'active']
            ).order_by('-created_at').first()

            if not current_subscription:
                return Response({'error': 'No active subscription found to upgrade'}, status=404)
            
            old_plan = current_subscription.plan
            
            # Use the StripeService to handle the upgrade/downgrade
            subscription = StripeService.upgrade_subscription(request.user, new_plan=new_plan, payment_method_id=payment_method_id)
            
            # Handle credit allocation based on upgrade/downgrade
            CreditService.allocate_credits_for_plan_change(request.user, new_plan, old_plan)
            
            serializer = SubscriptionSerializer(subscription)
            return Response(serializer.data)
                
        except Exception as e:
            logger.error(f"Error upgrading subscription: {e}")
            return Response({'error': 'Failed to upgrade subscription'}, status=500)

@method_decorator(csrf_exempt, name='dispatch')
class StripeWebhookView(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
        
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        except ValueError as e:
            return HttpResponse(status=400)
        except stripe.error.SignatureVerificationError as e:
            return HttpResponse(status=400)
        
        # Check if event has already been processed
        if is_event_processed(event['id']):
            return HttpResponse(status=200)
        
        event_type = event['type']
        event_data = event['data']['object']
        
        try:
            if event_type == 'customer.subscription.created':
                self.handle_subscription_created(event_data)
            elif event_type == 'customer.subscription.updated':
                self.handle_subscription_updated(event_data)
            elif event_type == 'customer.subscription.deleted':
                self.handle_subscription_deleted(event_data)
            elif event_type == 'invoice.payment_succeeded':
                self.handle_payment_succeeded(event_data)
            elif event_type == 'invoice.payment_failed':
                self.handle_payment_failed(event_data)
            elif event_type == 'checkout.session.completed':
                self.handle_checkout_completed(event_data)
            elif event_type == 'invoice.created':
                self.handle_invoice_created(event_data)
            elif event_type == 'payment_method.attached':
                self.handle_payment_method_attached(event_data)
            
            # Mark event as processed
            mark_event_processed(event['id'], event_type, event_data)
            
        except Exception as e:
            logger.error(f"Error processing webhook {event_type}: {e}")
            return HttpResponse(status=500)
        
        return HttpResponse(status=200)
    
    def handle_subscription_created(self, subscription_data):
        """Handle subscription.created webhook"""
        try:
            # Check if subscription already exists
            existing_subscription = Subscription.objects.filter(stripe_subscription_id=subscription_data['id']).first()
            if existing_subscription:
                logger.info(f"Subscription {subscription_data['id']} already exists")
                return
            
            user_id = subscription_data.get('metadata', {}).get('user_id')
            if not user_id:
                logger.error("No user_id in subscription metadata")
                return
            
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                logger.error(f"User {user_id} not found")
                return
            
            # Get plan from metadata or find by price ID
            plan_id = subscription_data.get('metadata', {}).get('plan_id')
            plan = None
            if plan_id:
                try:
                    plan = SubscriptionPlan.objects.get(id=plan_id)
                except SubscriptionPlan.DoesNotExist:
                    logger.error(f"Plan {plan_id} not found")
            
            if not plan:
                # Try to find plan by price ID
                price_id = subscription_data['items']['data'][0]['price']['id']
                try:
                    plan = SubscriptionPlan.objects.get(stripe_price_id=price_id)
                except SubscriptionPlan.DoesNotExist:
                    logger.error(f"Plan with price ID {price_id} not found")
            
            # Create subscription record
            # Check if this is a trial user (has subscription ID that starts with 'trial_')
            subscription_exists = Subscription.objects.filter(stripe_subscription_id=subscription_data['id']).exists()
            if subscription_exists:
                if subscription_data['id'].startswith('trial_'):
                    # Delete any other trial subscriptions for this user
                    Subscription.objects.filter(user=user, stripe_subscription_id__startswith='trial_').delete()
            else:
                subscription, created = Subscription.objects.update_or_create(
                    user=user,
                defaults={
                    'plan': plan,
                        'stripe_subscription_id': subscription_data['id'],
                        'stripe_customer_id': subscription_data['customer'],
                    'status': subscription_data['status'],
                        'current_period_start': datetime.fromtimestamp(subscription_data['current_period_start'], tz=dt_timezone.utc),
                        'current_period_end': datetime.fromtimestamp(subscription_data['current_period_end'], tz=dt_timezone.utc),
                        'trial_start': datetime.fromtimestamp(subscription_data['trial_start'], tz=dt_timezone.utc) if subscription_data.get('trial_start') else None,
                        'trial_end': datetime.fromtimestamp(subscription_data['trial_end'], tz=dt_timezone.utc) if subscription_data.get('trial_end') else None
                        }
                )
                
            # Allocate credits for new subscription
            CreditService.allocate_credits_for_new_subscription(user, subscription)
            
            logger.info(f"Subscription created for user {user.email}")
            
        except Exception as e:
            logger.error(f"Error handling subscription.created: {e}")
    
    def handle_subscription_updated(self, subscription_data):
        """Handle subscription.updated webhook"""
        try:
            subscription = Subscription.objects.get(stripe_subscription_id=subscription_data['id'])
            old_status = subscription.status
            subscription.status = subscription_data['status']
            subscription.current_period_start = datetime.fromtimestamp(subscription_data['current_period_start'], tz=dt_timezone.utc)
            subscription.current_period_end = datetime.fromtimestamp(subscription_data['current_period_end'], tz=dt_timezone.utc)
            subscription.save()
            
            # Only reset credits if this is a new billing cycle AND payment succeeded
            # Don't reset credits just because status changed to active
            # Credits should only reset when payment succeeds for the new billing cycle
            if old_status != 'active' and subscription.status == 'active':
                # This might be a new subscription, not a billing cycle renewal
                # We'll handle credit reset in payment_succeeded webhook instead
                pass
            
            logger.info(f"Subscription updated for user {subscription.user.email}")
        except Subscription.DoesNotExist:
            logger.error(f"Subscription {subscription_data['id']} not found")
        except Exception as e:
            logger.error(f"Error handling subscription.updated: {e}")
    
    def handle_subscription_deleted(self, subscription_data):
        """Handle subscription.deleted webhook"""
        try:
            subscription = Subscription.objects.get(stripe_subscription_id=subscription_data['id'])
            subscription.status = 'canceled'
            subscription.canceled_at = timezone.now()
            subscription.save()
            
            logger.info(f"Subscription canceled for user {subscription.user.email}")
        except Subscription.DoesNotExist:
            logger.error(f"Subscription {subscription_data['id']} not found")
        except Exception as e:
            logger.error(f"Error handling subscription.deleted: {e}")
    
    def handle_payment_succeeded(self, invoice_data):
        """Handle invoice.payment_succeeded webhook"""
        try:
            subscription_id = invoice_data.get('subscription')
            if not subscription_id:
                logger.info("No subscription found for invoice")
                return
            
            # Get subscription from database or create from Stripe
            try:
                subscription = Subscription.objects.get(stripe_subscription_id=subscription_id)
                logger.info(f"Found subscription: {subscription.id} for user: {subscription.user.email}")
            except Subscription.DoesNotExist:
                logger.info(f"No subscription found for ID: {subscription_id}")
                try:
                    stripe_subscription = stripe.Subscription.retrieve(subscription_id)
                    customer_id = stripe_subscription.customer

                    try:
                        customer = stripe.Customer.retrieve(customer_id)
                        User = get_user_model()
                        user = User.objects.get(email=customer.email)
                    except Exception as e:
                        logger.error(f"Error finding user for customer {customer_id}: {e}")
                        return
                    
                    # Get plan from price ID
                    plan = None
                    if stripe_subscription.get('items') and stripe_subscription['items'].get('data'):
                        price_id = stripe_subscription['items']['data'][0]['price']['id']
                        try:
                            plan = SubscriptionPlan.objects.get(stripe_price_id=price_id)
                        except SubscriptionPlan.DoesNotExist:
                            print(f"Plan with price {price_id} not found")
                            return
                    
                    # Create subscription from Stripe data
                    subscription, created = Subscription.objects.get_or_create(
                        stripe_subscription_id=stripe_subscription.id,
                        defaults={
                            'user': user,
                            'plan': plan,
                            'stripe_customer_id': customer_id,
                            'status': stripe_subscription.status,
                            'current_period_start': datetime.fromtimestamp(stripe_subscription.get('current_period_start'), tz=dt_timezone.utc) if stripe_subscription.get('current_period_start') else timezone.now(),
                            'current_period_end': datetime.fromtimestamp(stripe_subscription.get('current_period_end'), tz=dt_timezone.utc) if stripe_subscription.get('current_period_end') else timezone.now() + timedelta(days=30),
                            'trial_start': datetime.fromtimestamp(stripe_subscription.get('trial_start'), tz=dt_timezone.utc) if stripe_subscription.get('trial_start') else None,
                            'trial_end': datetime.fromtimestamp(stripe_subscription.get('trial_end'), tz=dt_timezone.utc) if stripe_subscription.get('trial_end') else None,
                        }
                    )
                    if created:
                        logger.info(f"Created subscription {subscription.id} from Stripe data for invoice")
                    else:
                        logger.info(f"Subscription {subscription.id} already exists from Stripe data")
                except Exception as e:
                    logger.error(f"Error getting subscription from Stripe: {str(e)}")
                    return
            
            # Create or update invoice
            invoice, created = Invoice.objects.get_or_create(
                stripe_invoice_id=invoice_data['id'],
                defaults={
                    'subscription': subscription,
                    'amount': (invoice_data.get('amount_paid') or invoice_data.get('amount_due') or 0) / 100,
                    'currency': invoice_data.get('currency', 'usd'),
                    'status': invoice_data.get('status', 'paid'),
                    'invoice_pdf': invoice_data.get('invoice_pdf', ''),
                    'hosted_invoice_url': invoice_data.get('hosted_invoice_url', ''),
                }
            )
            if created:
                logger.info(f"Created new invoice {invoice.id} for subscription {subscription.id}")
            else:
                # Update existing invoice
                invoice.status = invoice_data.get('status', 'paid')
                invoice.amount = (invoice_data.get('amount_paid') or invoice_data.get('amount_due') or 0) / 100
                invoice.save()
                logger.info(f"Updated existing invoice {invoice.id}")
            
            # Sync subscription status
            StripeService.sync_subscription_from_stripe(subscription_id)
            
            # Send payment success email
            try:
                email_service = EmailService()
                if email_service:
                    success = email_service.send_payment_success_email(
                        subscription,
                        invoice.amount,
                        invoice.stripe_invoice_id,
                        invoice.hosted_invoice_url
                    )
                    if success:
                        logger.info(f"Payment success email sent to {subscription.user.email}")
                    else:
                        logger.error(f"Failed to send payment success email to {subscription.user.email}")
                else:
                    logger.error("Email service not available")
            except Exception as e:
                logger.error(f"Exception sending payment success email to {subscription.user.email}: {str(e)}")
            
            # Only reset credits if this is a billing cycle renewal, not a new subscription
            if CreditService.is_billing_cycle_renewal(subscription, invoice_data):
                CreditService.reset_credits_for_billing_cycle(subscription.user, subscription)
                logger.info(f"Credits reset for billing cycle renewal - user {subscription.user.email}")
            else:
                logger.info(f"Payment succeeded for new subscription - user {subscription.user.email}")
            
            logger.info(f"Payment succeeded for user {subscription.user.email}")
            
        except Subscription.DoesNotExist:
            logger.error(f"Subscription {invoice_data['subscription']} not found - this may be normal for new subscriptions")
        except Exception as e:
            logger.error(f"Error handling payment.succeeded: {e}")
    
    def handle_payment_failed(self, invoice_data):
        """Handle invoice.payment_failed webhook"""
        try:
            subscription = Subscription.objects.get(stripe_subscription_id=invoice_data['subscription'])
            
            # Send payment failed email
            email_service = EmailService()
            if email_service:
                try:
                    success = email_service.send_payment_failed_email(subscription)
                    if success:
                        logger.info(f"Payment failed email sent to {subscription.user.email}")
                    else:
                        logger.error(f"Failed to send payment failed email to {subscription.user.email}")
                except Exception as e:
                    logger.error(f"Exception sending payment failed email to {subscription.user.email}: {str(e)}")
            
            logger.info(f"Payment failed for user {subscription.user.email}")
            
        except Subscription.DoesNotExist:
            logger.error(f"Subscription {invoice_data['subscription']} not found")
        except Exception as e:
            logger.error(f"Error handling payment.failed: {e}")
    
    def handle_checkout_completed(self, session_data):
        """Handle checkout.session.completed webhook"""
        try:
            user_id = session_data.get('metadata', {}).get('user_id')
            plan_id = session_data.get('metadata', {}).get('plan_id')
            is_trial_upgrade = session_data.get('metadata', {}).get('is_trial_upgrade') == 'true'
            
            if not user_id or not plan_id:
                logger.error("Missing user_id or plan_id in checkout session metadata")
                return
            
            try:
                user = User.objects.get(id=user_id)
                plan = SubscriptionPlan.objects.get(id=plan_id)
            except (User.DoesNotExist, SubscriptionPlan.DoesNotExist) as e:
                logger.error(f"User or plan not found: {e}")
                return
            
            # Get the subscription from Stripe
            subscription_id = session_data.get('subscription')
            if subscription_id:
                try:
                    stripe_subscription = stripe.Subscription.retrieve(subscription_id)

                    # Use get_or_create to prevent duplicates
                    subscription, created = Subscription.objects.get_or_create(
                    user=user,
                        defaults={
                            'stripe_subscription_id': stripe_subscription.id,
                            'plan': plan,
                            'stripe_customer_id': stripe_subscription.customer,
                            'status': stripe_subscription.status,
                            'current_period_start': datetime.fromtimestamp(stripe_subscription.get('current_period_start'), tz=dt_timezone.utc) if stripe_subscription.get('current_period_start') else timezone.now(),
                            'current_period_end': datetime.fromtimestamp(stripe_subscription.get('current_period_end'), tz=dt_timezone.utc) if stripe_subscription.get('current_period_end') else timezone.now() + timedelta(days=30),
                            'trial_start': datetime.fromtimestamp(stripe_subscription.get('trial_start'), tz=dt_timezone.utc) if stripe_subscription.get('trial_start') else None,
                            'trial_end': datetime.fromtimestamp(stripe_subscription.get('trial_end'), tz=dt_timezone.utc) if stripe_subscription.get('trial_end') else None,
                        }
                    )

                    if not created:
                        # Update existing fields in case they're out of sync
                        subscription.stripe_subscription_id = stripe_subscription.id
                        subscription.plan = plan
                        subscription.stripe_customer_id = stripe_subscription.customer
                        subscription.status = stripe_subscription.status
                        subscription.current_period_start = datetime.fromtimestamp(stripe_subscription.get('current_period_start'), tz=dt_timezone.utc) if stripe_subscription.get('current_period_start') else timezone.now()
                        subscription.current_period_end = datetime.fromtimestamp(stripe_subscription.get('current_period_end'), tz=dt_timezone.utc) if stripe_subscription.get('current_period_end') else timezone.now() + timedelta(days=30)
                        subscription.trial_start = datetime.fromtimestamp(stripe_subscription.get('trial_start'), tz=dt_timezone.utc) if stripe_subscription.get('trial_start') else None
                        subscription.trial_end = datetime.fromtimestamp(stripe_subscription.get('trial_end'), tz=dt_timezone.utc) if stripe_subscription.get('trial_end') else None
                        subscription.save()
                        logger.info(f"Updated subscription {subscription.id} for user {user.email}")
                    else:
                        logger.info(f"Created new subscription {subscription.id} for user {user.email}")


                except stripe.error.InvalidRequestError as e:
                    logger.error(f"Subscription {subscription_id} not found in Stripe: {str(e)}")
                    return
                except Exception as e:
                    logger.error(f"Error retrieving subscription from Stripe: {str(e)}")
                    traceback.print_exc()
                    return
                
                # Allocate credits for the subscription
                CreditService.allocate_credits_for_new_subscription(user, subscription)
                
                logger.info(f"Updated existing subscription for user {user.email}")
                return
                
        except Exception as e:
            logger.error(f"Error handling checkout.session.completed: {e}")
            traceback.print_exc()
            return

    def handle_invoice_created(self, invoice_data):
        """Handle invoice.created webhook"""
        try:
            subscription = Subscription.objects.get(stripe_subscription_id=invoice_data['subscription'])
            
            # Create invoice record
            invoice = Invoice.objects.create(
                subscription=subscription,
                stripe_invoice_id=invoice_data['id'],
                amount=invoice_data['amount_due'] / 100,  # Convert from cents
                currency=invoice_data['currency'],
                status=invoice_data['status'],
                invoice_pdf=invoice_data.get('invoice_pdf'),
                hosted_invoice_url=invoice_data.get('hosted_invoice_url')
            )
            
            logger.info(f"Invoice created for user {subscription.user.email}")
            
        except Subscription.DoesNotExist:
            logger.error(f"Subscription {invoice_data['subscription']} not found")
        except Exception as e:
            logger.error(f"Error handling invoice.created: {e}")

    def handle_payment_method_attached(self, payment_method_data):
        """Handle payment_method.attached webhook"""
        try:
            customer_id = payment_method_data['customer']
            payment_method_id = payment_method_data['id']
            
            # Find user by customer ID through subscription
            user = None
            try:
                subscription = Subscription.objects.get(stripe_customer_id=customer_id)
                user = subscription.user
            except Subscription.DoesNotExist:
                # If subscription doesn't exist yet, try to find user by email from Stripe customer
                try:
                    customer = stripe.Customer.retrieve(customer_id)
                    if customer.email:
                        user = User.objects.get(email=customer.email)
                        logger.info(f"Found user {user.email} by email for customer {customer_id}")
                    else:
                        logger.error(f"No email found for customer {customer_id}")
                        return
                except (User.DoesNotExist, stripe.error.StripeError) as e:
                    logger.error(f"Could not find user for customer {customer_id}: {e}")
                    return
            
            # Save payment method
            payment_method = PaymentMethod.objects.create(
                user=user,
                stripe_payment_method_id=payment_method_id,
                card_brand=payment_method_data['card']['brand'],
                card_last4=payment_method_data['card']['last4'],
                card_exp_month=payment_method_data['card']['exp_month'],
                card_exp_year=payment_method_data['card']['exp_year'],
                is_default=True
            )
            
            logger.info(f"Payment method attached for user {user.email}")
            
        except Exception as e:
            logger.error(f"Error handling payment_method.attached: {e}")

class BillingPortalView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            customer = StripeService.get_or_create_customer(request.user)
            
            session = stripe.billing_portal.Session.create(
                customer=customer.id,
                return_url=f"{settings.FRONTEND_URL}/billing"
            )
            
            return Response({'url': session.url})
        except Exception as e:
            logger.error(f"Error creating billing portal session: {e}")
            return Response({'error': 'Failed to create billing portal session'}, status=500)

# Credit System Views
class CreditBalanceView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get user's credit balance and usage summary"""
        try:
            summary = CreditService.get_usage_summary(request.user)
            
            # Add trial information
            is_trial = CreditService.is_trial_user(request.user)
            trial_restrictions = CreditService.get_trial_model_restrictions() if is_trial else None
            
            summary.update({
                'is_trial_user': is_trial,
                'trial_restrictions': trial_restrictions
            })
            
            return Response(summary)
        except Exception as e:
            logger.error(f"Error getting credit balance: {e}")
            return Response({'error': 'Failed to get credit balance'}, status=500)

class CreditUsageView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """Deduct credits for AI model usage"""
        serializer = CreditUsageRequestSerializer(data=request.data)
        if serializer.is_valid():
            try:
                result = CreditService.deduct_credits(
                    user=request.user,
                    model_name=serializer.validated_data['model_name'],
                    input_tokens=serializer.validated_data['input_tokens'],
                    output_tokens=serializer.validated_data['output_tokens'],
                    bot_id=serializer.validated_data.get('bot_id'),
                    request_id=serializer.validated_data.get('request_id')
                )
                return Response(result)
            except ValueError as e:
                return Response({'error': str(e)}, status=400)
            except Exception as e:
                logger.error(f"Error deducting credits: {e}")
                return Response({'error': 'Failed to deduct credits'}, status=500)
        return Response(serializer.errors, status=400)

class CreditUsageLogView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get user's credit usage logs"""
        try:
            logs = CreditUsageLog.objects.filter(user=request.user).order_by('-created_at')
            serializer = CreditUsageLogSerializer(logs, many=True)
            return Response(serializer.data)
        except Exception as e:
            logger.error(f"Error getting credit usage logs: {e}")
            return Response({'error': 'Failed to get usage logs'}, status=500)

class AdminCreditAdjustmentView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """Admin function to adjust user credits"""
        # Check if user is admin
        if not request.user.is_staff:
            return Response({'error': 'Admin access required'}, status=403)
        
        serializer = AdminCreditAdjustmentSerializer(data=request.data)
        if serializer.is_valid():
            try:
                user = User.objects.get(id=serializer.validated_data['user_id'])
                credits_to_add = serializer.validated_data['credits_to_add']
                reason = serializer.validated_data.get('reason', 'Admin adjustment')
                
                success = CreditService.add_credits(user, credits_to_add, reason)
                
                if success:
                    return Response({
                        'message': f'Added {credits_to_add} credits to {user.email}',
                        'new_balance': user.credit_balance.credits_remaining
                    })
                else:
                    return Response({'error': 'Failed to add credits'}, status=500)
            except User.DoesNotExist:
                return Response({'error': 'User not found'}, status=404)
            except Exception as e:
                logger.error(f"Error adjusting credits: {e}")
                return Response({'error': 'Failed to adjust credits'}, status=500)
        return Response(serializer.errors, status=400)

class AdminCreditUsageView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Admin function to view all credit usage"""
        # Check if user is admin
        if not request.user.is_staff:
            return Response({'error': 'Admin access required'}, status=403)
        
        try:
            user_id = request.query_params.get('user_id')
            if user_id:
                logs = CreditUsageLog.objects.filter(user_id=user_id).order_by('-created_at')
            else:
                logs = CreditUsageLog.objects.all().order_by('-created_at')
            
            serializer = CreditUsageLogSerializer(logs, many=True)
            return Response(serializer.data)
        except Exception as e:
            logger.error(f"Error getting admin credit usage: {e}")
            return Response({'error': 'Failed to get usage data'}, status=500)