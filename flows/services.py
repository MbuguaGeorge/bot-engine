from typing import List, Dict, Any, Optional
from django.conf import settings
from bots.models import Bot
from .models import Flow
from .flow_engine import FlowEngine
import logging

logger = logging.getLogger(__name__)

class FlowExecutionService:
    """Service for handling WhatsApp webhooks and executing flows"""
    
    def __init__(self):
        self.openai_api_key = settings.OPENAI_API_KEY
    
    def process_webhook(self, webhook_data: Dict[str, Any]) -> List[str]:
        """
        Process incoming webhook from WhatsApp and execute appropriate flow
        
        Args:
            webhook_data: The webhook payload from WhatsApp
            
        Returns:
            List of responses to send back to WhatsApp
        """
        try:
            # Extract phone number and message from webhook
            phone_number = self._extract_phone_number(webhook_data)
            message = self._extract_message(webhook_data)
            
            if not phone_number or not message:
                logger.error("Missing phone number or message in webhook data")
                return []
            
            # Find the bot for this phone number
            bot = self._get_bot(phone_number)
            if not bot:
                logger.error(f"No bot found for phone number: {phone_number}")
                return []
            
            # Get active flow for the bot
            flow = self._get_active_flow(bot)
            if not flow:
                logger.error(f"No active flow found for bot: {bot.id}")
                return []
            
            # Execute the flow
            return self.execute_flow(flow, message)
            
        except Exception as e:
            logger.error(f"Error processing webhook: {str(e)}")
            return []
    
    def execute_flow(self, flow: Flow, user_input: str) -> List[str]:
        """
        Execute a flow with the given user input
        
        Args:
            flow: The Flow object to execute
            user_input: The user's input message
            
        Returns:
            List of responses to send back to the user
        """
        try:
            # Create context with necessary data
            context = {
                "openai_api_key": self.openai_api_key,
                "flow_id": flow.id,
                "bot_id": flow.bot.id
            }
            
            # Initialize and run the flow engine
            engine = FlowEngine(
                flow_data=flow.flow_data,
                user_input=user_input,
                context=context
            )
            
            return engine.run()
            
        except Exception as e:
            logger.error(f"Error executing flow {flow.id}: {str(e)}")
            return ["I apologize, but I'm having trouble processing your request right now."]
    
    def _extract_phone_number(self, webhook_data: Dict[str, Any]) -> Optional[str]:
        """Extract phone number from webhook data"""
        # This needs to be implemented based on your WhatsApp webhook format
        # Example implementation:
        try:
            return webhook_data.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("messages", [{}])[0].get("from")
        except (IndexError, KeyError):
            return None
    
    def _extract_message(self, webhook_data: Dict[str, Any]) -> Optional[str]:
        """Extract message text from webhook data"""
        # This needs to be implemented based on your WhatsApp webhook format
        # Example implementation:
        try:
            return webhook_data.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("messages", [{}])[0].get("text", {}).get("body")
        except (IndexError, KeyError):
            return None
    
    def _get_bot(self, phone_number: str) -> Optional[Bot]:
        """Get bot by phone number"""
        try:
            return Bot.objects.get(phone_number=phone_number, whatsapp_connected=True)
        except Bot.DoesNotExist:
            return None
    
    def _get_active_flow(self, bot: Bot) -> Optional[Flow]:
        """Get active flow for a bot"""
        try:
            return Flow.objects.get(bot=bot, status='active')
        except Flow.DoesNotExist:
            return None 