from rest_framework import serializers
from .models import Flow
from bots.models import Bot

class FlowSerializer(serializers.ModelSerializer):
    class Meta:
        model = Flow
        fields = [
            'id',
            'name',
            'bot',
            'status',
            'is_active',
            'flow_data',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'bot']

    def validate_name(self, value):
        bot = self.context.get('bot')  # For create operation
        if not bot:
            bot = self.instance.bot if self.instance else None  # For update operation
        
        if bot:
            existing_flow = Flow.objects.filter(bot=bot, name=value)
            if self.instance:
                existing_flow = existing_flow.exclude(pk=self.instance.pk)
            if existing_flow.exists():
                raise serializers.ValidationError("A flow with this name already exists for this bot.")
        return value

    def validate(self, data):
        # Bot validation is not needed here since it's handled in the view
        return data

    def validate_status(self, value):
        if value not in ['active', 'inactive']:
            raise serializers.ValidationError("Invalid status. Must be 'active' or 'inactive'.")
        return value

    def validate_is_active(self, value):
        if value not in [True, False]:
            raise serializers.ValidationError("Invalid is_active format. Must be a boolean.")
        return value

    def validate_flow_data(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Invalid flow_data format. Must be a dictionary.")
        return value

    def validate_created_at(self, value):
        if not isinstance(value, str):
            raise serializers.ValidationError("Invalid created_at format. Must be a string.")
        return value

    def validate_updated_at(self, value):
        if not isinstance(value, str):
            raise serializers.ValidationError("Invalid updated_at format. Must be a string.")
        return value 