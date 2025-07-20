from django.shortcuts import render
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model, authenticate, update_session_auth_hash
from django.utils import timezone
from .serializers import UserSerializer

User = get_user_model()

class SignUpView(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            refresh = RefreshToken.for_user(user)

            # Start 7-day trial subscription
            from subscription.models import Subscription
            from datetime import timedelta
            if not Subscription.objects.filter(user=user).exists():
                Subscription.objects.create(
                    user=user,
                    plan=None,  # No plan assigned during trial
                    stripe_subscription_id=f"trial_{user.id}",
                    stripe_customer_id=f"trial_{user.id}",
                    status='trialing',
                    current_period_start=timezone.now(),
                    current_period_end=timezone.now() + timedelta(days=7),
                    trial_start=timezone.now(),
                    trial_end=timezone.now() + timedelta(days=7),
                )

            return Response({
                'token': str(refresh.access_token),
                'refresh': str(refresh),
                'user': UserSerializer(user).data
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')
        password = request.data.get('password')

        if not email or not password:
            return Response({
                'error': 'Please enter both your email and password to continue.'
            }, status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(email=email, password=password)

        if user:
            # Check if account is pending deletion
            if user.is_pending_deletion and user.deletion_requested_at:
                days_remaining = 60 - (timezone.now() - user.deletion_requested_at).days
                return Response({
                    'error': f'Your account is scheduled for deletion and will be permanently removed in {max(0, days_remaining)} days.'
                }, status=status.HTTP_403_FORBIDDEN)
            
            refresh = RefreshToken.for_user(user)
            return Response({
                'token': str(refresh.access_token),
                'refresh': str(refresh),
                'user': UserSerializer(user).data
            })
        
        return Response({
            'error': 'The email or password you entered is incorrect. Please try again.'
        }, status=status.HTTP_401_UNAUTHORIZED)

class CurrentUserView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)

class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        current_password = request.data.get('current_password')
        new_password = request.data.get('new_password')
        
        if not current_password or not new_password:
            return Response({'error': 'Please enter both your current password and new password.'}, status=400)
        
        if not request.user.check_password(current_password):
            return Response({'error': 'Your current password is incorrect. Please try again.'}, status=400)
        
        if len(new_password) < 8:
            return Response({'error': 'Your new password must be at least 8 characters long.'}, status=400)
        
        request.user.set_password(new_password)
        request.user.save()
        update_session_auth_hash(request, request.user)
        
        return Response({'message': 'Your password has been updated successfully!'})

class DeleteAccountView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        password = request.data.get('password')
        
        if not password:
            return Response({'error': 'Please enter your password to confirm account deletion.'}, status=400)
        
        if not request.user.check_password(password):
            return Response({'error': 'The password you entered is incorrect. Please try again.'}, status=400)
        
        # Mark account for deletion
        request.user.is_pending_deletion = True
        request.user.deletion_requested_at = timezone.now()
        request.user.save()
        
        return Response({
            'message': 'Your account has been scheduled for deletion and will be permanently removed in 60 days.',
            'deletion_date': request.user.deletion_requested_at + timezone.timedelta(days=60)
        })
