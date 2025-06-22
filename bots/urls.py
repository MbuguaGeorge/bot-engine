from django.urls import path
from .views import (
    BotListCreateView,
    BotDetailView,
    BotDuplicateView,
    BotWhatsAppToggleView
)

app_name = 'bots'

urlpatterns = [
    path('bots/', BotListCreateView.as_view(), name='bot-list'),
    path('bots/<int:pk>/', BotDetailView.as_view(), name='bot-detail'),
    path('bots/<int:pk>/duplicate/', BotDuplicateView.as_view(), name='bot-duplicate'),
    path('bots/<int:pk>/toggle-whatsapp/', BotWhatsAppToggleView.as_view(), name='bot-toggle-whatsapp'),
] 