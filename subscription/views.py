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
        subscription = Subscription.objects.filter(user=request.user).first()
        if subscription:
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
                
                if existing_subscription:
                    return Response(
                        {'error': 'You already have an active subscription'},
                        status=400
                    )
                
                # For new subscriptions without payment method, create checkout session
                if not serializer.validated_data.get('payment_method_id'):
                    try:
                        # Create Stripe checkout session
                        customer = StripeService.get_or_create_customer(request.user)
                        
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
                                'plan_id': plan.id
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
                    try:
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
                    subscription.stripe_subscription_id,
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
            
                customer = StripeService.get_or_create_customer(request.user)
                
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
            if not new_plan_id:
                return Response({'error': 'Plan ID is required'}, status=400)
            
            new_plan = get_object_or_404(SubscriptionPlan, id=new_plan_id)
            current_subscription = Subscription.objects.get(user=request.user, status__in=['trialing', 'active'])
            
            # Store old plan for credit proration
            old_plan = current_subscription.plan
            
            # Update subscription in Stripe
            stripe.Subscription.modify(
                current_subscription.stripe_subscription_id,
                items=[{
                    'id': stripe.Subscription.retrieve(current_subscription.stripe_subscription_id)['items']['data'][0]['id'],
                    'price': new_plan.stripe_price_id,
                }],
                proration_behavior='create_prorations'
            )
            
            # Update local subscription
            current_subscription.plan = new_plan
            current_subscription.save()
            
            # Prorate credits for the upgrade/downgrade
            CreditService.prorate_credits_for_upgrade(request.user, current_subscription, new_plan)
            
            serializer = SubscriptionSerializer(current_subscription)
            return Response(serializer.data)
        except Subscription.DoesNotExist:
            return Response({'error': 'No active subscription found'}, status=404)
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
            user_id = subscription_data.get('metadata', {}).get('user_id')
            if not user_id:
                logger.error("No user_id in subscription metadata")
                return
            
            from django.contrib.auth import get_user_model
            User = get_user_model()
            
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
            subscription = Subscription.objects.create(
                user=user,
                plan=plan,
                stripe_subscription_id=subscription_data['id'],
                stripe_customer_id=subscription_data['customer'],
                status=subscription_data['status'],
                current_period_start=datetime.fromtimestamp(subscription_data['current_period_start'], tz=dt_timezone.utc),
                current_period_end=datetime.fromtimestamp(subscription_data['current_period_end'], tz=dt_timezone.utc),
                trial_start=datetime.fromtimestamp(subscription_data['trial_start'], tz=dt_timezone.utc) if subscription_data.get('trial_start') else None,
                trial_end=datetime.fromtimestamp(subscription_data['trial_end'], tz=dt_timezone.utc) if subscription_data.get('trial_end') else None
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
            subscription = Subscription.objects.get(stripe_subscription_id=invoice_data['subscription'])
            
            # Create invoice record
            invoice = Invoice.objects.create(
                subscription=subscription,
                stripe_invoice_id=invoice_data['id'],
                amount=invoice_data['amount_paid'] / 100,  # Convert from cents
                currency=invoice_data['currency'],
                status=invoice_data['status'],
                invoice_pdf=invoice_data.get('invoice_pdf'),
                hosted_invoice_url=invoice_data.get('hosted_invoice_url')
            )
            
            # Send payment success email
            email_service = EmailService()
            if EmailService:
                try:
                    success = email_service.send_payment_success_email(
                        subscription,
                        invoice.amount,
                        invoice.stripe_invoice_id
                    )
                    if success:
                        logger.info(f"Payment success email sent to {subscription.user.email}")
                    else:
                        logger.error(f"Failed to send payment success email to {subscription.user.email}")
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
            logger.error(f"Subscription {invoice_data['subscription']} not found")
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
            
            if not user_id or not plan_id:
                logger.error("Missing user_id or plan_id in checkout session metadata")
                return
            
            from django.contrib.auth import get_user_model
            User = get_user_model()
            
            try:
                user = User.objects.get(id=user_id)
                plan = SubscriptionPlan.objects.get(id=plan_id)
            except (User.DoesNotExist, SubscriptionPlan.DoesNotExist) as e:
                logger.error(f"User or plan not found: {e}")
                return
            
            # Create subscription record
            subscription = Subscription.objects.create(
                user=user,
                plan=plan,
                stripe_subscription_id=session_data['subscription'],
                stripe_customer_id=session_data['customer'],
                status='active',
                current_period_start=datetime.fromtimestamp(session_data['subscription_data']['current_period_start'], tz=dt_timezone.utc),
                current_period_end=datetime.fromtimestamp(session_data['subscription_data']['current_period_end'], tz=dt_timezone.utc)
            )
            
            # Allocate credits for new subscription
            CreditService.allocate_credits_for_new_subscription(user, subscription)
            
            logger.info(f"Checkout completed for user {user.email}")
                
        except Exception as e:
            logger.error(f"Error handling checkout.session.completed: {e}")

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
            
            # Find user by customer ID
            user = None
            try:
                user = User.objects.get(stripe_customer_id=customer_id)
            except User.DoesNotExist:
                logger.error(f"User with customer ID {customer_id} not found")
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
                from django.contrib.auth import get_user_model
                User = get_user_model()
                
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
