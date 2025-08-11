from django.shortcuts import render
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model, authenticate, update_session_auth_hash
from django.utils import timezone
from .serializers import UserSerializer
from bots.services import NotificationService, NOTIFICATION_EVENT_TYPES
from email_templates.email_service import EmailService
from .services import OTPService
import logging

logger = logging.getLogger(__name__)

User = get_user_model()

class SignUpView(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            # First, validate the email using Abstract API
            user_data = serializer.validated_data
            test_email = user_data.get('email')
            
            # Validate email address BEFORE creating user
            email_service = EmailService()
            try:
                # Validate email address using Abstract API
                email_valid = email_service.validate_email_address(test_email)
                if not email_valid:
                    logger.warning(f"Email validation failed for {test_email} - preventing user creation")
                    return Response({
                        'error': 'Please enter a valid email address. The email address you provided appears to be invalid or cannot receive emails.'
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                logger.info(f"Email validation successful for {test_email}, proceeding with user creation")
            except Exception as e:
                logger.error(f"Exception during email validation for {test_email}: {str(e)}")
                return Response({
                    'error': 'Unable to validate email address. Please check your email and try again.'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # If email validation passes, create the user (inactive by default)
            user = serializer.save()
            
            # Create and send OTP
            otp = OTPService.create_otp_for_user(user)
            if not otp:
                # Delete the user if OTP creation fails
                user.delete()
                return Response({
                    'error': 'Failed to create verification code. Please try again.'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            # Send OTP email
            try:
                success = email_service.send_otp_email(user, otp.code)
                if not success:
                    # Delete the user if OTP email fails
                    user.delete()
                    otp.delete()
                    return Response({
                        'error': 'Failed to send verification email. Please check your email address and try again.'
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
                logger.info(f"OTP email sent successfully to {user.email}")
            except Exception as e:
                # Delete the user if OTP email fails
                user.delete()
                otp.delete()
                logger.error(f"Exception sending OTP email to {user.email}: {str(e)}")
                return Response({
                    'error': 'Failed to send verification email. Please try again later.'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            return Response({
                'message': 'Account created successfully! Please check your email for verification code.',
                'user_id': user.id,
                'email': user.email
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class VerifyOTPView(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        email = request.data.get('email')
        otp_code = request.data.get('otp_code')
        
        if not email or not otp_code:
            return Response({
                'error': 'Please provide both email and verification code.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({
                'error': 'No account found with this email address.'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Check if user is already verified
        if user.email_verified:
            return Response({
                'error': 'Email is already verified.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Verify OTP
        is_valid, message = OTPService.verify_otp(user, otp_code)
        
        if is_valid:
            # Activate user account
            user.is_active = True
            user.email_verified = True
            user.save()
            
            # Start 14-day trial subscription
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
                    current_period_end=timezone.now() + timedelta(days=14),
                    trial_start=timezone.now(),
                    trial_end=timezone.now() + timedelta(days=14),
                )
            
            # Send welcome email
            email_service = EmailService()
            try:
                success = email_service.send_welcome_email(user)
                if success:
                    logger.info(f"Welcome email sent successfully to {user.email}")
                else:
                    logger.error(f"Failed to send welcome email to {user.email} after verification")
            except Exception as e:
                logger.error(f"Exception sending welcome email to {user.email}: {str(e)}")
            
            # Generate tokens for immediate login
            refresh = RefreshToken.for_user(user)
            
            return Response({
                'message': 'Email verified successfully! Welcome to Wozza!',
                'token': str(refresh.access_token),
                'refresh': str(refresh),
                'user': UserSerializer(user).data
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                'error': message
            }, status=status.HTTP_400_BAD_REQUEST)

class ResendOTPView(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        email = request.data.get('email')
        
        if not email:
            return Response({
                'error': 'Please provide your email address.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({
                'error': 'No account found with this email address.'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Check if user is already verified
        if user.email_verified:
            return Response({
                'error': 'Email is already verified.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if user can resend OTP (no email validation needed here)
        can_resend, message = OTPService.can_resend_otp(user)
        if not can_resend:
            return Response({
                'error': message
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)
        
        # Resend OTP
        success, message = OTPService.resend_otp(user)
        if success:
            # Get the new OTP and send email
            otp = user.otps.first()
            if otp:
                email_service = EmailService()
                email_sent = email_service.send_otp_email(user, otp.code)
                if email_sent:
                    return Response({
                        'message': 'New verification code sent successfully!'
                    }, status=status.HTTP_200_OK)
                else:
                    return Response({
                        'error': 'Failed to send verification email. Please try again.'
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            else:
                return Response({
                    'error': 'Failed to generate new verification code. Please try again.'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            return Response({
                'error': message
            }, status=status.HTTP_400_BAD_REQUEST)

class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')
        password = request.data.get('password')

        if not email or not password:
            return Response({
                'error': 'Please enter both your email and password to continue.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # First, check if the email exists in our system
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({
                'error': 'No account found with this email address. Please check your email or sign up for a new account.'
            }, status=status.HTTP_404_NOT_FOUND)

        # Check if account is pending deletion
        if user.is_pending_deletion and user.deletion_requested_at:
            days_remaining = 60 - (timezone.now() - user.deletion_requested_at).days
            return Response({
                'error': f'Your account is scheduled for deletion and will be permanently removed in {max(0, days_remaining)} days.'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Check if email is verified before attempting authentication
        if not user.email_verified:
            return Response({
                'error': 'Please check your email for the verification code to complete your registration.',
                'email_not_verified': True,
                'email': user.email
            }, status=status.HTTP_403_FORBIDDEN)

        # Now attempt authentication
        authenticated_user = authenticate(email=email, password=password)

        if authenticated_user:
            refresh = RefreshToken.for_user(authenticated_user)
            return Response({
                'token': str(refresh.access_token),
                'refresh': str(refresh),
                'user': UserSerializer(authenticated_user).data
            })
        
        return Response({
            'error': 'The password you entered is incorrect. Please try again.'
        }, status=status.HTTP_401_UNAUTHORIZED)

class CurrentUserView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

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
        # Trigger notification
        NotificationService.create_and_send(
            user=request.user,
            type="password_change",
            title="Password Changed",
            message="Your password was changed successfully.",
        )
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
        # Trigger notification
        NotificationService.create_and_send(
            user=request.user,
            type="account_deletion_requested",
            title="Account Deletion Requested",
            message="Your account has been scheduled for deletion in 60 days.",
        )
        return Response({
            'message': 'Your account has been scheduled for deletion and will be permanently removed in 60 days.',
            'deletion_date': request.user.deletion_requested_at + timezone.timedelta(days=60)
        })
