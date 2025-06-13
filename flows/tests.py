from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model
from bots.models import Bot
from .models import Flow

User = get_user_model()

class FlowModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )
        self.bot = Bot.objects.create(
            name='Test Bot',
            user=self.user
        )

    def test_create_flow(self):
        flow = Flow.objects.create(
            name='Test Flow',
            bot=self.bot,
            flow_data={'nodes': [], 'edges': []}
        )
        self.assertEqual(flow.name, 'Test Flow')
        self.assertEqual(flow.status, 'draft')
        self.assertFalse(flow.is_active)

    def test_only_one_active_flow(self):
        flow1 = Flow.objects.create(
            name='Flow 1',
            bot=self.bot,
            is_active=True
        )
        flow2 = Flow.objects.create(
            name='Flow 2',
            bot=self.bot
        )
        
        # Try to activate second flow
        flow2.is_active = True
        flow2.save()
        
        # Refresh from database
        flow1.refresh_from_db()
        flow2.refresh_from_db()
        
        # Check that flow2 is now active and flow1 is not
        self.assertFalse(flow1.is_active)
        self.assertTrue(flow2.is_active)

class FlowAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )
        self.bot = Bot.objects.create(
            name='Test Bot',
            user=self.user
        )
        self.flow = Flow.objects.create(
            name='Test Flow',
            bot=self.bot,
            flow_data={'nodes': [], 'edges': []}
        )
        self.client.force_authenticate(user=self.user)

    def test_list_flows(self):
        url = reverse('flows:flow-list', args=[self.bot.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_create_flow(self):
        url = reverse('flows:flow-list', args=[self.bot.id])
        data = {
            'name': 'New Flow',
            'flow_data': {'nodes': [], 'edges': []},
            'is_active': True
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Flow.objects.count(), 2)
        self.assertEqual(response.data['name'], 'New Flow')

    def test_update_flow(self):
        url = reverse('flows:flow-detail', args=[self.flow.id])
        data = {
            'name': 'Updated Flow',
            'is_active': True
        }
        response = self.client.patch(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.flow.refresh_from_db()
        self.assertEqual(self.flow.name, 'Updated Flow')
        self.assertTrue(self.flow.is_active)

    def test_delete_flow(self):
        url = reverse('flows:flow-detail', args=[self.flow.id])
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Flow.objects.count(), 0)

    def test_unauthorized_access(self):
        # Create another user and bot
        other_user = User.objects.create_user(
            email='other@example.com',
            password='testpass123'
        )
        other_bot = Bot.objects.create(
            name='Other Bot',
            user=other_user
        )
        other_flow = Flow.objects.create(
            name='Other Flow',
            bot=other_bot
        )

        # Try to access other user's flow
        url = reverse('flows:flow-detail', args=[other_flow.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_duplicate_flow_name(self):
        url = reverse('flows:flow-list', args=[self.bot.id])
        data = {
            'name': 'Test Flow',  # Same name as existing flow
            'flow_data': {'nodes': [], 'edges': []}
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('name', response.data)
