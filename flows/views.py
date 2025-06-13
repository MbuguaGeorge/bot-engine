from django.http import Http404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from .models import Flow
from bots.models import Bot
from .serializers import FlowSerializer
from django.conf import settings
import hmac
import hashlib
import logging
from .services import FlowExecutionService
from .whatsapp import WhatsAppClient

logger = logging.getLogger(__name__)

# Create your views here.

class FlowListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request, bot_id):
        """List all flows for a specific bot"""
        bot = get_object_or_404(Bot, id=bot_id, user=request.user)
        flows = Flow.objects.filter(bot=bot)
        serializer = FlowSerializer(flows, many=True)
        return Response(serializer.data)
    
    def post(self, request, bot_id):
        """Create a new flow for a specific bot"""
        bot = get_object_or_404(Bot, id=bot_id, user=request.user)
        serializer = FlowSerializer(data=request.data, context={'bot': bot})
        if serializer.is_valid():
            serializer.save(bot=bot)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class FlowDetailView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get_object(self, pk, user):
        """Get flow object and verify ownership"""
        flow = get_object_or_404(Flow, id=pk)
        if flow.bot.user != user:
            raise Http404
        return flow
    
    def get(self, request, pk):
        """Get a specific flow"""
        flow = self.get_object(pk, request.user)
        serializer = FlowSerializer(flow)
        return Response(serializer.data)
    
    def patch(self, request, pk):
        """Update a flow partially"""
        flow = self.get_object(pk, request.user)
        serializer = FlowSerializer(flow, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def delete(self, request, pk):
        """Delete a flow"""
        flow = self.get_object(pk, request.user)
        flow.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class WhatsAppWebhookView(APIView):
    permission_classes = [AllowAny]  # WhatsApp needs to access this endpoint
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.flow_service = FlowExecutionService()
        self.whatsapp_client = WhatsAppClient()
    
    def get(self, request):
        """
        Handle the webhook verification from WhatsApp
        """
        mode = request.query_params.get('hub.mode')
        token = request.query_params.get('hub.verify_token')
        challenge = request.query_params.get('hub.challenge')
        
        if mode and token:
            if mode == 'subscribe' and token == settings.WHATSAPP_VERIFY_TOKEN:
                return Response(int(challenge))
            return Response('Invalid verify token', status=status.HTTP_403_FORBIDDEN)
        
        return Response('Invalid request', status=status.HTTP_400_BAD_REQUEST)
    
    def post(self, request):
        """
        Handle incoming messages from WhatsApp
        """
        # Verify webhook signature
        if not self._verify_webhook_signature(request):
            return Response('Invalid signature', status=status.HTTP_403_FORBIDDEN)
        
        try:
            # Extract the sender's phone number
            phone_number = self.flow_service._extract_phone_number(request.data)
            if not phone_number:
                logger.error("Could not extract phone number from webhook data")
                return Response('Invalid webhook data', status=status.HTTP_400_BAD_REQUEST)
            
            # Process the webhook and get responses
            responses = self.flow_service.process_webhook(request.data)
            
            # Send responses back to WhatsApp
            if responses:
                try:
                    self.whatsapp_client.send_messages(phone_number, responses)
                except Exception as e:
                    logger.error(f"Error sending WhatsApp messages: {str(e)}")
                    # We still return 200 to WhatsApp to acknowledge receipt
            
            return Response({'status': 'success'})
            
        except Exception as e:
            logger.error(f"Error processing webhook: {str(e)}")
            return Response('Internal server error', status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _verify_webhook_signature(self, request) -> bool:
        """
        Verify that the webhook request came from WhatsApp
        """
        signature = request.headers.get('X-Hub-Signature-256')
        if not signature:
            return False
            
        # Get the raw request body
        body = request.body
        
        # Calculate expected signature
        expected_signature = hmac.new(
            settings.WHATSAPP_APP_SECRET.encode('utf-8'),
            msg=body,
            digestmod=hashlib.sha256
        ).hexdigest()
        
        # Compare signatures
        return hmac.compare_digest(f"sha256={expected_signature}", signature)
