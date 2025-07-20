from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from django.core.mail import send_mail
from django.conf import settings
from .models import Subscription
from .services import StripeService
import logging

logger = logging.getLogger(__name__)

@shared_task
def check_expired_subscriptions():
    """Check for expired subscriptions and update their status"""
    try:
        # Find subscriptions that have expired
        expired_subscriptions = Subscription.objects.filter(
            current_period_end__lt=timezone.now(),
            status__in=['trialing', 'active']
        )
        
        for subscription in expired_subscriptions:
            try:
                # Sync with Stripe to get latest status
                StripeService.sync_subscription_from_stripe(subscription.stripe_subscription_id)
                
                # Send notification to user
                send_subscription_expired_notification.delay(subscription.id)
                
                logger.info(f"Processed expired subscription: {subscription.id}")
                
            except Exception as e:
                logger.error(f"Error processing expired subscription {subscription.id}: {str(e)}")
        
        logger.info(f"Processed {expired_subscriptions.count()} expired subscriptions")
        
    except Exception as e:
        logger.error(f"Error in check_expired_subscriptions task: {str(e)}")

@shared_task
def sync_subscription_status():
    """Sync all subscription statuses with Stripe"""
    try:
        subscriptions = Subscription.objects.filter(
            status__in=['trialing', 'active', 'past_due']
        )
        
        for subscription in subscriptions:
            try:
                StripeService.sync_subscription_from_stripe(subscription.stripe_subscription_id)
                logger.info(f"Synced subscription: {subscription.id}")
            except Exception as e:
                logger.error(f"Error syncing subscription {subscription.id}: {str(e)}")
        
        logger.info(f"Synced {subscriptions.count()} subscriptions")
        
    except Exception as e:
        logger.error(f"Error in sync_subscription_status task: {str(e)}")

@shared_task
def send_subscription_expired_notification(subscription_id):
    """Send notification to user about expired subscription"""
    try:
        subscription = Subscription.objects.get(id=subscription_id)
        user = subscription.user
        
        plan_name = subscription.plan.name if subscription.plan else "Trial Period"
        
        subject = "Your subscription has expired"
        message = f"""
        Dear {user.full_name},
        
        Your {plan_name} subscription has expired on {subscription.current_period_end.strftime('%B %d, %Y')}.
        
        To continue using our services, please renew your subscription by visiting your billing dashboard.
        
        If you have any questions, please contact our support team.
        
        Best regards,
        The Wozza Team
        """
        
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
        
        logger.info(f"Sent expiration notification to {user.email}")
        
    except Exception as e:
        logger.error(f"Error sending expiration notification: {str(e)}")

@shared_task
def send_trial_ending_notification(subscription_id):
    """Send notification to user about trial ending soon"""
    try:
        subscription = Subscription.objects.get(id=subscription_id)
        user = subscription.user
        
        if subscription.is_trialing and subscription.trial_end:
            days_left = (subscription.trial_end - timezone.now()).days
            
            if days_left <= 3:  # Send notification 3 days before trial ends
                plan_name = subscription.plan.name if subscription.plan else "Trial Period"
                
                subject = "Your trial is ending soon"
                message = f"""
                Dear {user.full_name},
                
                Your trial for {plan_name} will end in {days_left} days on {subscription.trial_end.strftime('%B %d, %Y')}.
                
                To continue using our services without interruption, please add a payment method and upgrade to a paid plan.
                
                If you have any questions, please contact our support team.
                
                Best regards,
                The Wozza Team
                """
                
                send_mail(
                    subject=subject,
                    message=message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    fail_silently=False,
                )
                
                logger.info(f"Sent trial ending notification to {user.email}")
        
    except Exception as e:
        logger.error(f"Error sending trial ending notification: {str(e)}")

@shared_task
def cleanup_canceled_subscriptions():
    """Clean up old canceled subscriptions"""
    try:
        # Find subscriptions canceled more than 30 days ago
        cutoff_date = timezone.now() - timezone.timedelta(days=30)
        old_canceled_subscriptions = Subscription.objects.filter(
            status='canceled',
            canceled_at__lt=cutoff_date
        )
        
        count = old_canceled_subscriptions.count()
        old_canceled_subscriptions.delete()
        
        logger.info(f"Cleaned up {count} old canceled subscriptions")
        
    except Exception as e:
        logger.error(f"Error in cleanup_canceled_subscriptions task: {str(e)}")

@shared_task
def sync_invoice_history():
    """Sync invoice history for all subscriptions"""
    try:
        subscriptions = Subscription.objects.all()
        for subscription in subscriptions:
            try:
                StripeService.get_invoice_history(subscription)
            except Exception as e:
                print(f"Error syncing invoices for subscription {subscription.id}: {str(e)}")
    except Exception as e:
        print(f"Error in sync_invoice_history task: {str(e)}")

@shared_task
def cleanup_old_webhook_events():
    """Clean up webhook events older than 30 days to prevent database bloat"""
    try:
        from datetime import timedelta
        from django.utils import timezone
        from .models import WebhookEvent
        
        cutoff_date = timezone.now() - timedelta(days=30)
        deleted_count, _ = WebhookEvent.objects.filter(processed_at__lt=cutoff_date).delete()
        print(f"Cleaned up {deleted_count} old webhook events")
    except Exception as e:
        print(f"Error in cleanup_old_webhook_events task: {str(e)}") 

@shared_task
def send_trial_expiry_reminders():
    from bots.models import Bot
    now = timezone.now()
    soon = now + timedelta(days=2)
    tomorrow = now + timedelta(days=1)
    # 2 days left
    two_days_left = Subscription.objects.filter(
        status='trialing',
        trial_end__date=soon.date()
    )
    for sub in two_days_left:
        send_mail(
            subject='Your trial is ending soon! (2 days left)',
            message='Your 7-day trial will end in 2 days. Please subscribe to continue using the service.',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[sub.user.email],
            fail_silently=True,
        )
    # 1 day left
    one_day_left = Subscription.objects.filter(
        status='trialing',
        trial_end__date=tomorrow.date()
    )
    for sub in one_day_left:
        send_mail(
            subject='Your trial is ending tomorrow!',
            message='Your 7-day trial will end tomorrow. Please subscribe to avoid interruption.',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[sub.user.email],
            fail_silently=True,
        )
    # Expired trials: set to unpaid and turn bots offline
    expired_trials = Subscription.objects.filter(
        status='trialing',
        trial_end__lt=now
    )
    for sub in expired_trials:
        sub.status = 'unpaid'
        sub.save(update_fields=['status'])
        # Turn all bots for this user to offline
        Bot.objects.filter(user=sub.user).update(status='disconnected', whatsapp_connected=False)

# Add to beat schedule
from celery import Celery
app = Celery('API')

app.conf.beat_schedule['send-trial-expiry-reminders'] = {
    'task': 'subscription.tasks.send_trial_expiry_reminders',
    'schedule': 86400.0,  # every day
} 