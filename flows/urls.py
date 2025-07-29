from django.urls import path
from .views import (
    FlowListCreateView,
    FlowDetailView,
    FileUploadView,
    FileDeleteView,
    WhatsAppWebhookView,
    ConversationHandoffView,
    send_whatsapp_message,
    GoogleOAuthDeviceCodeView, GoogleOAuthTokenPollView,
    GoogleDocsLinkView, GoogleDocsListView,
    GoogleOAuthURLView, GoogleOAuthCallbackView,
    GoogleOAuthStatusView, UpsertGDriveLinkView
)

app_name = 'flows'

urlpatterns = [
    path('bots/<int:bot_id>/flows/', FlowListCreateView.as_view(), name='flow-list'),
    path('flows/<int:pk>/', FlowDetailView.as_view(), name='flow-detail'),
    path('flows/<int:flow_id>/upload/', FileUploadView.as_view(), name='file-upload'),
    path('flows/<int:flow_id>/files/<int:file_id>/', FileDeleteView.as_view(), name='file-delete'),
    path('webhook/whatsapp/', WhatsAppWebhookView.as_view(), name='whatsapp-webhook'),
    path('flows/handoff/', ConversationHandoffView.as_view(), name='conversation-handoff'),
    path('flows/send_whatsapp_message/', send_whatsapp_message, name='send-whatsapp-message'),
    path('google-oauth/device/', GoogleOAuthDeviceCodeView.as_view(), name='google_oauth_device'),
    path('google-oauth/token/', GoogleOAuthTokenPollView.as_view(), name='google_oauth_token'),
    path('google-docs/link/', GoogleDocsLinkView.as_view(), name='google_docs_link'),
    path('google-docs/list/', GoogleDocsListView.as_view(), name='google_docs_list'),
    path('google-oauth/url/', GoogleOAuthURLView.as_view(), name='google_oauth_url'),
    path('google-oauth/callback/', GoogleOAuthCallbackView.as_view(), name='google_oauth_callback'),
    path('google-oauth/status/', GoogleOAuthStatusView.as_view(), name='google_oauth_status'),
    path('upsert-gdrive-link/', UpsertGDriveLinkView.as_view(), name='upsert_gdrive_link'),
] 