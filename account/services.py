import pyotp
import logging
from django.utils import timezone
from datetime import timedelta
from .models import OTP, User

logger = logging.getLogger(__name__)

class OTPService:
    @staticmethod
    def generate_otp():
        """Generate a 6-digit OTP"""
        return pyotp.random_base32()[:6].upper()
    
    @staticmethod
    def create_otp_for_user(user):
        """Create a new OTP for a user"""
        try:
            # Delete any existing unused OTPs for this user
            OTP.objects.filter(user=user, is_used=False).delete()
            
            # Generate new OTP
            otp_code = OTPService.generate_otp()
            expires_at = timezone.now() + timedelta(minutes=5)
            
            # Create OTP record
            otp = OTP.objects.create(
                user=user,
                code=otp_code,
                expires_at=expires_at
            )
            
            logger.info(f"OTP created for user {user.email}: {otp_code}")
            return otp
            
        except Exception as e:
            logger.error(f"Error creating OTP for user {user.email}: {str(e)}")
            return None
    
    @staticmethod
    def verify_otp(user, otp_code):
        """Verify OTP for a user"""
        try:
            # Get the most recent unused OTP for this user
            otp = OTP.objects.filter(
                user=user,
                is_used=False
            ).first()
            
            if not otp:
                logger.warning(f"No OTP found for user {user.email}")
                return False, "No verification code found. Please request a new one."
            
            # Check if OTP is expired
            if otp.is_expired():
                logger.warning(f"OTP expired for user {user.email}")
                return False, "Verification code has expired. Please request a new one."
            
            # Check if OTP code matches
            if otp.code != otp_code.upper():
                logger.warning(f"Invalid OTP code for user {user.email}")
                return False, "Invalid verification code. Please check and try again."
            
            # Mark OTP as used
            otp.mark_as_used()
            
            logger.info(f"OTP verified successfully for user {user.email}")
            return True, "Email verified successfully!"
            
        except Exception as e:
            logger.error(f"Error verifying OTP for user {user.email}: {str(e)}")
            return False, "An error occurred during verification. Please try again."
    
    @staticmethod
    def can_resend_otp(user):
        """Check if user can request a new OTP"""
        try:
            # Get the most recent OTP for this user
            otp = OTP.objects.filter(user=user).first()
            
            if not otp:
                return True, "No previous OTP found"
            
            # Check if user has exceeded resend limit
            if not otp.can_resend():
                return False, "Maximum resend attempts reached. Please wait before requesting another code."
            
            # Check if enough time has passed since last OTP (1 minute cooldown)
            time_since_last = timezone.now() - otp.created_at
            if time_since_last < timedelta(minutes=1):
                remaining_seconds = 60 - int(time_since_last.total_seconds())
                return False, f"Please wait {remaining_seconds} seconds before requesting another code."
            
            return True, "Can resend OTP"
            
        except Exception as e:
            logger.error(f"Error checking resend eligibility for user {user.email}: {str(e)}")
            return False, "An error occurred. Please try again."
    
    @staticmethod
    def resend_otp(user):
        """Resend OTP to user"""
        try:
            # Check if user can resend
            can_resend, message = OTPService.can_resend_otp(user)
            if not can_resend:
                return False, message
            
            # Get the most recent OTP
            otp = OTP.objects.filter(user=user).first()
            if otp:
                # Increment resend count
                otp.increment_resend_count()
            
            # Create new OTP
            new_otp = OTPService.create_otp_for_user(user)
            if not new_otp:
                return False, "Failed to generate new verification code. Please try again."
            
            logger.info(f"OTP resent to user {user.email}")
            return True, "New verification code sent successfully!"
            
        except Exception as e:
            logger.error(f"Error resending OTP to user {user.email}: {str(e)}")
            return False, "An error occurred while sending the verification code. Please try again." 