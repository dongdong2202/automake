from django.test import TestCase
from .models import User

class UserMethodTests(TestCase):
    def test_superuser_methods(self):
        # 1. 后台管理员：有 username，无 openid
        user = User.objects.create_superuser(username='cxd_test', password='password123')
        self.assertEqual(user.get_username(), 'cxd_test')
        self.assertEqual(user.get_full_name(), 'cxd_test')
        self.assertEqual(user.get_short_name(), 'cxd_test')

    def test_customer_methods(self):
        # 2. 微信用户：有 openid，无 username
        user = User.objects.create_user(openid='openid_test')
        self.assertEqual(user.get_username(), 'openid_test')
        self.assertEqual(user.get_full_name(), 'openid_test')
        self.assertEqual(user.get_short_name(), 'openid_test')

    def test_empty_user_methods(self):
        # 3. 边界情况：无 username，无 openid
        user = User.objects.create(username=None, openid=None)
        expected = f"User({user.pk})"
        self.assertEqual(user.get_username(), expected)
        self.assertEqual(user.get_full_name(), expected)
        self.assertEqual(user.get_short_name(), expected)

