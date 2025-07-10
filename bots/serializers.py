from rest_framework import serializers
from .models import Bot
from flows.models import Flow
from bots.models import WhatsAppBusinessAccount

class BotSerializer(serializers.ModelSerializer):
    flows = serializers.SerializerMethodField()
    activeFlow = serializers.SerializerMethodField()

    class Meta:
        model = Bot
        fields = [
            'id',
            'name',
            'phone_number',
            'status',
            'whatsapp_connected',
            'created_at',
            'last_updated',
            'flows',
            'activeFlow',
        ]
        read_only_fields = ['id', 'created_at', 'last_updated']

    def get_flows(self, obj):
        return [
            {
                'id': str(flow.id),
                'name': flow.name,
                'status': flow.status,
                'is_active': flow.is_active,
            }
            for flow in obj.flows.all().order_by('-updated_at')
        ]

    def get_activeFlow(self, obj):
        flow = obj.flows.filter(is_active=True).first()
        if flow:
            return {'id': str(flow.id), 'name': flow.name}
        return None

    def validate_name(self, value):
        user = self.context['request'].user
        if Bot.objects.filter(user=user, name=value).exists():
            if self.instance and self.instance.name == value:
                return value
            raise serializers.ValidationError("You already have a bot with this name.")
        return value

    def validate_phone_number(self, value):
        if value is None or value.strip() == '':
            return None
            
        # Remove any spaces or special characters except +
        cleaned_number = ''.join(c for c in value if c.isdigit() or c == '+')
        
        # Ensure it starts with +
        if not cleaned_number.startswith('+'):
            raise serializers.ValidationError("Phone number must be in international format starting with +")
        
        # Check if phone number is already in use
        if Bot.objects.filter(phone_number=cleaned_number).exists():
            if self.instance and self.instance.phone_number == cleaned_number:
                return cleaned_number
            raise serializers.ValidationError("This phone number is already in use.")
        
        return cleaned_number

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)

class BotDetailSerializer(BotSerializer):
    class Meta(BotSerializer.Meta):
        fields = BotSerializer.Meta.fields

    def get_flows(self, obj):
        return [
            {
                'id': str(flow.id),
                'name': flow.name,
                'status': flow.status,
                'is_active': flow.is_active,
            }
            for flow in obj.flows.all().order_by('-updated_at')
        ]

    def get_activeFlow(self, obj):
        flow = obj.flows.filter(is_active=True).first()
        if flow:
            return {'id': str(flow.id), 'name': flow.name}
        return None

class WhatsAppBusinessAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = WhatsAppBusinessAccount
        fields = [
            'id', 'bot', 'user', 'business_id', 'business_name', 'access_token', 'phone_number_id', 'phone_number', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'user']