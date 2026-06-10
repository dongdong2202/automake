from django.contrib.auth.backends import ModelBackend
from django.db.models import Q
import logging

from .models import User

logger = logging.getLogger(__name__)

class CustomAuthBackend(ModelBackend):
    """
    自定义认证后端
    支持后台管理员通过 username + password 登录，也支持微信用户通过 openid 认证
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            return None
        try:
            # 支持通过 openid 或 username 查找用户
            user = User.objects.get(Q(openid=username) | Q(username=username))
            
            # 如果是后台管理员（有密码），需要验证密码
            if user.has_usable_password():
                if user.check_password(password):
                    logger.info(f"管理员/用户 {user.username or user.openid} 通过密码验证成功")
                    return user
                else:
                    logger.warning(f"管理员/用户 {user.username or user.openid} 密码验证失败")
                    return None
            else:
                # 微信免密登录（通过 openid 直接认证）
                logger.info(f"微信用户 {user.openid} 免密认证成功")
                return user
        except User.DoesNotExist:
            logger.debug(f"未找到对应的用户: {username}")
            return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
