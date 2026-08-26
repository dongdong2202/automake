from rest_framework.authentication import BaseAuthentication
from django.contrib.auth import get_user_model
from django.conf import settings

class DevMockAuthentication(BaseAuthentication):
    """
    开发/测试阶段免 Token 自动登录认证器。

    【使用说明】
    仅在 settings.DEBUG = True 时生效。
    如果请求的 Header 中没有携带 Authorization，则自动以数据库中第一个用户身份进行登录，
    从而免去在测试阶段频繁在 Swagger UI 复制粘贴 JWT Token 的操作。
    """
    def authenticate(self, request):
        if not settings.DEBUG:
            return None

        # 如果请求头里提供了 JWT Token，则跳过此 Mock，交给 SimpleJWT 验证
        auth_header = request.headers.get('Authorization', '')
        if auth_header and auth_header.strip().startswith('Bearer'):
            return None

        User = get_user_model()
        user = User.objects.first()
        if not user:
            # 如果数据库是空的，自动创建一个测试用户
            user = User.objects.create_user(
                openid='dev-test-openid',
                username='dev_tester',
                nickname='开发测试账号'
            )

        # 返回 (user, auth)
        return (user, None)
