from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from .services import CreditService

User = get_user_model()

@receiver(post_save, sender=User)
def allocate_trial_credits_for_new_user(sender, instance, created, **kwargs):
    """Automatically allocate trial credits for new users"""
    if created:
        try:
            # Allocate trial credits for new user
            CreditService.allocate_trial_credits(instance)
        except Exception as e:
            print(f"Error allocating trial credits for user {instance.email}: {e}") 