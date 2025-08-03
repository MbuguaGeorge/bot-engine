from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.core.exceptions import ObjectDoesNotExist
import logging
import json
from .models import SupportTicket
from .serializers import (
    SupportTicketSerializer, 
    SupportTicketCreateSerializer
)

logger = logging.getLogger(__name__)

def publish_to_redis(channel, payload):
    """Publish message to Redis for real-time updates"""
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, db=0)
        r.publish(channel, json.dumps(payload))
        logger.info(f"Published to Redis channel {channel}: {payload}")
    except Exception as e:
        logger.error(f"Failed to publish to Redis: {e}")

class SupportTicketListView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get all tickets for the current user"""
        try:
            tickets = SupportTicket.objects.filter(user=request.user)
            serializer = SupportTicketSerializer(tickets, many=True)
            return Response(serializer.data)
        except Exception as e:
            logger.error(f"Error fetching tickets: {e}")
            return Response(
                {'error': 'Error fetching tickets'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def post(self, request):
        """Create a new support ticket"""
        try:
            logger.info(f"Creating ticket with data: {request.data}")
            serializer = SupportTicketCreateSerializer(data=request.data, context={'request': request})
            if serializer.is_valid():
                logger.info("Serializer is valid, saving ticket")
                ticket = serializer.save()
                logger.info(f"Ticket created successfully: {ticket.id}")
                return Response(
                    SupportTicketSerializer(ticket).data, 
                    status=status.HTTP_201_CREATED
                )
            else:
                logger.error(f"Serializer errors: {serializer.errors}")
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error creating ticket: {e}", exc_info=True)
            return Response(
                {'error': f'Error creating ticket: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class SupportTicketDetailView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get_object(self, ticket_id, user):
        """Get ticket and verify ownership"""
        try:
            ticket = SupportTicket.objects.get(id=ticket_id)
            if ticket.user != user:
                return None
            return ticket
        except SupportTicket.DoesNotExist:
            return None
    
    def get(self, request, ticket_id):
        """Get a specific ticket"""
        ticket = self.get_object(ticket_id, request.user)
        if not ticket:
            return Response({'error': 'Ticket not found'}, status=status.HTTP_404_NOT_FOUND)
        
        try:
            serializer = SupportTicketSerializer(ticket)
            return Response(serializer.data)
        except Exception as e:
            logger.error(f"Error fetching ticket: {e}")
            return Response(
                {'error': 'Error fetching ticket'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def patch(self, request, ticket_id):
        """Update a ticket (limited fields for users)"""
        ticket = self.get_object(ticket_id, request.user)
        if not ticket:
            return Response({'error': 'Ticket not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Users can only update certain fields
        allowed_fields = ['subject', 'description', 'category']
        data = {k: v for k, v in request.data.items() if k in allowed_fields}
        
        try:
            serializer = SupportTicketSerializer(ticket, data=data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error updating ticket: {e}")
            return Response(
                {'error': 'Error updating ticket'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

# SupportTicketResponseView and SupportTicketStatusView removed - responses will be handled via email
