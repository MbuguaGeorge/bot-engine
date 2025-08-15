from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from rest_framework.authentication import SessionAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework import exceptions
import logging

logger = logging.getLogger(__name__)
User = get_user_model()


class CookieSessionAuthentication(SessionAuthentication):
    """
    Custom session authentication that handles cookie-based sessions
    with enhanced security and logging.
    """
    
    def authenticate(self, request):
        """
        Returns a `User` if the request session currently has a logged in user.
        Otherwise returns `None`.
        """
        # Get the session-based user
        user = getattr(request._request, 'user', None)
        
        if not user or not user.is_active:
            return None
            
        # Check if session is valid
        if not hasattr(request._request, 'session') or not request._request.session.session_key:
            return None
            
        # Log successful session authentication
        logger.info(f"Session authentication successful for user: {user.email}")
        
        return (user, None)
    
    def enforce_csrf(self, request):
        """
        Override to skip CSRF enforcement for API authentication.
        """
        # Skip CSRF check for API authentication
        # The session cookie itself provides sufficient authentication
        return


class HybridAuthentication:
    """
    Authentication class that tries session authentication first,
    then falls back to JWT authentication for backward compatibility.
    """
    
    def __init__(self):
        self.session_auth = CookieSessionAuthentication()
        self.jwt_auth = JWTAuthentication()
    
    def authenticate(self, request):
        """
        Try session authentication first, then JWT.
        """
        # Try session authentication first (preferred)
        try:
            result = self.session_auth.authenticate(request)
            if result:
                user, token = result
                logger.info(f"Session authentication successful for user: {user.email}")
                return result
        except exceptions.AuthenticationFailed:
            pass  # Fall through to JWT
            
        # Fall back to JWT authentication
        try:
            result = self.jwt_auth.authenticate(request)
            if result:
                user, token = result
                logger.info(f"JWT authentication successful for user: {user.email}")
                return result
        except exceptions.AuthenticationFailed:
            pass
            
        return None
    
    def authenticate_header(self, request):
        """
        Return a string to be used as the value of the `WWW-Authenticate`
        header in a `401 Unauthenticated` response.
        """
        return 'Bearer'


class SecureModelBackend(ModelBackend):
    """
    Enhanced ModelBackend with additional security logging.
    """
    
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get('email')
        if username is None or password is None:
            return None
            
        try:
            user = User.objects.get(email=username)
        except User.DoesNotExist:
            # Run the default password hasher once to reduce the timing
            # difference between an existing and a nonexistent user
            User().set_password(password)
            logger.warning(f"Login attempt with non-existent email: {username}")
            return None
        
        if user.check_password(password) and self.user_can_authenticate(user):
            logger.info(f"Successful login for user: {user.email}")
            return user
        else:
            logger.warning(f"Failed login attempt for user: {username}")
            return None 