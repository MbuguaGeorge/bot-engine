from django.urls import path
from .views import (
    SubscriptionPlanListView, CurrentSubscriptionView, CreateSubscriptionView,
    CancelSubscriptionView, PaymentMethodListView, CreatePaymentMethodView,
    UpdatePaymentMethodView, InvoiceHistoryView, StripeWebhookView, BillingPortalView, UpgradeSubscriptionView
)

app_name = 'subscription'

urlpatterns = [
    path('plans/', SubscriptionPlanListView.as_view(), name='plans'),
    path('current/', CurrentSubscriptionView.as_view(), name='current'),
    path('create/', CreateSubscriptionView.as_view(), name='create'),
    path('cancel/', CancelSubscriptionView.as_view(), name='cancel'),
    path('upgrade/', UpgradeSubscriptionView.as_view(), name='upgrade'),
    path('payment-methods/', PaymentMethodListView.as_view(), name='payment-methods'),
    path('payment-methods/create/', CreatePaymentMethodView.as_view(), name='create-payment-method'),
    path('payment-methods/update/', UpdatePaymentMethodView.as_view(), name='update-payment-method'),
    path('invoices/', InvoiceHistoryView.as_view(), name='invoices'),
    path('webhook/', StripeWebhookView.as_view(), name='webhook'),
    path('billing-portal/', BillingPortalView.as_view(), name='billing-portal'),
] 