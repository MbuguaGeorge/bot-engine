from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from django.conf import settings
from .models import Subscription
from .services import StripeService
from email_templates.email_service import EmailService
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
        
        # Send email using MailerSend
        email_service = EmailService()
        if email_service:
            try:
                success = email_service.send_subscription_expired_email(subscription)
                if success:
                    logger.info(f"Subscription expired email sent successfully to {subscription.user.email}")
                else:
                    logger.error(f"Failed to send subscription expired email to {subscription.user.email}")
            except Exception as e:
                logger.error(f"Exception sending subscription expired email to {subscription.user.email}: {str(e)}")
        else:
            logger.error("Email service not available - subscription expired email not sent")
        
    except Exception as e:
        logger.error(f"Error sending expiration notification: {str(e)}")

@shared_task
def send_trial_ending_notification(subscription_id):
    """Send notification to user about trial ending soon"""
    try:
        subscription = Subscription.objects.get(id=subscription_id)
        
        # Send email using MailerSend
        if email_service:
            try:
                success = email_service.send_trial_ending_email(subscription)
                if success:
                    logger.info(f"Trial ending email sent successfully to {subscription.user.email}")
                else:
                    logger.error(f"Failed to send trial ending email to {subscription.user.email}")
            except Exception as e:
                logger.error(f"Exception sending trial ending email to {subscription.user.email}: {str(e)}")
        else:
            logger.error("Email service not available - trial ending email not sent")
        
    except Exception as e:
        logger.error(f"Error sending trial ending notification: {str(e)}")

@shared_task
def send_payment_failed_notification(subscription_id, retry_date=None):
    """Send notification to user about failed payment"""
    try:
        subscription = Subscription.objects.get(id=subscription_id)
        
        # Send email using MailerSend
        if email_service:
            try:
                success = email_service.send_payment_failed_email(subscription, retry_date)
                if success:
                    logger.info(f"Payment failed email sent successfully to {subscription.user.email}")
                else:
                    logger.error(f"Failed to send payment failed email to {subscription.user.email}")
            except Exception as e:
                logger.error(f"Exception sending payment failed email to {subscription.user.email}: {str(e)}")
        else:
            logger.error("Email service not available - payment failed email not sent")
        
    except Exception as e:
        logger.error(f"Error sending payment failed notification: {str(e)}")

@shared_task
def send_payment_success_notification(subscription_id, amount, transaction_id):
    """Send notification to user about successful payment"""
    try:
        subscription = Subscription.objects.get(id=subscription_id)
        
        # Send email using MailerSend
        if email_service:
            try:
                success = email_service.send_payment_success_email(subscription, amount, transaction_id)
                if success:
                    logger.info(f"Payment success email sent successfully to {subscription.user.email}")
                else:
                    logger.error(f"Failed to send payment success email to {subscription.user.email}")
            except Exception as e:
                logger.error(f"Exception sending payment success email to {subscription.user.email}: {str(e)}")
        else:
            logger.error("Email service not available - payment success email not sent")
        
    except Exception as e:
        logger.error(f"Error sending payment success notification: {str(e)}")

@shared_task
def cleanup_canceled_subscriptions():
    """Clean up canceled subscriptions after a certain period"""
    try:
        # Find subscriptions that were canceled more than 30 days ago
        cutoff_date = timezone.now() - timedelta(days=30)
        canceled_subscriptions = Subscription.objects.filter(
            status='canceled',
            canceled_at__lt=cutoff_date
        )
        
        count = canceled_subscriptions.count()
        canceled_subscriptions.delete()
        
        logger.info(f"Cleaned up {count} canceled subscriptions")
        
    except Exception as e:
        logger.error(f"Error in cleanup_canceled_subscriptions task: {str(e)}")

@shared_task
def sync_invoice_history():
    """Sync invoice history from Stripe"""
    try:
        subscriptions = Subscription.objects.filter(
            status__in=['active', 'trialing']
        )
        
        for subscription in subscriptions:
            try:
                StripeService.get_invoice_history(subscription)
                logger.info(f"Synced invoice history for subscription: {subscription.id}")
            except Exception as e:
                logger.error(f"Error syncing invoice history for subscription {subscription.id}: {str(e)}")
        
        logger.info(f"Synced invoice history for {subscriptions.count()} subscriptions")
        
    except Exception as e:
        logger.error(f"Error in sync_invoice_history task: {str(e)}")

@shared_task
def cleanup_old_webhook_events():
    """Clean up old webhook events to prevent database bloat"""
    try:
        from .models import WebhookEvent
        
        # Delete webhook events older than 90 days
        cutoff_date = timezone.now() - timedelta(days=90)
        old_events = WebhookEvent.objects.filter(processed_at__lt=cutoff_date)
        
        count = old_events.count()
        old_events.delete()
        
        logger.info(f"Cleaned up {count} old webhook events")
        
    except Exception as e:
        logger.error(f"Error in cleanup_old_webhook_events task: {str(e)}")

@shared_task
def send_trial_expiry_reminders():
    """Send reminders to users whose trial is ending soon"""
    try:
        # Find users whose trial ends in 3 days
        reminder_date = timezone.now() + timedelta(days=3)
        trial_subscriptions = Subscription.objects.filter(
        status='trialing',
            trial_end__date=reminder_date.date()
    )
        
        for subscription in trial_subscriptions:
            try:
                send_trial_ending_notification.delay(subscription.id)
                logger.info(f"Sent trial expiry reminder to {subscription.user.email}")
            except Exception as e:
                logger.error(f"Error sending trial expiry reminder to {subscription.user.email}: {str(e)}")
        
        logger.info(f"Sent {trial_subscriptions.count()} trial expiry reminders")
        
    except Exception as e:
        logger.error(f"Error in send_trial_expiry_reminders task: {str(e)}")