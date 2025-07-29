from typing import List, Dict, Any, Optional
from bots.models import Bot
from .models import Flow, Conversation
from .flow_engine import FlowEngine
import logging
import json
import redis
from django.conf import settings

logger = logging.getLogger(__name__)

# Redis client for publishing chat messages
_redis_client = None

def get_redis_client():
    global _redis_client
    if _redis_client is None:
        redis_url = getattr(settings, 'REDIS_URL', 'redis://localhost:6379/0')
        _redis_client = redis.Redis.from_url(redis_url)
    return _redis_client

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
            phone_number = self._extract_phone_number(webhook_data)
            
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
            
            # Conversation handoff logic
            conversation_id = f"bot_{bot.id}_{phone_number}"
            conversation, _ = Conversation.objects.get_or_create(
                conversation_id=conversation_id,
                bot=bot,
                defaults={"user_id": phone_number}
            )
            # Always publish user messages to Node.js chat service for display
            self._store_chat_message(bot.id, phone_number, message, 'user')
            # Handoff keyword detection
            HANDOFF_KEYWORD = '#agent'
            if message.strip().lower() == HANDOFF_KEYWORD:
                if not conversation.handoff_active:
                    conversation.handoff_active = True
                    conversation.save(update_fields=["handoff_active"])
                    logger.info(f"Handoff activated for {conversation_id}")
                return []  # Do not process bot flow when handoff is triggered
            # If handoff is active, pause bot replies
            if conversation.handoff_active:
                logger.info(f"Handoff active for {conversation_id}, skipping bot flow.")
                return []
            responses = self.execute_flow(flow, message)
            # Publish bot responses to Node.js chat service for display
            redis_client = get_redis_client()
            for resp in responses:
                bot_message_data = {
                    "conversation_id": conversation_id,
                    "bot_id": str(bot.id),
                    "message": {
                        "sender": "bot",
                        "from": phone_number_id,
                        "content": resp,
                        "type": "text",
                        "status": "sent",
                        "timestamp": self._get_current_timestamp()
                    }
                }
                try:
                    redis_client.publish(f"chat_message_{bot.id}", json.dumps(bot_message_data))
                    logger.info(f"Published bot reply to Redis: {conversation_id} - bot: {resp[:50]}...")
                except Exception as re:
                    logger.error(f"Redis publish error (bot reply): {re}")
            return responses
        except Exception as e:
            logger.error(f"Error processing webhook: {str(e)}")
            return []
    
    def _store_chat_message(self, bot_id: int, phone_number: str, content: str, sender: str):
        """Store message in Node.js chat service via Redis (only for user messages)"""
        try:
            if sender != 'user':
                return  # Only publish user messages to Node.js
            conversation_id = f"bot_{bot_id}_{phone_number}"
            message_data = {
                "conversation_id": conversation_id,
                "bot_id": str(bot_id),
                "message": {
                    "sender": sender,
                    "from": phone_number,
                    "content": content,
                    "type": "text",
                    "status": "sent",
                    "timestamp": self._get_current_timestamp()
                }
            }
            redis_client = get_redis_client()
            try:
                redis_client.publish('chat_message', json.dumps(message_data))
                logger.info(f"Published chat message to Redis: {conversation_id} - {sender}: {content[:50]}...")
            except Exception as re:
                logger.error(f"Redis publish error: {re}")
        except Exception as e:
            logger.error(f"Error storing chat message: {str(e)}")
            # Don't raise the exception to avoid breaking the webhook flow
    
    def _get_current_timestamp(self) -> str:
        """Get current timestamp in ISO format"""
        from datetime import datetime
        return datetime.utcnow().isoformat() + 'Z'
    
    def execute_flow(self, flow: Flow, user_input: str) -> List[str]:
        """
        Execute a flow with the given user input
        
        Args:
            flow: The Flow object to execute
            user_input: The user's input message
            
        Returns:
            List of responses to send back to the user
        """
        gdrive_links = []
        for node in flow.flow_data.get("nodes", []):
            node_data = node.get("data", {})
            gdrive_links.extend(node_data.get("gdrive_links", []))

        try:
            context = {
                "flow_id": flow.id,
                "bot_id": flow.bot.id,
                "files": list(flow.uploaded_files.values_list('id', flat=True)),
                "gdrive_links": gdrive_links,
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

    def set_handoff(self, conversation_id: str, bot: Bot, active: bool):
        conversation, _ = Conversation.objects.get_or_create(
            conversation_id=conversation_id,
            bot=bot,
            defaults={"user_id": ""}
        )
        conversation.handoff_active = active
        conversation.save(update_fields=["handoff_active"])
        logger.info(f"Set handoff for {conversation_id} to {active}")
        return conversation

    def is_handoff_active(self, conversation_id: str, bot: Bot) -> bool:
        try:
            conversation = Conversation.objects.get(conversation_id=conversation_id, bot=bot)
            return conversation.handoff_active
        except Conversation.DoesNotExist:
            return False 