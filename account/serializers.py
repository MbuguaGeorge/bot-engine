from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)
    email = serializers.EmailField(required=True)
    full_name = serializers.CharField(required=True)

    class Meta:
        model = User
        fields = ('email', 'full_name', 'password', 'date_joined')

    def validate_password(self, value):
        if len(value) < 8:
            raise serializers.ValidationError("Your password must be at least 8 characters long.")
        return value

    def validate_email(self, value):
        # Only check uniqueness if email is being changed
        user = self.instance
        if user and user.email == value:
            return value
        try:
            validate_email(value)
        except ValidationError:
            raise serializers.ValidationError("Please enter a valid email address.")
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("An account with this email address already exists. Please try logging in instead.")
        return value

    def validate_full_name(self, value):
        if value is None:
            return value
        if len(value.strip()) == 0:
            raise serializers.ValidationError("Please enter your full name.")
        return value.strip()

    def validate(self, attrs):
        # Allow partial updates: don't require fields not present
        if self.instance and self.partial:
            return attrs
        return super().validate(attrs)

    def create(self, validated_data):
        user = User.objects.create_user(
            email=validated_data['email'],
            full_name=validated_data['full_name'],
            password=validated_data['password']
        )
        return user 