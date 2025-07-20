from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APITestCase
from rest_framework import status
from .tasks import delete_expired_accounts

User = get_user_model()

class AuthenticationTests(APITestCase):
    def setUp(self):
        self.user_data = {
            'email': 'test@example.com',
            'full_name': 'Test User',
            'password': 'testpass123'
        }
        self.user = User.objects.create_user(**self.user_data)

    def test_user_signup(self):
        response = self.client.post('/api/signup/', {
            'email': 'newuser@example.com',
            'full_name': 'New User',
            'password': 'newpass123'
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(email='newuser@example.com').exists())

    def test_user_signup_invalid_data(self):
        # Test without email
        response = self.client.post('/api/signup/', {
            'full_name': 'New User',
            'password': 'newpass123'
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_user_login(self):
        # Create a user first
        response = self.client.post('/api/login/', {
            'email': 'test@example.com',
            'password': 'testpass123'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('token', response.data)

    def test_user_login_invalid_credentials(self):
        # Try logging in with non-existent user
        response = self.client.post('/api/login/', {
            'email': 'nonexistent@example.com',
            'password': 'wrongpass'
        })
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_blocked_for_pending_deletion(self):
        # Mark user for deletion
        self.user.is_pending_deletion = True
        self.user.deletion_requested_at = timezone.now()
        self.user.save()

        response = self.client.post('/api/login/', {
            'email': 'test@example.com',
            'password': 'testpass123'
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('scheduled for deletion', response.data['error'])

    def test_delete_account_requires_password(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post('/api/delete-account/', {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Password is required', response.data['error'])

    def test_delete_account_wrong_password(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post('/api/delete-account/', {
            'password': 'wrongpassword'
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Password is incorrect', response.data['error'])

    def test_delete_account_success(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post('/api/delete-account/', {
            'password': 'testpass123'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('scheduled for deletion', response.data['message'])
        
        # Check user is marked for deletion
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_pending_deletion)
        self.assertIsNotNone(self.user.deletion_requested_at)


class AccountDeletionTaskTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='test@example.com',
            full_name='Test User',
            password='testpass123'
        )

    def test_delete_expired_accounts_task(self):
        # Mark user for deletion 61 days ago
        self.user.is_pending_deletion = True
        self.user.deletion_requested_at = timezone.now() - timedelta(days=61)
        self.user.save()

        # Run the task
        deleted_count = delete_expired_accounts()

        # Check user was deleted
        self.assertEqual(deleted_count, 1)
        self.assertFalse(User.objects.filter(email='test@example.com').exists())

    def test_delete_expired_accounts_task_not_expired(self):
        # Mark user for deletion 30 days ago (not expired)
        self.user.is_pending_deletion = True
        self.user.deletion_requested_at = timezone.now() - timedelta(days=30)
        self.user.save()

        # Run the task
        deleted_count = delete_expired_accounts()

        # Check user was NOT deleted
        self.assertEqual(deleted_count, 0)
        self.assertTrue(User.objects.filter(email='test@example.com').exists())

    def test_delete_expired_accounts_task_not_pending(self):
        # User not marked for deletion
        self.user.is_pending_deletion = False
        self.user.deletion_requested_at = timezone.now() - timedelta(days=61)
        self.user.save()

        # Run the task
        deleted_count = delete_expired_accounts()

        # Check user was NOT deleted
        self.assertEqual(deleted_count, 0)
        self.assertTrue(User.objects.filter(email='test@example.com').exists())
