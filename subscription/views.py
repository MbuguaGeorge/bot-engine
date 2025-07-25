from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.http import HttpResponse
from django.utils import timezone
import stripe
import json
from datetime import datetime, timedelta, timezone as dt_timezone

from .models import Subscription, SubscriptionPlan, PaymentMethod, Invoice, WebhookEvent
from .serializers import (
    SubscriptionSerializer, SubscriptionPlanSerializer, PaymentMethodSerializer,
    CreateSubscriptionSerializer, CancelSubscriptionSerializer, UpdatePaymentMethodSerializer
)
from .services import StripeService
from django.conf import settings
from bots.services import NotificationService

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
                        
                        return Response({'url': checkout_session.url}, status=200)
                        
                    except Exception as e:
                        return Response(
                            {'error': 'Unable to create checkout session. Please try again.'},
                            status=400
                        )
                
                # Create subscription with payment method
                subscription = StripeService.create_subscription(
                    user=request.user,
                    plan=plan,
                    payment_method_id=serializer.validated_data.get('payment_method_id'),
                    trial_from_plan=serializer.validated_data.get('trial_from_plan', True)
                )
                
                subscription_serializer = SubscriptionSerializer(subscription)
                return Response(subscription_serializer.data, status=201)
                
            except Exception as e:
                # Provide user-friendly error messages
                error_message = 'Unable to create subscription. Please try again.'
                if 'card' in str(e).lower():
                    error_message = 'Payment method error. Please check your card details.'
                elif 'customer' in str(e).lower():
                    error_message = 'Account setup error. Please contact support.'
                
                return Response({'error': error_message}, status=400)
        
        return Response({'error': 'Invalid plan selection'}, status=400)

class CancelSubscriptionView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        serializer = CancelSubscriptionSerializer(data=request.data)
        if serializer.is_valid():
            try:
                subscription = get_object_or_404(
                    Subscription,
                    user=request.user,
                    status__in=['trialing', 'active']
                )
                
                subscription = StripeService.cancel_subscription(
                    subscription,
                    cancel_at_period_end=serializer.validated_data.get('cancel_at_period_end', True)
                )
                
                subscription_serializer = SubscriptionSerializer(subscription)
                return Response(subscription_serializer.data)
                
            except Exception as e:
                return Response({'error': str(e)}, status=400)
        
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
        payment_method_id = request.data.get('payment_method_id')
        if not payment_method_id:
            return Response({'error': 'Payment method ID is required'}, status=400)
        
        try:
            payment_method = StripeService.create_payment_method(request.user, payment_method_id)
            serializer = PaymentMethodSerializer(payment_method)
            return Response(serializer.data, status=201)
        except Exception as e:
            return Response({'error': str(e)}, status=400)

class UpdatePaymentMethodView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        serializer = UpdatePaymentMethodSerializer(data=request.data)
        if serializer.is_valid():
            try:
                subscription = get_object_or_404(
                    Subscription,
                    user=request.user,
                    status__in=['trialing', 'active']
                )
                
                StripeService.update_subscription_payment_method(
                    subscription,
                    serializer.validated_data['payment_method_id']
                )
                
                return Response({'message': 'Payment method updated successfully'})
                
            except Exception as e:
                return Response({'error': str(e)}, status=400)
        
        return Response(serializer.errors, status=400)

class InvoiceHistoryView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        subscription = Subscription.objects.filter(user=request.user).first()
        if not subscription:
            return Response({'error': 'No subscription found'}, status=404)
        
        try:
            invoices = StripeService.get_invoice_history(subscription)
            from .serializers import InvoiceSerializer
            serializer = InvoiceSerializer(invoices, many=True)
            return Response(serializer.data)
        except Exception as e:
            return Response({'error': str(e)}, status=400)

class UpgradeSubscriptionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        plan_id = request.data.get('plan_id')
        payment_method_id = request.data.get('payment_method_id')
        if not plan_id:
            return Response({'error': 'plan_id is required'}, status=400)
        try:
            plan = get_object_or_404(SubscriptionPlan, id=plan_id)
            subscription = StripeService.upgrade_subscription(
                user=request.user,
                new_plan=plan,
                payment_method_id=payment_method_id
            )
            serializer = SubscriptionSerializer(subscription)
            return Response(serializer.data)
        except Exception as e:
            return Response({'error': str(e)}, status=400)

@method_decorator(csrf_exempt, name='dispatch')
class StripeWebhookView(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
        
        print(f"=== WEBHOOK RECEIVED ===")
        print(f"Webhook received: {request.META.get('HTTP_STRIPE_SIGNATURE', 'No signature')}")
        print(f"Payload length: {len(payload)}")
        print(f"Content-Type: {request.content_type}")
        
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
            print(f"Webhook event type: {event['type']}")
            print(f"Event ID: {event['id']}")
            print(f"Event data keys: {list(event['data']['object'].keys())}")
            
            # Check if this event has already been processed
            if WebhookEvent.objects.filter(stripe_event_id=event['id']).exists():
                print(f"Event {event['id']} already processed, skipping")
                return HttpResponse(status=200)
            
            # Store the event to prevent duplicate processing
            webhook_event = WebhookEvent.objects.create(
                stripe_event_id=event['id'],
                event_type=event['type'],
                data=event['data']
            )
            print(f"Stored webhook event {webhook_event.id} for processing")
            
        except ValueError as e:
            print(f"Webhook ValueError: {str(e)}")
            return HttpResponse(status=400)
        except stripe.error.SignatureVerificationError as e:
            print(f"Webhook signature verification failed: {str(e)}")
            return HttpResponse(status=400)
        except Exception as e:
            print(f"Unexpected error in webhook verification: {str(e)}")
            import traceback
            traceback.print_exc()
            return HttpResponse(status=400)
        
        # Handle the event
        if event['type'] == 'customer.subscription.created':
            self.handle_subscription_created(event['data']['object'])
        elif event['type'] == 'customer.subscription.updated':
            self.handle_subscription_updated(event['data']['object'])
        elif event['type'] == 'customer.subscription.deleted':
            self.handle_subscription_deleted(event['data']['object'])
        elif event['type'] == 'invoice.payment_succeeded':
            self.handle_payment_succeeded(event['data']['object'])
        elif event['type'] == 'invoice.payment_failed':
            self.handle_payment_failed(event['data']['object'])
        elif event['type'] == 'checkout.session.completed':
            self.handle_checkout_completed(event['data']['object'])
        elif event['type'] == 'invoice.created':
            self.handle_invoice_created(event['data']['object'])
        elif event['type'] == 'payment_method.attached':
            self.handle_payment_method_attached(event['data']['object'])
        else:
            print(f"Unhandled event type: {event['type']}")
        
        return HttpResponse(status=200)
    
    def handle_subscription_created(self, subscription_data):
        """Handle subscription creation"""
        try:
            print(f"Handling subscription created: {subscription_data['id']}")
            
            # Get customer and user
            customer_id = subscription_data['customer']
            try:
                existing_subscription = Subscription.objects.get(stripe_customer_id=customer_id)
                user = existing_subscription.user
            except Subscription.DoesNotExist:
                # Try to get user from Stripe customer
                try:
                    customer = stripe.Customer.retrieve(customer_id)
                    from django.contrib.auth import get_user_model
                    User = get_user_model()
                    user = User.objects.get(email=customer.email)
                except Exception as e:
                    print(f"Could not find user for customer {customer_id}: {str(e)}")
                    return
            
            # Get plan
            plan = None
            if subscription_data.get('items') and subscription_data['items'].get('data'):
                # Try to get plan from price ID
                price_id = subscription_data['items']['data'][0]['price']['id']
                try:
                    plan = SubscriptionPlan.objects.get(stripe_price_id=price_id)
                except SubscriptionPlan.DoesNotExist:
                    print(f"Plan with price {price_id} not found")
                    return
            
            # Use get_or_create to prevent duplicates
            subscription, created = Subscription.objects.get_or_create(
                stripe_subscription_id=subscription_data['id'],
                defaults={
                    'user': user,
                    'plan': plan,
                    'stripe_customer_id': customer_id,
                    'status': subscription_data['status'],
                    'current_period_start': datetime.fromtimestamp(subscription_data.get('current_period_start'), tz=dt_timezone.utc) if subscription_data.get('current_period_start') else timezone.now(),
                    'current_period_end': datetime.fromtimestamp(subscription_data.get('current_period_end'), tz=dt_timezone.utc) if subscription_data.get('current_period_end') else timezone.now() + timedelta(days=30),
                    'trial_start': datetime.fromtimestamp(subscription_data.get('trial_start'), tz=dt_timezone.utc) if subscription_data.get('trial_start') else None,
                    'trial_end': datetime.fromtimestamp(subscription_data.get('trial_end'), tz=dt_timezone.utc) if subscription_data.get('trial_end') else None,
                }
            )
            
            if created:
                print(f"Successfully created subscription {subscription.id} for user {user.id}")
                NotificationService.create_and_send(
                    user=subscription.user,
                    type="subscription_activated",
                    title="Subscription Activated",
                    message="Your subscription is now active.",
                )
            else:
                print(f"Subscription {subscription.id} already exists for user {user.id}")
            
        except Exception as e:
            print(f"Error handling subscription created: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def handle_subscription_updated(self, subscription_data):
        try:
            print(f"Handling subscription updated: {subscription_data['id']}")
            subscription = Subscription.objects.get(
                stripe_subscription_id=subscription_data['id']
            )
            StripeService.sync_subscription_from_stripe(subscription_data['id'])
        except Subscription.DoesNotExist:
            print(f"Subscription {subscription_data['id']} not found for update")
            # Try to create it if it doesn't exist
            self.handle_subscription_created(subscription_data)
    
    def handle_subscription_deleted(self, subscription_data):
        try:
            subscription = Subscription.objects.get(
                stripe_subscription_id=subscription_data['id']
            )
            subscription.status = 'canceled'
            subscription.save()
        except Subscription.DoesNotExist:
            pass
    
    def handle_payment_succeeded(self, invoice_data):
        """Handle successful payment"""
        try:
            print(f"Handling payment succeeded for invoice: {invoice_data['id']}")
            
            # Use get_or_create for invoice to prevent duplicates
            subscription_id = invoice_data.get('subscription')
            if not subscription_id:
                print("No subscription found for invoice")
                return
            
            # Get subscription from database or create from Stripe
            try:
                subscription = Subscription.objects.get(stripe_subscription_id=subscription_id)
                print(f"Found subscription: {subscription.id} for user: {subscription.user.email}")
                NotificationService.create_and_send(
                    user=subscription.user,
                    type="payment_success",
                    title="Payment Successful",
                    message="Your payment was processed successfully.",
                )
            except Subscription.DoesNotExist:
                print(f"Subscription {subscription_id} not found in database, getting from Stripe")
                try:
                    # Get subscription from Stripe
                    stripe_subscription = stripe.Subscription.retrieve(subscription_id)
                    
                    # Get user from customer
                    customer_id = stripe_subscription.customer
                    try:
                        customer = stripe.Customer.retrieve(customer_id)
                        from django.contrib.auth import get_user_model
                        User = get_user_model()
                        user = User.objects.get(email=customer.email)
                    except Exception as e:
                        print(f"Could not find user for customer {customer_id}: {str(e)}")
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
                        print(f"Created subscription {subscription.id} from Stripe data for invoice")
                        NotificationService.create_and_send(
                            user=subscription.user,
                            type="subscription_activated",
                            title="Subscription Activated",
                            message="Your subscription is now active.",
                        )
                    else:
                        print(f"Subscription {subscription.id} already exists from Stripe data")
                except Exception as e:
                    print(f"Error getting subscription from Stripe: {str(e)}")
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
                print(f"Created new invoice {invoice.id} for subscription {subscription.id}")
            else:
                # Update existing invoice
                invoice.status = invoice_data.get('status', 'paid')
                invoice.amount = (invoice_data.get('amount_paid') or invoice_data.get('amount_due') or 0) / 100
                invoice.save()
                print(f"Updated existing invoice {invoice.id}")
            
            # Sync subscription status
            StripeService.sync_subscription_from_stripe(subscription_id)
            
        except Exception as e:
            print(f"Error handling payment succeeded: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def handle_payment_failed(self, invoice_data):
        """Handle failed payment"""
        try:
            print(f"Handling payment failed for invoice: {invoice_data['id']}")
            subscription_id = invoice_data.get('subscription')
            if subscription_id:
                # Get subscription from database or create from Stripe
                try:
                    subscription = Subscription.objects.get(stripe_subscription_id=subscription_id)
                    subscription.status = 'past_due'
                    subscription.save()
                    NotificationService.create_and_send(
                        user=subscription.user,
                        type="payment_failed",
                        title="Payment Failed",
                        message="A payment for your subscription failed. Please update your payment method.",
                    )
                except Subscription.DoesNotExist:
                    print(f"Subscription {subscription_id} not found in database, getting from Stripe")
                    try:
                        # Get subscription from Stripe
                        stripe_subscription = stripe.Subscription.retrieve(subscription_id)
                        
                        # Get user from customer
                        customer_id = stripe_subscription.customer
                        try:
                            customer = stripe.Customer.retrieve(customer_id)
                            from django.contrib.auth import get_user_model
                            User = get_user_model()
                            user = User.objects.get(email=customer.email)
                        except Exception as e:
                            print(f"Could not find user for customer {customer_id}: {str(e)}")
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
                                'status': 'past_due',  # Set as past_due since payment failed
                                'current_period_start': datetime.fromtimestamp(stripe_subscription.get('current_period_start'), tz=dt_timezone.utc) if stripe_subscription.get('current_period_start') else timezone.now(),
                                'current_period_end': datetime.fromtimestamp(stripe_subscription.get('current_period_end'), tz=dt_timezone.utc) if stripe_subscription.get('current_period_end') else timezone.now() + timedelta(days=30),
                                'trial_start': datetime.fromtimestamp(stripe_subscription.get('trial_start'), tz=dt_timezone.utc) if stripe_subscription.get('trial_start') else None,
                                'trial_end': datetime.fromtimestamp(stripe_subscription.get('trial_end'), tz=dt_timezone.utc) if stripe_subscription.get('trial_end') else None,
                            }
                        )
                        if created:
                            print(f"Created subscription {subscription.id} from Stripe data for failed payment")
                            NotificationService.create_and_send(
                                user=subscription.user,
                                type="payment_failed",
                                title="Payment Failed",
                                message="A payment for your subscription failed. Please update your payment method.",
                            )
                        else:
                            subscription.status = 'past_due'
                            subscription.save()
                            print(f"Updated subscription {subscription.id} status to past_due")
                    except Exception as e:
                        print(f"Error getting subscription from Stripe: {str(e)}")
        except Exception as e:
            print(f"Error handling payment failed: {str(e)}")
    
    def handle_checkout_completed(self, session_data):
        """Handle successful checkout session completion"""
        try:
            print(f"Handling checkout completed: {session_data['id']}")
            
            # Extract metadata
            user_id = session_data.get('metadata', {}).get('user_id')
            plan_id = session_data.get('metadata', {}).get('plan_id')
            
            if not user_id or not plan_id:
                print("Missing user_id or plan_id in metadata")
                return
            
            # Get user and plan
            from django.contrib.auth import get_user_model
            User = get_user_model()
            
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                print(f"User {user_id} not found")
                return
                
            try:
                plan = SubscriptionPlan.objects.get(id=plan_id)
            except SubscriptionPlan.DoesNotExist:
                print(f"Plan {plan_id} not found")
                return
            
            # Get the subscription from Stripe
            subscription_id = session_data.get('subscription')
            if subscription_id:
                try:
                    stripe_subscription = stripe.Subscription.retrieve(subscription_id)
                    
                    # Use get_or_create to prevent duplicates
                    subscription, created = Subscription.objects.get_or_create(
                        stripe_subscription_id=stripe_subscription.id,
                        defaults={
                            'user': user,
                            'plan': plan,
                            'stripe_customer_id': stripe_subscription.customer,
                            'status': stripe_subscription.status,
                            'current_period_start': datetime.fromtimestamp(stripe_subscription.get('current_period_start'), tz=dt_timezone.utc) if stripe_subscription.get('current_period_start') else timezone.now(),
                            'current_period_end': datetime.fromtimestamp(stripe_subscription.get('current_period_end'), tz=dt_timezone.utc) if stripe_subscription.get('current_period_end') else timezone.now() + timedelta(days=30),
                            'trial_start': datetime.fromtimestamp(stripe_subscription.get('trial_start'), tz=dt_timezone.utc) if stripe_subscription.get('trial_start') else None,
                            'trial_end': datetime.fromtimestamp(stripe_subscription.get('trial_end'), tz=dt_timezone.utc) if stripe_subscription.get('trial_end') else None,
                        }
                    )
                    
                    if created:
                        print(f"Successfully created subscription {subscription.id} for user {user.id}")
                        NotificationService.create_and_send(
                            user=subscription.user,
                            type="subscription_activated",
                            title="Subscription Activated",
                            message="Your subscription is now active.",
                        )
                    else:
                        print(f"Subscription {subscription.id} already exists for user {user.id}")
                    
                except stripe.error.InvalidRequestError as e:
                    print(f"Subscription {subscription_id} not found in Stripe: {str(e)}")
                    return
                
                except Exception as e:
                    print(f"Error retrieving subscription from Stripe: {str(e)}")
                    return
                
        except Exception as e:
            print(f"Error handling checkout completion: {str(e)}")
            import traceback
            traceback.print_exc()

    def handle_invoice_created(self, invoice_data):
        """Handle invoice creation"""
        try:
            print(f"Handling invoice created: {invoice_data['id']}")
            
            # Get subscription
            subscription_id = invoice_data.get('subscription')
            if not subscription_id:
                print("No subscription found for invoice")
                return
            
            # Get subscription from database or create from Stripe
            try:
                subscription = Subscription.objects.get(stripe_subscription_id=subscription_id)
                print(f"Found subscription: {subscription.id} for user: {subscription.user.email}")
            except Subscription.DoesNotExist:
                print(f"Subscription {subscription_id} not found in database, getting from Stripe")
                try:
                    # Get subscription from Stripe
                    stripe_subscription = stripe.Subscription.retrieve(subscription_id)
                    
                    # Get user from customer
                    customer_id = stripe_subscription.customer
                    try:
                        customer = stripe.Customer.retrieve(customer_id)
                        from django.contrib.auth import get_user_model
                        User = get_user_model()
                        user = User.objects.get(email=customer.email)
                    except Exception as e:
                        print(f"Could not find user for customer {customer_id}: {str(e)}")
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
                        print(f"Created subscription {subscription.id} from Stripe data for invoice")
                    else:
                        print(f"Subscription {subscription.id} already exists from Stripe data")
                except Exception as e:
                    print(f"Error getting subscription from Stripe: {str(e)}")
                    return
            
            # Create or update invoice record
            invoice, created = Invoice.objects.get_or_create(
                stripe_invoice_id=invoice_data['id'],
                defaults={
                    'subscription': subscription,
                    'amount': (invoice_data.get('amount_due') or 0) / 100,
                    'currency': invoice_data.get('currency', 'usd'),
                    'status': invoice_data.get('status', 'open'),
                    'invoice_pdf': invoice_data.get('invoice_pdf', ''),
                    'hosted_invoice_url': invoice_data.get('hosted_invoice_url', ''),
                }
            )
            
            if created:
                print(f"Successfully created invoice {invoice.id} for subscription {subscription.id}")
            else:
                print(f"Invoice {invoice.id} already exists for subscription {subscription.id}")
            
        except Exception as e:
            print(f"Error handling invoice created: {str(e)}")
            import traceback
            traceback.print_exc()

    def handle_payment_method_attached(self, payment_method_data):
        """Handle payment method attachment"""
        try:
            print(f"Handling payment method attached: {payment_method_data['id']}")
            
            # Get customer and find user
            customer_id = payment_method_data['customer']
            
            try:
                existing_subscription = Subscription.objects.get(stripe_customer_id=customer_id)
                user = existing_subscription.user
            except Subscription.DoesNotExist:
                # If no existing subscription, try to find user by customer ID in Stripe
                try:
                    customer = stripe.Customer.retrieve(customer_id)
                    user_email = customer.email
                    from django.contrib.auth import get_user_model
                    User = get_user_model()
                    user = User.objects.get(email=user_email)
                except Exception as e:
                    print(f"Could not find user for customer {customer_id}: {str(e)}")
                    return
            
            # Use get_or_create for payment method
            payment_method, created = PaymentMethod.objects.get_or_create(
                stripe_payment_method_id=payment_method_data['id'],
                defaults={
                    'user': user,
                    'card_brand': payment_method_data['card']['brand'],
                    'card_last4': payment_method_data['card']['last4'],
                    'card_exp_month': payment_method_data['card']['exp_month'],
                    'card_exp_year': payment_method_data['card']['exp_year'],
                    'is_default': payment_method_data.get('metadata', {}).get('is_default', False),
                }
            )
            
            if created:
                print(f"Successfully created payment method {payment_method.id} for user {user.id}")
            else:
                print(f"Payment method {payment_method.id} already exists for user {user.id}")
            
        except Exception as e:
            print(f"Error handling payment method attached: {str(e)}")
            import traceback
            traceback.print_exc()

class BillingPortalView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            subscription = Subscription.objects.filter(user=request.user).first()
            if not subscription:
                return Response({'error': 'No subscription found'}, status=404)
            
            customer = StripeService.get_or_create_customer(request.user)
            session = stripe.billing_portal.Session.create(
                customer=customer.id,
                return_url=f"{settings.FRONTEND_URL}/dashboard/billing"
            )
            
            return Response({'url': session.url})
            
        except Exception as e:
            return Response({'error': str(e)}, status=400)
