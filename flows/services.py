from typing import List, Dict, Any, Optional
from bots.models import Bot
from .models import Flow
from .flow_engine import FlowEngine
import logging

logger = logging.getLogger(__name__)

class FlowExecutionService:
    """Service for handling WhatsApp webhooks and executing flows"""
    
    def process_webhook(self, webhook_data: Dict[str, Any]) -> List[str]:
        """
        Process incoming webhook from WhatsApp and execute appropriate flow
        
        Args:
            webhook_data: The webhook payload from WhatsApp
            
        Returns:
            List of responses to send back to WhatsApp
        """
        try:
            phone_number_id = self._extract_phone_number_id(webhook_data)
            message = self._extract_message(webhook_data)
            
            if not phone_number_id or not message:
                logger.error("Missing phone number or message in webhook data")
                return []
            
            bot = self._get_bot(phone_number_id)
            if not bot:
                logger.error(f"No bot found for phone number: {phone_number_id}")
                return []
            
            flow = self._get_active_flow(bot)
            if not flow:
                logger.error(f"No active flow found for bot: {bot.id}")
                return []
            
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
            context = {
                "flow_id": flow.id,
                "bot_id": flow.bot.id,
                "files": list(flow.uploaded_files.values_list('id', flat=True)),
                "gdrive_links": flow.flow_data.get("gdrive_links", []),
                "user_id": flow.bot.user.id,
            }
            
            engine = FlowEngine(
                flow_data=flow.flow_data,
                user_input=user_input,
                context=context
            )
            
            return engine.run()
            
        except Exception as e:
            logger.error(f"Error executing flow {flow.id}: {str(e)}")
            return ["I apologize, but I'm having trouble processing your request right now."]
    
    def _extract_phone_number_id(self, webhook_data: Dict[str, Any]) -> Optional[str]:
        """Extract phone number from webhook data"""
        try:
            return webhook_data.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("metadata", {}).get("phone_number_id")
        except (IndexError, KeyError):
            return None
        
    def _extract_phone_number(self, webhook_data: Dict[str, Any]) -> Optional[str]:
        """Extract phone number from webhook data"""
        try:
            return webhook_data.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("messages", [{}])[0].get("from")
        except (IndexError, KeyError):
            return None
    
    def _extract_message(self, webhook_data: Dict[str, Any]) -> Optional[str]:
        """Extract message text from webhook data"""
        try:
            return webhook_data.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("messages", [{}])[0].get("text", {}).get("body")
        except (IndexError, KeyError):
            return None
    
    def _get_bot(self, phone_number_id: str) -> Optional[Bot]:
        """Get bot by phone number ID"""
        try:
            return Bot.objects.get(phone_number_id=phone_number_id, whatsapp_connected=True)
        except Bot.DoesNotExist:
            return None
    
    def _get_active_flow(self, bot: Bot) -> Optional[Flow]:
        """Get active flow for a bot"""
        try:
            return Flow.objects.get(bot=bot, status='active')
        except Flow.DoesNotExist:
            return None 