from django.urls import path
from .views import (
    FlowListCreateView,
    FlowDetailView,
    FileUploadView,
    FileDeleteView,
    WhatsAppWebhookView
)

app_name = 'flows'

urlpatterns = [
    path('bots/<int:bot_id>/flows/', FlowListCreateView.as_view(), name='flow-list'),
    path('flows/<int:pk>/', FlowDetailView.as_view(), name='flow-detail'),
    path('flows/<int:flow_id>/upload/', FileUploadView.as_view(), name='file-upload'),
    path('flows/<int:flow_id>/files/<int:file_id>/', FileDeleteView.as_view(), name='file-delete'),
    path('webhook/whatsapp/', WhatsAppWebhookView.as_view(), name='whatsapp-webhook'),
] 