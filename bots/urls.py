from django.urls import path
from .views import (
    BotListCreateView,
    BotDetailView,
    BotDuplicateView,
    BotWhatsAppToggleView
)

app_name = 'bots'

urlpatterns = [
    path('', BotListCreateView.as_view(), name='bot-list'),
    path('<int:pk>/', BotDetailView.as_view(), name='bot-detail'),
    path('<int:pk>/duplicate/', BotDuplicateView.as_view(), name='bot-duplicate'),
    path('<int:pk>/toggle-whatsapp/', BotWhatsAppToggleView.as_view(), name='bot-toggle-whatsapp'),
] 