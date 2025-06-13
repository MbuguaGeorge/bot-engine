from rest_framework import serializers
from .models import Bot

class BotSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bot
        fields = [
            'id',
            'name',
            'phone_number',
            'status',
            'flow_data',
            'whatsapp_connected',
            'created_at',
            'last_updated'
        ]
        read_only_fields = ['id', 'created_at', 'last_updated']

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
        fields = BotSerializer.Meta.fields + ['flow_data'] 