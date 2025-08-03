from functools import wraps
from django.http import JsonResponse
from rest_framework.response import Response
from rest_framework import status
import logging
from .services import CreditService

logger = logging.getLogger(__name__)

def require_credits(model_name_field='model_name', input_tokens_field='input_tokens', output_tokens_field='output_tokens'):
    """
    Decorator to automatically deduct credits for AI model usage
    
    Usage:
    @require_credits('model_name', 'input_tokens', 'output_tokens')
    def your_ai_function(self, request):
        # Your AI processing code here
        pass
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, request, *args, **kwargs):
            try:
                # Get the model name and token counts from request data
                model_name = request.data.get(model_name_field)
                input_tokens = request.data.get(input_tokens_field, 0)
                output_tokens = request.data.get(output_tokens_field, 0)
                bot_id = request.data.get('bot_id')
                request_id = request.data.get('request_id')
                
                if not model_name:
                    return Response(
                        {'error': f'Missing required field: {model_name_field}'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                # Calculate credits needed
                credits_needed = CreditService.calculate_credits_needed(
                    model_name, input_tokens, output_tokens
                )
                
                # Deduct credits before processing
                deduction_result = CreditService.deduct_credits(
                    user=request.user,
                    model_name=model_name,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    bot_id=bot_id,
                    request_id=request_id
                )
                
                # Add credit information to request data for the function to use
                request.credit_info = deduction_result
                
                # Call the original function
                result = func(self, request, *args, **kwargs)
                
                # Add credit information to response if it's a Response object
                if isinstance(result, Response):
                    result.data['credit_info'] = {
                        'credits_deducted': deduction_result['credits_deducted'],
                        'credits_remaining': deduction_result['credits_remaining'],
                        'cost_usd': deduction_result['cost_usd']
                    }
                
                return result
                
            except ValueError as e:
                # Insufficient credits or invalid model
                return Response(
                    {'error': str(e)},
                    status=status.HTTP_400_BAD_REQUEST
                )
            except Exception as e:
                logger.error(f"Error in credit deduction: {e}")
                return Response(
                    {'error': 'Failed to process credit deduction'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        
        return wrapper
    return decorator

def check_credits_only(model_name_field='model_name', input_tokens_field='input_tokens', output_tokens_field='output_tokens'):
    """
    Decorator to check if user has sufficient credits without deducting them
    
    Usage:
    @check_credits_only('model_name', 'input_tokens', 'output_tokens')
    def your_ai_function(self, request):
        # Your AI processing code here
        pass
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, request, *args, **kwargs):
            try:
                # Get the model name and token counts from request data
                model_name = request.data.get(model_name_field)
                input_tokens = request.data.get(input_tokens_field, 0)
                output_tokens = request.data.get(output_tokens_field, 0)
                
                if not model_name:
                    return Response(
                        {'error': f'Missing required field: {model_name_field}'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                # Calculate credits needed
                credits_needed = CreditService.calculate_credits_needed(
                    model_name, input_tokens, output_tokens
                )
                
                # Check if user has sufficient credits
                balance = CreditService.get_or_create_credit_balance(request.user)
                if not balance.has_sufficient_credits(credits_needed):
                    return Response(
                        {'error': f'Insufficient credits. Required: {credits_needed}, Available: {balance.credits_remaining}'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                # Add credit information to request data
                request.credit_info = {
                    'credits_needed': credits_needed,
                    'credits_remaining': balance.credits_remaining
                }
                
                # Call the original function
                return func(self, request, *args, **kwargs)
                
            except Exception as e:
                logger.error(f"Error in credit check: {e}")
                return Response(
                    {'error': 'Failed to check credits'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        
        return wrapper
    return decorator 