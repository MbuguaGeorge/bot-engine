from django.urls import path
from .views import (
    FlowListCreateView,
    FlowDetailView,
    WhatsAppWebhookView
)

app_name = 'flows'

urlpatterns = [
    path('bots/<int:bot_id>/flows/', FlowListCreateView.as_view(), name='flow-list'),
    path('flows/<int:pk>/', FlowDetailView.as_view(), name='flow-detail'),
    path('webhook/', WhatsAppWebhookView.as_view(), name='whatsapp-webhook'),
] 