from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from .models import Bot
from .serializers import BotSerializer, BotDetailSerializer

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
        serializer = BotSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
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
        bot = self.get_object(pk, request.user)
        serializer = BotDetailSerializer(bot, data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def patch(self, request, pk):
        """Partially update a bot"""
        bot = self.get_object(pk, request.user)
        serializer = BotDetailSerializer(bot, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def delete(self, request, pk):
        """Delete a bot"""
        bot = self.get_object(pk, request.user)
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
            phone_number=None  # Phone number must be set manually for the copy
        )
        serializer = BotSerializer(new_bot)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

class BotWhatsAppToggleView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request, pk):
        """Toggle WhatsApp connection status"""
        bot = get_object_or_404(Bot, pk=pk, user=request.user)
        bot.whatsapp_connected = not bot.whatsapp_connected
        bot.save()
        serializer = BotSerializer(bot)
        return Response(serializer.data)
