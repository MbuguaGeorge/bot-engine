from django.urls import path
from .views import (
    SignUpView, LoginView, LogoutView, CurrentUserView, 
    ChangePasswordView, DeleteAccountView, VerifyOTPView, 
    ResendOTPView, SessionRefreshView, SessionStatusView, SessionToJWTView
)

urlpatterns = [
    path('signup/', SignUpView.as_view(), name='signup'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('verify-otp/', VerifyOTPView.as_view(), name='verify_otp'),
    path('resend-otp/', ResendOTPView.as_view(), name='resend_otp'),
    path('me/', CurrentUserView.as_view(), name='current_user'),
    path('change-password/', ChangePasswordView.as_view(), name='change_password'),
    path('delete-account/', DeleteAccountView.as_view(), name='delete_account'),
    
    # Session management endpoints
    path('session/refresh/', SessionRefreshView.as_view(), name='session_refresh'),
    path('session/status/', SessionStatusView.as_view(), name='session_status'),
    path('session/to-jwt/', SessionToJWTView.as_view(), name='session_to_jwt'),
] 