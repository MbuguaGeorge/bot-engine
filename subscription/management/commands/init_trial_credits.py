from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from subscription.services import CreditService

User = get_user_model()

class Command(BaseCommand):
    help = 'Initialize trial credits for existing users who don\'t have a subscription'

    def handle(self, *args, **options):
        # Get all users
        users = User.objects.all()
        trial_users_created = 0
        
        for user in users:
            try:
                # Check if user has an active subscription
                from subscription.models import Subscription
                active_subscription = Subscription.objects.filter(
                    user=user, 
                    status__in=['trialing', 'active']
                ).first()
                
                if not active_subscription:
                    # User has no active subscription, allocate trial credits
                    balance = CreditService.get_or_create_credit_balance(user)
                    
                    if not balance.trial_credits_allocated:
                        CreditService.allocate_trial_credits(user)
                        trial_users_created += 1
                        self.stdout.write(
                            self.style.SUCCESS(f'Trial credits allocated for user: {user.email}')
                        )
                    else:
                        self.stdout.write(
                            self.style.WARNING(f'Trial credits already allocated for user: {user.email}')
                        )
                else:
                    self.stdout.write(
                        self.style.WARNING(f'User {user.email} has active subscription, skipping trial allocation')
                    )
                    
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'Error allocating trial credits for user {user.email}: {e}')
                )
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully allocated trial credits for {trial_users_created} users')
        ) 