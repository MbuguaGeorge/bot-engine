import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'API.settings')
app = Celery('API')
app.config_from_object('django.conf:settings', namespace='CELERY')

app.conf.update(
    broker_url=os.getenv('REDIS_URL'),
    result_backend=os.getenv('REDIS_URL'),
    worker_log_level='INFO',
    worker_log_format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)

app.conf.beat_schedule = {
    'upsert-gdrive-links-every-2-hours': {
        'task': 'Engines.rag_engine.tasks.upsert_gdrive_links_to_pinecone',
        'schedule': crontab(hour='*/2'),
    },
    'send-trial-expiry-reminders': {
        'task': 'subscription.tasks.send_trial_expiry_reminders',
        'schedule': 86400.0,  # every day
    },
    'check-expired-subscriptions': {
        'task': 'subscription.tasks.check_expired_subscriptions',
        'schedule': 3600.0,  # Run every hour
    },
    'sync-subscription-status': {
        'task': 'subscription.tasks.sync_subscription_status',
        'schedule': 1800.0,  # Run every 30 minutes
    },
    'cleanup-canceled-subscriptions': {
        'task': 'subscription.tasks.cleanup_canceled_subscriptions',
        'schedule': 86400.0,  # Run daily
    },
    'sync-invoice-history': {
        'task': 'subscription.tasks.sync_invoice_history',
        'schedule': 7200.0,  # Run every 2 hours
    },
    'cleanup-old-webhook-events': {
        'task': 'subscription.tasks.cleanup_old_webhook_events',
        'schedule': 86400.0,  # Run daily
    },
    'delete-expired-accounts': {
        'task': 'account.tasks.delete_expired_accounts',
        'schedule': 86400.0,  # Run daily
    },
    'send-notification-summaries': {
        'task': 'bots.models.NotificationService.send_summaries_to_inactive_users',
        'schedule': 600.0,  # Every 10 minutes
    },
}

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}') 

app.autodiscover_tasks()