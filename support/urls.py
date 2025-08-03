from django.urls import path
from .views import SupportTicketListView, SupportTicketDetailView

urlpatterns = [
    path('tickets/', SupportTicketListView.as_view(), name='support-ticket-list'),
    path('tickets/<int:ticket_id>/', SupportTicketDetailView.as_view(), name='support-ticket-detail'),
] 