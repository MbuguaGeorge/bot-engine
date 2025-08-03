from django.core.management.base import BaseCommand
from subscription.models import SubscriptionPlan

class Command(BaseCommand):
    help = 'Update existing subscription plans with credit-based values'

    def handle(self, *args, **options):
        # Define plan updates based on plan type - only credits matter
        plan_updates = {
            'basic': {
                'credits_per_month': 1000,
            },
            'pro': {
                'credits_per_month': 5000,
            },
            'enterprise': {
                'credits_per_month': 25000,
            },
        }

        updated_count = 0

        for plan_type, features in plan_updates.items():
            plans = SubscriptionPlan.objects.filter(plan_type=plan_type)
            
            for plan in plans:
                # Update the plan with new credit-based features
                plan.credits_per_month = features['credits_per_month']
                plan.save()
                
                updated_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f'Updated plan: {plan.name} ({plan.plan_type}) - {plan.credits_per_month} credits/month')
                )

        self.stdout.write(
            self.style.SUCCESS(f'Successfully updated {updated_count} subscription plans with credit-based features')
        ) 