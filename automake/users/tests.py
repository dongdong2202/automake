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


from unittest.mock import patch
from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from .models import User, UserProfile

class WechatLoginAPITests(APITestCase):
    @patch('utils.wechat.WechatMiniApp.code_to_session')
    def test_wechat_login_with_wxfile_avatar(self, mock_code_to_session):
        # 模拟微信服务器返回 openid 和 session_key
        mock_code_to_session.return_value = {
            'openid': 'test_openid_wxfile',
            'session_key': 'test_session_key_wxfile',
            'unionid': 'test_unionid_wxfile'
        }

        url = reverse('user-login')
        data = {
            'code': 'mock_code',
            'nickname': 'Test User',
            'avatar_url': 'wxfile://temp/19ee5ddfcba_bec.jpeg'
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['code'], 0)  # 成功返回 code 应为 0
        
        # 验证数据库中是否成功创建用户并保存了 wxfile 头像
        user = User.objects.get(openid='test_openid_wxfile')
        self.assertEqual(user.profile.avatar_url, 'wxfile://temp/19ee5ddfcba_bec.jpeg')
        self.assertEqual(user.profile.nickname, 'Test User')

    def test_update_profile_with_wxfile_avatar(self):
        from .models import UserProfile
        # 创建测试用户并登录
        user = User.objects.create_user(openid='test_update_openid')
        profile = UserProfile.objects.create(user=user, nickname='Old Nick', avatar_url='')
        
        self.client.force_authenticate(user=user)
        url = reverse('user-profile')
        data = {
            'nickname': 'New Nick',
            'avatar_url': 'wxfile://temp/new_avatar.jpeg'
        }
        
        # PUT 更新个人资料
        response = self.client.put(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['code'], 0)
        
        # 验证更新结果
        profile.refresh_from_db()
        self.assertEqual(profile.nickname, 'New Nick')
        self.assertEqual(profile.avatar_url, 'wxfile://temp/new_avatar.jpeg')


