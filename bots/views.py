import requests
from rest_framework.views import APIView
from rest_framework.response import Response
from django.http import JsonResponse, HttpResponseRedirect
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from .models import Bot, WhatsAppBusinessAccount, Notification, NotificationSettings
from django.contrib.auth import get_user_model
from django.conf import settings
from .serializers import BotSerializer, BotDetailSerializer
from .serializers import WhatsAppBusinessAccountSerializer
from rest_framework.pagination import PageNumberPagination
from .serializers import NotificationSettingsSerializer

# Create your views here.

class BotListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """List all bots for the authenticated user"""
        bots = Bot.objects.filter(user=request.user)
        serializer = BotSerializer(bots, many=True)
        return Response(serializer.data)
    
    def post(self, request):
        """Create a new bot"""
        if not Bot.can_user_create_or_edit(request.user):
            return Response({'error': 'Your subscription has expired. Please subscribe to create a new bot.'}, status=403)
        serializer = BotSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            bot = serializer.save()
            Notification.objects.create_notification(
                user=request.user,
                bot=bot,
                type='bot_created',
                title='Bot Created',
                message=f'Bot "{bot.name}" was created.'
            )
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class BotDetailView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get_object(self, pk, user):
        return get_object_or_404(Bot, pk=pk, user=user)
    
    def get(self, request, pk):
        """Retrieve a bot"""
        bot = self.get_object(pk, request.user)
        serializer = BotDetailSerializer(bot)
        return Response(serializer.data)
    
    def put(self, request, pk):
        """Update a bot"""
        if not Bot.can_user_create_or_edit(request.user):
            return Response({'error': 'Your subscription has expired. Please subscribe to edit bots.'}, status=403)
        bot = self.get_object(pk, request.user)
        serializer = BotDetailSerializer(bot, data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def patch(self, request, pk):
        """Partially update a bot"""
        if not Bot.can_user_create_or_edit(request.user):
            return Response({'error': 'Your subscription has expired. Please subscribe to edit bots.'}, status=403)
        bot = self.get_object(pk, request.user)
        serializer = BotDetailSerializer(bot, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def delete(self, request, pk):
        """Delete a bot"""
        bot = self.get_object(pk, request.user)
        Notification.objects.create_notification(
            user=request.user,
            bot=bot,
            type='bot_deleted',
            title='Bot Deleted',
            message=f'Bot "{bot.name}" was deleted.'
        )
        bot.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class BotDuplicateView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request, pk):
        """Duplicate a bot"""
        original_bot = get_object_or_404(Bot, pk=pk, user=request.user)
        new_bot = Bot.objects.create(
            user=request.user,
            name=f"{original_bot.name} (Copy)",
            status='draft',
            flow_data=original_bot.flow_data,
            whatsapp_connected=False,
            phone_number=None
        )
        Notification.objects.create_notification(
            user=request.user,
            bot=new_bot,
            type='bot_duplicated',
            title='Bot Duplicated',
            message=f'Bot "{original_bot.name}" was duplicated.'
        )
        serializer = BotSerializer(new_bot)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

class BotWhatsAppToggleView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request, pk):
        """Toggle WhatsApp connection status"""
        bot = get_object_or_404(Bot, pk=pk, user=request.user)
        if bot.whatsapp_connected:
            try:
                waba = WhatsAppBusinessAccount.objects.get(bot=bot)
                waba.delete()
            except WhatsAppBusinessAccount.DoesNotExist:
                pass
            bot.phone_number = None
            bot.phone_number_id = None
            bot.status = 'disconnected'
            bot.whatsapp_connected = False
            bot.save()
            Notification.objects.create_notification(
                user=request.user,
                bot=bot,
                type='whatsapp_disconnected',
                title='WhatsApp Disconnected',
                message=f'WhatsApp was disconnected from bot "{bot.name}".'
            )
        serializer = BotSerializer(bot)
        return Response(serializer.data)
    

class GenerateSignupURLView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, bot_id):
        user = request.user
        redirect_uri = settings.META_REDIRECT_URI
        app_id = settings.META_APP_ID
        state = f"{user.id}:{bot_id}"

        signup_url = (
            f"https://www.facebook.com/dialog/oauth?"
            f"client_id={app_id}&"
            f"redirect_uri={redirect_uri}&"
            f"state={state}&"
            f"scope=whatsapp_business_management,whatsapp_business_messaging,business_management"
        )

        return JsonResponse({"signup_url": signup_url})
    

class MetaCallbackView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        code = request.GET.get("code")
        state = request.GET.get("state")
        redirect_uri = settings.META_REDIRECT_URI

        if not code or not state:
            return Response({"error": "Missing code or state"}, status=400)

        try:
            user_id, bot_id = state.split(":")
            user = get_user_model().objects.get(id=user_id)

            token_res = requests.get("https://graph.facebook.com/v19.0/oauth/access_token", params={
                "client_id": settings.META_APP_ID,
                "client_secret": settings.META_APP_SECRET,
                "redirect_uri": redirect_uri,
                "code": code
            })
            token_data = token_res.json()
            access_token = token_data.get("access_token")

            if not access_token:
                return Response({"error": "Failed to fetch token"}, status=400)

            business_res = requests.get("https://graph.facebook.com/v19.0/me/businesses", params={"access_token": access_token})
            business_data = business_res.json()
            businesses = business_data.get("data", [])

            if not businesses:
                return Response({"error": "No business found for this user"}, status=400)

            business_id = businesses[1]["id"]
            business_name = businesses[1]["name"]

            wa_res = requests.get(
                f"https://graph.facebook.com/v19.0/{business_id}/owned_whatsapp_business_accounts",
                params={"access_token": access_token}
            )
            wa_accounts = wa_res.json().get("data", [])
            if not wa_accounts:
                return Response({"error": "No WhatsApp Business Accounts found"}, status=400)
            wa_account = wa_accounts[0]

            if not wa_account:
                return Response({"error": "No WhatsApp business account found"}, status=400)

            whatsapp_business_id = wa_account["id"]

            phone_res = requests.get(
                f"https://graph.facebook.com/v19.0/{whatsapp_business_id}/phone_numbers",
                params={"access_token": access_token}
            )
            phone_data = phone_res.json().get("data", [])
            phone_number = phone_data[0] if phone_data else None

            if not phone_number:
                return Response({"error": "No phone number found"}, status=400)

            phone_number_id = phone_number["id"]
            display_phone_number = phone_number["display_phone_number"]

            existing = WhatsAppBusinessAccount.objects.filter(
                phone_number_id=phone_number_id
            ).exclude(user=user).first()

            if existing:
                return Response({"error": "Phone number already linked with another bot"}, status=400)

            bot = Bot.objects.get(id=bot_id, user=user)
            bot.phone_number=display_phone_number
            bot.phone_number_id=phone_number_id
            bot.status='active'
            bot.whatsapp_connected=True
            bot.save()
            
            WhatsAppBusinessAccount.objects.update_or_create(
                bot=bot,
                defaults={
                    "user": user,
                    "access_token": access_token,
                    "phone_number_id": phone_number_id,
                    "phone_number": display_phone_number,
                    "business_id": whatsapp_business_id,
                    "business_name": business_name,
                }
            )
            Notification.objects.create_notification(
                user=user,
                bot=bot,
                type='whatsapp_connected',
                title='WhatsApp Connected',
                message=f'WhatsApp was connected to bot "{bot.name}".'
            )
            return HttpResponseRedirect(f"{settings.FRONTEND_URL}/dashboard")

        except Exception as e:
            return Response({"error": str(e)}, status=500)

class WhatsAppBusinessAccountDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, bot_id):
        bot = get_object_or_404(Bot, id=bot_id, user=request.user)
        try:
            waba = WhatsAppBusinessAccount.objects.get(bot=bot)
            serializer = WhatsAppBusinessAccountSerializer(waba)
            return Response(serializer.data)
        except WhatsAppBusinessAccount.DoesNotExist:
            return Response({'detail': 'No WhatsApp Business Account found for this bot.'}, status=404)

class BotStatsView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        total_bots = Bot.objects.filter(user=request.user).count()
        active_bots = Bot.objects.filter(user=request.user, status='active').count()
        return Response({
            'total_bots': total_bots,
            'active_bots': active_bots
        })

class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        unread = request.query_params.get('unread')
        qs = Notification.objects.filter(user=request.user)
        if unread == 'true':
            qs = qs.filter(is_read=False)
        elif unread == 'false':
            qs = qs.filter(is_read=True)
        qs = qs.order_by('-created_at')
        paginator = PageNumberPagination()
        paginator.page_size = int(request.query_params.get('page_size', 20))
        result_page = paginator.paginate_queryset(qs, request)
        data = [
            {
                'id': n.id,
                'type': n.type,
                'title': n.title,
                'message': n.message,
                'is_read': n.is_read,
                'created_at': n.created_at,
                'bot_id': n.bot.id if n.bot else None,
                'data': n.data,
            }
            for n in result_page
        ]
        return paginator.get_paginated_response(data)

class NotificationMarkReadView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request, pk):
        try:
            notification = Notification.objects.get(id=pk, user=request.user)
        except Notification.DoesNotExist:
            return Response({'error': 'Notification not found'}, status=404)
        is_read = request.data.get('is_read', True)
        notification.is_read = is_read
        notification.save()
        Notification.objects.publish_mark_read(notification)
        return Response({'success': True, 'id': notification.id, 'is_read': notification.is_read})

class NotificationMarkAllReadView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        notifications = Notification.objects.filter(user=request.user, is_read=False)
        notifications.update(is_read=True)
        # Publish for each notification
        for n in notifications:
            Notification.objects.publish_mark_read(n)
        return Response({'success': True})

class NotificationSettingsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        settings, _ = NotificationSettings.objects.get_or_create(user=request.user)
        serializer = NotificationSettingsSerializer(settings)
        return Response(serializer.data)

    def put(self, request):
        settings, _ = NotificationSettings.objects.get_or_create(user=request.user)
        serializer = NotificationSettingsSerializer(settings, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request):
        settings, _ = NotificationSettings.objects.get_or_create(user=request.user)
        serializer = NotificationSettingsSerializer(settings, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)