from django.http import Http404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from .models import Flow, UploadedFile, Conversation
from bots.models import Bot
from .serializers import FlowSerializer
from django.conf import settings
import redis, json
import hmac
import hashlib
import logging
from .services import FlowExecutionService
from .whatsapp import WhatsAppClient
from .serializers import UploadedFileSerializer
from Engines.rag_engine.tasks import upsert_pdf_to_pinecone, delete_pdf_from_pinecone, upsert_gdrive_links_to_pinecone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from .whatsapp import WhatsAppClient
from .models import Conversation
from bots.models import Bot
from Engines.rag_engine.utils import (
    get_google_oauth_url, poll_for_token, store_google_token,
    validate_google_file_access, list_user_google_files
)
from flows.models import GoogleUserFile
from django.shortcuts import redirect
from django.http import HttpResponse
from urllib.parse import urlencode
import requests
from flows.models import GoogleOAuthToken
from django.utils import timezone

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

class FileUploadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, flow_id):
        from bots.models import Bot
        if not Bot.can_user_create_or_edit(request.user):
            return Response({'error': 'Your subscription has expired. Please subscribe to edit bot flows.'}, status=403)
        try:
            flow = Flow.objects.get(pk=flow_id, bot__user=request.user)
        except Flow.DoesNotExist:
            return Response({'error': 'Flow not found'}, status=status.HTTP_404_NOT_FOUND)
        files = request.FILES.getlist('file')
        node_id = request.data.get('node_id')
        if not node_id:
            return Response({'error': 'node_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        if not files:
            return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)
        uploaded_file_objects = []
        for f in files:
            uploaded_file = UploadedFile.objects.create(flow=flow, file=f, name=f.name, node_id=node_id)
            uploaded_file_objects.append(uploaded_file)
            ext = f.name.split('.')[-1].lower()
            if ext == 'pdf':
                upsert_pdf_to_pinecone.delay(
                    file_id=uploaded_file.id,
                    user_id=flow.bot.user.id,
                    bot_id=flow.bot.id,
                    flow_id=flow.id,
                    node_id=node_id
                )
        serializer = UploadedFileSerializer(uploaded_file_objects, many=True)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

class FileDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, flow_id, file_id):
        flow = get_object_or_404(Flow, id=flow_id, bot__user=request.user)
        file_instance = get_object_or_404(UploadedFile, id=file_id, flow=flow)

        # delete from pinecone
        delete_pdf_from_pinecone.delay(
            file_id=file_id,
            user_id=flow.bot.user.id,
            bot_id=flow.bot.id,
            flow_id=flow.id,
            node_id=file_instance.node_id
        )
        
        file_instance.delete()
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
            entry = request.data.get("entry", [])[0]
            changes = entry.get("changes", [])[0]
            value = changes.get("value", {})
            
            if "messages" not in value:
                return Response({'status': 'ignored (not a message event)'}, status=200)
    
            phone_number = self.flow_service._extract_phone_number(request.data)
            phone_number_id = self.flow_service._extract_phone_number_id(request.data)
            
            if not phone_number:
                logger.error("Could not extract phone number from webhook data")
                return Response('Invalid webhook data', status=status.HTTP_400_BAD_REQUEST)
            
            responses = self.flow_service.process_webhook(request.data)
            
            if responses:
                try:
                    self.whatsapp_client.send_messages(phone_number, phone_number_id, responses)
                except Exception as e:
                    logger.error(f"Error sending WhatsApp messages: {str(e)}")
            
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

class ConversationHandoffView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Set handoff status for a conversation (enable/disable handoff)"""
        conversation_id = request.data.get('conversation_id')
        bot_id = request.data.get('bot_id')
        active = request.data.get('active')
        if not conversation_id or not bot_id or active is None:
            return Response({'error': 'conversation_id, bot_id, and active are required'}, status=400)
        try:
            bot = Bot.objects.get(id=bot_id, user=request.user)
        except Bot.DoesNotExist:
            return Response({'error': 'Bot not found'}, status=404)
        FlowExecutionService().set_handoff(conversation_id, bot, bool(active))
        return Response({'success': True, 'handoff_active': bool(active)})

    def get(self, request):
        """Get handoff status for a conversation"""
        conversation_id = request.query_params.get('conversation_id')
        bot_id = request.query_params.get('bot_id')
        if not conversation_id or not bot_id:
            return Response({'error': 'conversation_id and bot_id are required'}, status=400)
        try:
            bot = Bot.objects.get(id=bot_id, user=request.user)
        except Bot.DoesNotExist:
            return Response({'error': 'Bot not found'}, status=404)
        active = FlowExecutionService().is_handoff_active(conversation_id, bot)
        return Response({'handoff_active': active})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_whatsapp_message(request):
    conversation_id = request.data.get('conversation_id')
    bot_id = request.data.get('bot_id')
    message = request.data.get('message')
    if not conversation_id or not bot_id or not message:
        return Response({'error': 'conversation_id, bot_id, and message are required'}, status=400)
    try:
        bot = Bot.objects.get(id=bot_id, user=request.user)
    except Bot.DoesNotExist:
        return Response({'error': 'Bot not found'}, status=404)
    
    try:
        conversation = Conversation.objects.get(conversation_id=conversation_id, bot=bot)
    except Conversation.DoesNotExist:
        return Response({'error': 'Conversation not found'}, status=404)
    phone_number = request.data.get('user_id') or conversation.user_id
    phone_number_id = bot.phone_number_id
    if not phone_number or not phone_number_id:
        return Response({'error': 'Bot or conversation missing WhatsApp phone number info'}, status=400)
    try:
        client = WhatsAppClient()
        resp = client.send_message(phone_number, phone_number_id, message)
        # After sending, publish to Redis for Node.js chat storage
        try:
            redis_url = getattr(settings, 'REDIS_URL', 'redis://localhost:6379/0')
            redis_client = redis.Redis.from_url(redis_url)
            msg_data = {
                "conversation_id": conversation_id,
                "bot_id": str(bot_id),
                "message": {
                    "sender": "agent",
                    "from": phone_number,
                    "content": message,
                    "type": "text",
                    "status": "sent",
                    "timestamp": __import__('datetime').datetime.utcnow().isoformat() + 'Z',
                }
            }
            redis_client.publish(f"chat_message_{bot_id}", json.dumps(msg_data))
        except Exception as re:
            logger.error(f"Redis publish error (agent message): {re}")
        return Response({'success': True, 'whatsapp_response': resp})
    except Exception as e:
        return Response({'error': str(e)}, status=500)

class GoogleOAuthDeviceCodeView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request):
        data = get_google_oauth_url()
        return Response(data)

class GoogleOAuthTokenPollView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request):
        device_code = request.data.get('device_code')
        if not device_code:
            return Response({'error': 'device_code required'}, status=400)
        token_data = poll_for_token(device_code)
        if token_data and 'access_token' in token_data:
            store_google_token(request.user, token_data)
            return Response({'success': True})
        return Response({'error': 'Authorization pending or failed'}, status=400)

class GoogleDocsLinkView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request):
        link = request.data.get('link')
        if not link:
            return Response({'error': 'link required'}, status=400)
        ok, msg = validate_google_file_access(request.user, link)
        if ok:
            return Response({'success': True, 'message': msg})
        return Response({'error': msg}, status=400)

class GoogleDocsListView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        files = list_user_google_files(request.user)
        return Response({'files': files})

class GoogleOAuthURLView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        # redirect_uri = request.build_absolute_uri('/api/google-oauth/callback/')
        redirect_uri = 'https://151e6095e0a2.ngrok-free.app/api/google-oauth/callback/'
        params = {
            'client_id': settings.GOOGLE_CLIENT_ID,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': ' '.join([
                'https://www.googleapis.com/auth/drive.readonly',
                'https://www.googleapis.com/auth/documents.readonly',
                'https://www.googleapis.com/auth/spreadsheets.readonly',
            ]),
            'access_type': 'offline',
            'prompt': 'consent',
            'state': str(request.user.id),
        }
        url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(params)
        return Response({'url': url})

class GoogleOAuthCallbackView(APIView):
    permission_classes = []  # No auth, Google will redirect here
    def get(self, request):
        code = request.GET.get('code')
        state = request.GET.get('state')
        error = request.GET.get('error')
        if error:
            return HttpResponse('<script>window.opener.postMessage({type:"google_oauth_error",error:"%s"}, "*");window.close();</script>' % error)
        if not code or not state:
            return HttpResponse('<script>window.opener.postMessage({type:"google_oauth_error",error:"Missing code or state"}, "*");window.close();</script>')
        # Exchange code for tokens
        redirect_uri = 'https://151e6095e0a2.ngrok-free.app/api/google-oauth/callback/'
        data = {
            'code': code,
            'client_id': settings.GOOGLE_CLIENT_ID,
            'client_secret': settings.GOOGLE_CLIENT_SECRET,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code',
        }
        token_resp = requests.post('https://oauth2.googleapis.com/token', data=data)
        if token_resp.status_code != 200:
            return HttpResponse('<script>window.opener.postMessage({type:"google_oauth_error",error:"Token exchange failed"}, "*");window.close();</script>')
        token_data = token_resp.json()
        # Save all relevant info to GoogleOAuthToken
        import datetime
        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            user = User.objects.get(id=state)
        except User.DoesNotExist:
            return HttpResponse('<script>window.opener.postMessage({type:"google_oauth_error",error:"User not found"}, "*");window.close();</script>')
        expires_in = token_data.get('expires_in', 3600)
        expires_at = timezone.now() + datetime.timedelta(seconds=expires_in)
        GoogleOAuthToken.objects.update_or_create(
            user=user,
            defaults={
                'access_token': token_data.get('access_token', ''),
                'refresh_token': token_data.get('refresh_token', ''),
                'expires_at': expires_at,
                'scope': token_data.get('scope', ''),
                'token_type': token_data.get('token_type', ''),
            }
        )
        return HttpResponse("""
            <script>
            try {
                window.opener.postMessage({type:"google_oauth_success"}, "*");
            } catch(e) {}
            window.close();
            setTimeout(function() {
                window.open("about:blank", "_self");
                window.close();
            }, 200);
            </script>
        """)


class GoogleOAuthStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            token_obj = GoogleOAuthToken.objects.get(user=request.user)
        except GoogleOAuthToken.DoesNotExist:
            return Response({'authorized': False, 'token': None})

        # Check if token is expired
        if token_obj.expires_at <= timezone.now():
            # Try to refresh the token
            refresh_data = {
                'client_id': settings.GOOGLE_CLIENT_ID,
                'client_secret': settings.GOOGLE_CLIENT_SECRET,
                'refresh_token': token_obj.refresh_token,
                'grant_type': 'refresh_token',
            }
            resp = requests.post('https://oauth2.googleapis.com/token', data=refresh_data)
            if resp.status_code == 200:
                token_data = resp.json()
                token_obj.access_token = token_data.get('access_token', '')
                expires_in = token_data.get('expires_in', 3600)
                token_obj.expires_at = timezone.now() + timezone.timedelta(seconds=expires_in)
                token_obj.save()
            else:
                return Response({'authorized': False, 'token': None, 'error': 'Failed to refresh token'})

        return Response({
            'authorized': True,
            'token': {
                'access_token': token_obj.access_token,
                'expires_at': token_obj.expires_at,
                'scope': token_obj.scope,
                'token_type': token_obj.token_type,
            }
        })


class UpsertGDriveLinkView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        link = request.data.get('link')
        flow_id = request.data.get('flow_id')
        if not link or not flow_id:
            return Response({'error': 'Missing link or flow_id'}, status=400)
        try:
            flow = Flow.objects.get(id=flow_id)
        except Flow.DoesNotExist:
            return Response({'error': 'Flow not found'}, status=404)
        upsert_gdrive_links_to_pinecone(request.user, flow.id, link)
        return Response({'status': 'upsert triggered'})