from typing import List, Dict, Any
import requests
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

class WhatsAppClient:
    """Client for sending messages via WhatsApp Cloud API"""
    
    BASE_URL = "https://graph.facebook.com/v23.0"
    
    def __init__(self):
        self.access_token = settings.WHATSAPP_ACCESS_TOKEN
        
    def send_message(self, to: str, phone_number_id: str, message: str) -> Dict[str, Any]:
        """
        Send a text message to a WhatsApp user
        
        Args:
            to: Recipient's phone number
            message: Message text to send
            
        Returns:
            API response data
        """
        url = f"{self.BASE_URL}/{phone_number_id}/messages"
        
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": message
            }
        }
        
        try:
            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()
            
            logger.info(f"Message sent successfully to {to}")
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending WhatsApp message to {to}: {str(e)}")
            if response := getattr(e, 'response', None):
                logger.error(f"WhatsApp API error response: {response.text}")
            raise
    
    def send_messages(self, to: str, phone_number_id: str, messages: List[str]) -> List[Dict[str, Any]]:
        """
        Send multiple messages to a WhatsApp user
        
        Args:
            to: Recipient's phone number
            messages: List of message texts to send
            
        Returns:
            List of API response data
        """
        responses = []
        
        for message in messages:
            try:
                response = self.send_message(to, phone_number_id, message)
                responses.append(response)
            except Exception as e:
                logger.error(f"Failed to send message: {str(e)}")
                # Continue sending remaining messages even if one fails
                continue
                
        return responses 