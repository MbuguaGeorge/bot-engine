from django.urls import path
from .views import LoginView, SignUpView, CurrentUserView, ChangePasswordView

app_name = 'account'

urlpatterns = [
    path('signup/', SignUpView.as_view(), name='signup'),
    path('login/', LoginView.as_view(), name='login'),
    path('users/me/', CurrentUserView.as_view(), name='current-user'),
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),
] 