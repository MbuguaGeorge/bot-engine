from rest_framework import serializers
from .models import Flow, UploadedFile
from bots.models import Bot

class UploadedFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UploadedFile
        fields = ('id', 'name', 'file', 'uploaded_at', 'node_id')
        read_only_fields = ('id', 'uploaded_at', 'file')

class FlowSerializer(serializers.ModelSerializer):
    flow_data = serializers.JSONField(required=True)

    class Meta:
        model = Flow
        fields = [
            'id', 'name', 'bot', 'status', 'is_active',
            'flow_data', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'bot']

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        flow_data = instance.flow_data if isinstance(instance.flow_data, dict) else {}
        nodes = flow_data.get('nodes', [])
        
        # Get all files for the flow at once to be efficient
        files_for_flow = instance.uploaded_files.all()
        files_by_node = {}
        for file in files_for_flow:
            if file.node_id not in files_by_node:
                files_by_node[file.node_id] = []
            files_by_node[file.node_id].append({'id': str(file.id), 'name': file.name})

        # Inject files into the correct nodes
        for node in nodes:
            if node.get('type') == 'aiNode':
                node_id = node.get('id')
                if 'data' not in node:
                    node['data'] = {}
                node['data']['files'] = files_by_node.get(node_id, [])

        representation['flow_data'] = flow_data
        return representation

    def validate_name(self, value):
        bot = self.context.get('bot')
        if not bot and self.instance:
            bot = self.instance.bot
        
        if bot:
            queryset = Flow.objects.filter(bot=bot, name=value)
            if self.instance:
                queryset = queryset.exclude(pk=self.instance.pk)
            if queryset.exists():
                raise serializers.ValidationError("A flow with this name already exists for this bot.")
        return value

    def validate_status(self, value):
        if value not in ['draft', 'active', 'archived']:
            raise serializers.ValidationError("Invalid status. Must be 'draft', 'active', or 'archived'.")
        return value

    def validate_is_active(self, value):
        if not isinstance(value, bool):
            raise serializers.ValidationError("Invalid is_active format. Must be a boolean.")
        return value

    def validate_flow_data(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Invalid flow_data format. Must be a dictionary.")
        
        # Ensure nodes and edges are present
        if 'nodes' not in value or 'edges' not in value:
            raise serializers.ValidationError("flow_data must contain 'nodes' and 'edges' keys.")
            
        return value

    def validate_created_at(self, value):
        if not isinstance(value, str):
            raise serializers.ValidationError("Invalid created_at format. Must be a string.")
        return value

    def validate_updated_at(self, value):
        if not isinstance(value, str):
            raise serializers.ValidationError("Invalid updated_at format. Must be a string.")
        return value 