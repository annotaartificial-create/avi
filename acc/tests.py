from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core import mail
from acc.models import PasswordResetCode

User = get_user_model()


class CustomAuthTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='trader@domain.com',
            password='Password123!'
        )

    def test_user_creation_and_auto_username(self):
        self.assertEqual(self.user.email, 'trader@domain.com')
        self.assertEqual(self.user.username, 'trader')
        self.assertTrue(self.user.check_password('Password123!'))

        # Test collision handling
        user2 = User.objects.create_user(
            email='trader@otherdomain.com',
            password='Password123!'
        )
        self.assertTrue(user2.username.startswith('trader_'))

    def test_login_flow(self):
        response = self.client.post(reverse('acc:login'), {
            'email': 'trader@domain.com',
            'password': 'Password123!',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['user'].is_authenticated)

    def test_login_invalid_credentials(self):
        response = self.client.post(reverse('acc:login'), {
            'email': 'trader@domain.com',
            'password': 'WrongPassword!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['user'].is_authenticated)
        self.assertContains(response, 'Invalid email or password')

    def test_signup_flow(self):
        response = self.client.post(reverse('acc:signup'), {
            'email': 'newtrader@domain.com',
            'password': 'ComplexPass123!',
            'confirm_password': 'ComplexPass123!',
            'terms': True,
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        new_user = User.objects.get(email='newtrader@domain.com')
        self.assertEqual(new_user.username, 'newtrader')
        self.assertTrue(response.context['user'].is_authenticated)

    def test_signup_password_mismatch(self):
        response = self.client.post(reverse('acc:signup'), {
            'email': 'mismatch@domain.com',
            'password': 'ComplexPass123!',
            'confirm_password': 'DifferentPass123!',
            'terms': True,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Passwords do not match')

    def test_password_reset_code_generation_and_confirm(self):
        # 1. Request reset
        response = self.client.post(reverse('acc:password_reset'), {
            'email': 'trader@domain.com',
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        # Check reset code was generated
        code_obj = PasswordResetCode.objects.filter(user=self.user, is_used=False).first()
        self.assertIsNotNone(code_obj)
        self.assertEqual(len(code_obj.code), 6)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(code_obj.code, mail.outbox[0].body)

        # 2. Confirm reset with code
        confirm_response = self.client.post(reverse('acc:password_reset_confirm'), {
            'email': 'trader@domain.com',
            'code': code_obj.code,
            'new_password': 'NewPassword456!',
            'confirm_password': 'NewPassword456!',
        }, follow=True)
        self.assertEqual(confirm_response.status_code, 200)

        # Check code is marked used
        code_obj.refresh_from_db()
        self.assertTrue(code_obj.is_used)

        # Check login with new password
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewPassword456!'))
