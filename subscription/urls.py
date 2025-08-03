from django.urls import path
from .views import (
    SubscriptionPlanListView, CurrentSubscriptionView, CreateSubscriptionView,
    CancelSubscriptionView, PaymentMethodListView, CreatePaymentMethodView,
    UpdatePaymentMethodView, InvoiceHistoryView, UpgradeSubscriptionView,
    StripeWebhookView, BillingPortalView,
    CreditBalanceView, CreditUsageView, CreditUsageLogView,
    AdminCreditAdjustmentView, AdminCreditUsageView
)

app_name = 'subscription'

urlpatterns = [
    # Existing subscription URLs
    path('plans/', SubscriptionPlanListView.as_view(), name='subscription-plans'),
    path('current/', CurrentSubscriptionView.as_view(), name='current-subscription'),
    path('create/', CreateSubscriptionView.as_view(), name='create-subscription'),
    path('cancel/', CancelSubscriptionView.as_view(), name='cancel-subscription'),
    path('payment-methods/', PaymentMethodListView.as_view(), name='payment-methods'),
    path('payment-methods/create/', CreatePaymentMethodView.as_view(), name='create-payment-method'),
    path('payment-methods/update/', UpdatePaymentMethodView.as_view(), name='update-payment-method'),
    path('invoices/', InvoiceHistoryView.as_view(), name='invoice-history'),
    path('upgrade/', UpgradeSubscriptionView.as_view(), name='upgrade-subscription'),
    path('webhook/', StripeWebhookView.as_view(), name='stripe-webhook'),
    path('billing-portal/', BillingPortalView.as_view(), name='billing-portal'),
    
    # Credit system URLs
    path('credits/balance/', CreditBalanceView.as_view(), name='credit-balance'),
    path('credits/usage/', CreditUsageView.as_view(), name='credit-usage'),
    path('credits/logs/', CreditUsageLogView.as_view(), name='credit-usage-logs'),
    path('credits/admin/adjust/', AdminCreditAdjustmentView.as_view(), name='admin-credit-adjustment'),
    path('credits/admin/usage/', AdminCreditUsageView.as_view(), name='admin-credit-usage'),
] 