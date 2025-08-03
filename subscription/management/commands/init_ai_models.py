from django.core.management.base import BaseCommand
from subscription.models import AIModel
from decimal import Decimal

class Command(BaseCommand):
    help = 'Initialize AI models with default pricing and credit conversion rates'

    def handle(self, *args, **options):
        # Default AI models with current pricing (as of 2024)
        models_data = [
            {
                'name': 'gpt-4o',
                'provider': 'openai',
                'display_name': 'GPT-4o',
                'cost_per_1k_tokens': Decimal('0.005'),
                'credit_conversion_rate': Decimal('1.0'),  # 1 credit = $0.002 worth of tokens
            },
            {
                'name': 'gpt-4o-mini',
                'provider': 'openai',
                'display_name': 'GPT-4o Mini',
                'cost_per_1k_tokens': Decimal('0.00015'),
                'credit_conversion_rate': Decimal('1.0'),
            },
            {
                'name': 'claude-3.5-sonnet',
                'provider': 'anthropic',
                'display_name': 'Claude 3.5 Sonnet',
                'cost_per_1k_tokens': Decimal('0.003'),
                'credit_conversion_rate': Decimal('1.0'),
            },
            {
                'name': 'claude-3-haiku',
                'provider': 'anthropic',
                'display_name': 'Claude 3 Haiku',
                'cost_per_1k_tokens': Decimal('0.00025'),
                'credit_conversion_rate': Decimal('1.0'),
            },
            {
                'name': 'gemini-2.5-pro',
                'provider': 'google',
                'display_name': 'Gemini 2.5 Pro',
                'cost_per_1k_tokens': Decimal('0.0035'),
                'credit_conversion_rate': Decimal('1.0'),
            },
            {
                'name': 'gemini-2.5-flash',
                'provider': 'google',
                'display_name': 'Gemini 2.5 Flash',
                'cost_per_1k_tokens': Decimal('0.000075'),
                'credit_conversion_rate': Decimal('1.0'),
            },
        ]

        created_count = 0
        updated_count = 0

        for model_data in models_data:
            model, created = AIModel.objects.get_or_create(
                name=model_data['name'],
                defaults=model_data
            )
            
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f'Created AI model: {model.display_name}')
                )
            else:
                # Update existing model with new pricing
                for key, value in model_data.items():
                    if key != 'name':  # Don't update the name
                        setattr(model, key, value)
                model.save()
                updated_count += 1
                self.stdout.write(
                    self.style.WARNING(f'Updated AI model: {model.display_name}')
                )

        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully initialized AI models. Created: {created_count}, Updated: {updated_count}'
            )
        ) 