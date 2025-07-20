import os
from celery import Celery
from django.conf import settings

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'API.settings')

app = Celery('API')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

# Configure periodic tasks
app.conf.beat_schedule = {
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
}

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}') 