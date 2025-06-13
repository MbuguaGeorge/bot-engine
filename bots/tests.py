from django.test import TestCase
from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from django.contrib.auth import get_user_model
from .models import Bot

User = get_user_model()

class BotTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123',
            full_name='Test User'
        )
        self.client.force_authenticate(user=self.user)
        
        self.bot_data = {
            'name': 'Test Bot',
            'phone_number': '+1234567890',
            'status': 'draft',
            'flow_data': {'nodes': [], 'edges': []},
            'whatsapp_connected': False
        }
        
        self.bot = Bot.objects.create(
            user=self.user,
            **self.bot_data
        )

    def test_create_bot_with_null_phone(self):
        url = reverse('bots:bot-list')
        data = {
            'name': 'Null Phone Bot',
            'phone_number': None,
            'status': 'draft',
            'flow_data': {'nodes': [], 'edges': []}
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data['phone_number'])

    def test_create_bot_with_blank_phone(self):
        url = reverse('bots:bot-list')
        data = {
            'name': 'Blank Phone Bot',
            'phone_number': '',
            'status': 'draft',
            'flow_data': {'nodes': [], 'edges': []}
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data['phone_number'])

    def test_create_bot(self):
        url = reverse('bots:bot-list')
        data = {
            'name': 'New Bot',
            'phone_number': '+1987654321',
            'status': 'draft',
            'flow_data': {'nodes': [], 'edges': []}
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Bot.objects.count(), 2)
        self.assertEqual(Bot.objects.get(name='New Bot').user, self.user)

    def test_list_bots(self):
        url = reverse('bots:bot-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_get_bot_detail(self):
        url = reverse('bots:bot-detail', kwargs={'pk': self.bot.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], self.bot_data['name'])
        self.assertEqual(response.data['phone_number'], self.bot_data['phone_number'])

    def test_update_bot(self):
        url = reverse('bots:bot-detail', kwargs={'pk': self.bot.pk})
        data = {
            'name': 'Updated Bot',
            'phone_number': '+1555555555',
            'status': 'active'
        }
        # Test PUT request
        response = self.client.put(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Bot.objects.get(pk=self.bot.pk).name, 'Updated Bot')
        self.assertEqual(Bot.objects.get(pk=self.bot.pk).phone_number, '+1555555555')
        self.assertEqual(Bot.objects.get(pk=self.bot.pk).status, 'active')

        # Test PATCH request with null phone
        patch_data = {'name': 'Patched Bot', 'phone_number': None}
        response = self.client.patch(url, patch_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Bot.objects.get(pk=self.bot.pk).name, 'Patched Bot')
        self.assertIsNone(Bot.objects.get(pk=self.bot.pk).phone_number)

    def test_delete_bot(self):
        url = reverse('bots:bot-detail', kwargs={'pk': self.bot.pk})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Bot.objects.count(), 0)

    def test_duplicate_bot(self):
        url = reverse('bots:bot-duplicate', kwargs={'pk': self.bot.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Bot.objects.count(), 2)
        self.assertTrue(response.data['name'].endswith('(Copy)'))
        self.assertIsNone(response.data['phone_number'])  # Phone number should be None for copy

    def test_invalid_phone_number(self):
        url = reverse('bots:bot-list')
        data = {
            'name': 'Invalid Phone Bot',
            'phone_number': '1234567890',  # Missing + prefix
            'status': 'draft'
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('phone_number', response.data)

    def test_duplicate_phone_number(self):
        url = reverse('bots:bot-list')
        data = {
            'name': 'Duplicate Phone Bot',
            'phone_number': self.bot_data['phone_number'],  # Using existing phone number
            'status': 'draft'
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('phone_number', response.data)

    def test_toggle_whatsapp(self):
        url = reverse('bots:bot-toggle-whatsapp', kwargs={'pk': self.bot.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['whatsapp_connected'])

    def test_bot_not_found(self):
        url = reverse('bots:bot-detail', kwargs={'pk': 99999})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthorized_access(self):
        # Create another user and bot
        other_user = User.objects.create_user(
            email='other@example.com',
            password='testpass123',
            full_name='Other User'
        )
        other_bot = Bot.objects.create(
            user=other_user,
            name='Other Bot',
            phone_number='+1999999999',
            status='draft'
        )

        # Try to access other user's bot
        url = reverse('bots:bot-detail', kwargs={'pk': other_bot.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
