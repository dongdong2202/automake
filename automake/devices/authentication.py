"""
上位机设备 JWT 认证与校验模块
提供设备 Token 校验函数、DRF 认证类及权限类
"""

import jwt
import logging
from functools import wraps
from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.response import Response

from devices.models import Device

logger = logging.getLogger(__name__)


def verify_device_token(token: str) -> tuple[bool, dict | str]:
    """
    上位机设备 JWT Token 校验纯函数
    :param token: JWT 字符串（无需 Bearer 前缀）
    :return: (True, payload) 或 (False, 错误提示字符串)
    """
    if not token:
        return False, "Token 不能为空"
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=['HS256']
        )
        return True, payload
    except jwt.ExpiredSignatureError:
        return False, "Token 已过期，请重新调用注册接口"
    except jwt.InvalidTokenError as e:
        return False, f"Token 非法或签名错误: {str(e)}"
    except Exception as e:
        logger.error(f"JWT 校验未知异常: {e}")
        return False, "Token 校验失败"


class DeviceJWTAuthentication(BaseAuthentication):
    """
    DRF 上位机设备 JWT 认证器
    
    使用说明：
    在 APIView 中配置:
        authentication_classes = [DeviceJWTAuthentication]
        permission_classes = [IsAuthenticatedDevice]
    
    请求成功后:
        request.auth: 对应的 Device 对象
        request.device: 对应的 Device 对象
    """
    def authenticate(self, request):
        auth_header = request.headers.get('Authorization', '').strip()
        if not auth_header:
            return None

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            raise AuthenticationFailed('Authorization Header 格式必须为: Bearer <token>')

        raw_token = parts[1]
        is_valid, result = verify_device_token(raw_token)
        if not is_valid:
            raise AuthenticationFailed(result)

        payload = result
        device_sn = payload.get('device_sn')
        if not device_sn:
            raise AuthenticationFailed('Token Payload 中缺少 device_sn 声明')

        device = Device.objects.filter(device_sn=device_sn).first()
        if not device:
            raise AuthenticationFailed(f'设备 {device_sn} 在系统中不存在或已被移除')

        # 挂载 device 属性到 request
        request.device = device
        return (None, device)


class IsAuthenticatedDevice(BasePermission):
    """
    DRF 权限类：限制只有成功通过设备 JWT 认证的请求才能访问
    """
    message = "未通过上位机设备身份认证"

    def has_permission(self, request, view):
        return bool(getattr(request, 'device', None) or isinstance(request.auth, Device))


def device_auth_required(view_func):
    """
    函数视图/装饰器版本：用于快速装饰普通 Django 视图或 APIView 成员方法
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        auth_header = request.headers.get('Authorization', '').strip()
        if not auth_header or not auth_header.lower().startswith('bearer '):
            return Response({'code': 401, 'message': '缺少 Authorization: Bearer <token> 请求头'}, status=401)

        token = auth_header.split()[1]
        is_valid, result = verify_device_token(token)
        if not is_valid:
            return Response({'code': 401, 'message': result}, status=401)

        device_sn = result.get('device_sn')
        device = Device.objects.filter(device_sn=device_sn).first()
        if not device:
            return Response({'code': 401, 'message': f'设备 {device_sn} 不存在'}, status=401)

        request.device = device
        return view_func(request, *args, **kwargs)
    return _wrapped_view


from drf_spectacular.extensions import OpenApiAuthenticationExtension

class DeviceJWTAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = 'devices.authentication.DeviceJWTAuthentication'
    name = 'deviceJwtAuth'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'http',
            'scheme': 'bearer',
            'bearerFormat': 'JWT',
            'description': '上位机设备 JWT 认证 Token（直接粘贴 access_token 即可）',
        }
