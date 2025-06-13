from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model

User = get_user_model()

class AuthenticationTests(APITestCase):
    def setUp(self):
        self.signup_url = reverse('account:signup')
        self.login_url = reverse('account:login')
        self.user_data = {
            'email': 'test@example.com',
            'password': 'testpass123',
            'full_name': 'Test User'
        }
        
    def test_user_signup(self):
        response = self.client.post(self.signup_url, self.user_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('token', response.data)
        self.assertTrue(User.objects.filter(email=self.user_data['email']).exists())
        
    def test_user_signup_invalid_data(self):
        # Test without email
        invalid_data = self.user_data.copy()
        del invalid_data['email']
        response = self.client.post(self.signup_url, invalid_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
        # Test with invalid email
        invalid_data = self.user_data.copy()
        invalid_data['email'] = 'invalid-email'
        response = self.client.post(self.signup_url, invalid_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
        # Test with short password
        invalid_data = self.user_data.copy()
        invalid_data['password'] = '123'
        response = self.client.post(self.signup_url, invalid_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
    def test_user_login(self):
        # Create a user first
        User.objects.create_user(
            email=self.user_data['email'],
            password=self.user_data['password'],
            full_name=self.user_data['full_name']
        )
        
        # Try logging in
        login_data = {
            'email': self.user_data['email'],
            'password': self.user_data['password']
        }
        response = self.client.post(self.login_url, login_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('token', response.data)
        
    def test_user_login_invalid_credentials(self):
        # Try logging in with non-existent user
        login_data = {
            'email': 'nonexistent@example.com',
            'password': 'wrongpass123'
        }
        response = self.client.post(self.login_url, login_data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        
        # Create a user and try wrong password
        User.objects.create_user(
            email=self.user_data['email'],
            password=self.user_data['password'],
            full_name=self.user_data['full_name']
        )
        login_data = {
            'email': self.user_data['email'],
            'password': 'wrongpass123'
        }
        response = self.client.post(self.login_url, login_data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
