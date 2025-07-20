from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)
User = get_user_model()

@shared_task
def delete_expired_accounts():
    """
    Delete user accounts that have been pending deletion for more than 60 days.
    Runs daily via Celery beat.
    """
    cutoff_date = timezone.now() - timedelta(days=60)
    
    # Find users pending deletion for more than 60 days
    users_to_delete = User.objects.filter(
        is_pending_deletion=True,
        deletion_requested_at__lt=cutoff_date
    )
    
    deleted_count = 0
    for user in users_to_delete:
        try:
            user_email = user.email  # Store email for logging
            user.delete()
            deleted_count += 1
            logger.info(f"Deleted user account: {user_email}")
        except Exception as e:
            logger.error(f"Failed to delete user {user.email}: {str(e)}")
    
    if deleted_count > 0:
        logger.info(f"Successfully deleted {deleted_count} expired user accounts")
    
    return deleted_count 