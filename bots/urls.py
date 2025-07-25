from django.urls import path
from .views import (
    BotListCreateView,
    BotDetailView,
    BotDuplicateView,
    BotWhatsAppToggleView,
    GenerateSignupURLView,
    MetaCallbackView,
    WhatsAppBusinessAccountDetailView,
    BotStatsView,
    NotificationListView,
    NotificationMarkReadView,
    NotificationMarkAllReadView,
    NotificationSettingsView,
)

app_name = 'bots'

urlpatterns = [
    path('bots/', BotListCreateView.as_view(), name='bot-list'),
    path('bots/<int:pk>/', BotDetailView.as_view(), name='bot-detail'),
    path('bots/<int:pk>/duplicate/', BotDuplicateView.as_view(), name='bot-duplicate'),
    path('bots/<int:pk>/toggle-whatsapp/', BotWhatsAppToggleView.as_view(), name='bot-toggle-whatsapp'),
    path('bots/<int:bot_id>/waba/', WhatsAppBusinessAccountDetailView.as_view(), name='bot-waba-detail'),
    path('bots/stats/', BotStatsView.as_view(), name='bot-stats'),
    path('meta/generate-signup-url/<int:bot_id>/', GenerateSignupURLView.as_view(), name='generate_signup_url'),
    path('meta/callback/', MetaCallbackView.as_view(), name='meta_callback'),
    
    # Notification endpoints
    path('notifications/', NotificationListView.as_view(), name='notification-list'),
    path('notifications/<int:pk>/read/', NotificationMarkReadView.as_view(), name='notification-mark-read'),
    path('notifications/mark-all-read/', NotificationMarkAllReadView.as_view(), name='notification-mark-all-read'),
    path('notification-settings/', NotificationSettingsView.as_view(), name='notification-settings'),
]