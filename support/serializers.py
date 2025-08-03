from rest_framework import serializers
from .models import SupportTicket, SupportTicketAttachment

class SupportTicketAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportTicketAttachment
        fields = ['id', 'file', 'filename', 'uploaded_at']
        read_only_fields = ['id', 'uploaded_at']

class SupportTicketSerializer(serializers.ModelSerializer):
    attachments = SupportTicketAttachmentSerializer(many=True, read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    user_full_name = serializers.CharField(source='user.full_name', read_only=True)
    assigned_to_email = serializers.CharField(source='assigned_to.email', read_only=True)
    assigned_to_full_name = serializers.CharField(source='assigned_to.full_name', read_only=True)
    
    class Meta:
        model = SupportTicket
        fields = [
            'id', 'user', 'user_email', 'user_full_name',
            'subject', 'description', 'category', 'status',
            'created_at', 'updated_at', 'resolved_at',
            'assigned_to', 'assigned_to_email', 'assigned_to_full_name',
            'internal_notes', 'attachments'
        ]
        read_only_fields = [
            'id', 'user', 'user_email', 'user_full_name',
            'created_at', 'updated_at', 'resolved_at',
            'assigned_to', 'assigned_to_email', 'assigned_to_full_name',
            'internal_notes', 'attachments'
        ]
    
    def validate_category(self, value):
        valid_categories = [choice[0] for choice in SupportTicket.CATEGORY_CHOICES]
        if value not in valid_categories:
            raise serializers.ValidationError("Invalid category")
        return value

class SupportTicketCreateSerializer(serializers.ModelSerializer):
    attachments = serializers.ListField(
        child=serializers.FileField(),
        required=False
    )
    
    class Meta:
        model = SupportTicket
        fields = ['subject', 'description', 'category', 'attachments']
    
    def create(self, validated_data):
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"Creating ticket with validated_data: {validated_data}")
        
        attachments_data = validated_data.pop('attachments', [])
        user = self.context['request'].user
        
        logger.info(f"User: {user.email}")
        logger.info(f"Attachments: {len(attachments_data)} files")
        
        try:
            # Create the ticket
            ticket = SupportTicket.objects.create(user=user, **validated_data)
            logger.info(f"Ticket created with ID: {ticket.id}")
            
            # Create attachments
            for attachment_file in attachments_data:
                SupportTicketAttachment.objects.create(
                    ticket=ticket,
                    file=attachment_file,
                    filename=attachment_file.name
                )
                logger.info(f"Attachment created: {attachment_file.name}")
            
            return ticket
        except Exception as e:
            logger.error(f"Error in ticket creation: {e}", exc_info=True)
            raise

# SupportTicketResponseCreateSerializer removed - responses will be handled via email 