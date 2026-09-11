from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication

class OptionalJWTAuthentication(JWTAuthentication):
    """
    可选的 JWT 认证器：
    当请求携带合法的用户 JWT 时解析出对应 User；
    当未携带或携带的是设备 Token / 无法识别的 Token 时，静默降级返回 None，
    避免阻断配置了 AllowAny 的开放业务接口（例如订单物料预校验）。
    """
    def authenticate(self, request):
        try:
            return super().authenticate(request)
        except Exception:
            return None


class UnifiedOrderAuthentication(BaseAuthentication):
    """
    双模认证器（支持顾客用户 JWT 与上位机终端设备 Token）：
    1. 优先尝试解析顾客用户 JWT (SimpleJWT)。
    2. 若携带的是上位机设备 Token (devices.authentication.verify_device_token)，
       则自动校验设备存在性，并挂载/创建专属的线下柜机终端账号 (kiosk_<device_sn>)，
       将终端用户作为 request.user，设备实体作为 request.device 和 request.auth。
    3. 若未携带任何 Token，返回 None 交由后续认证器（如 DevMockAuthentication）或权限类裁决。
    """
    def authenticate(self, request):
        auth_header = (
            request.headers.get('Authorization') or
            request.META.get('HTTP_AUTHORIZATION') or ''
        ).strip()
        if not auth_header:
            return None

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            return None

        raw_token = parts[1]

        # 1. 尝试作为普通用户 SimpleJWT 验证
        try:
            jwt_auth = JWTAuthentication()
            validated_token = jwt_auth.get_validated_token(raw_token)
            user = jwt_auth.get_user(validated_token)
            if user:
                return (user, validated_token)
        except Exception:
            pass

        # 2. 尝试作为上位机设备 Token 验证
        try:
            from devices.authentication import verify_device_token
            from devices.models import Device
            is_valid, result = verify_device_token(raw_token)
            if is_valid and isinstance(result, dict):
                device_sn = result.get('device_sn')
                if device_sn:
                    device = Device.objects.filter(device_sn=device_sn).first()
                    if device:
                        User = get_user_model()
                        kiosk_user, _ = User.objects.get_or_create(
                            openid=f"kiosk_{device_sn}",
                            defaults={
                                'username': f"kiosk_{device_sn}",
                                'role': getattr(User, 'CUSTOMER', 'customer'),
                                'is_active': True
                            }
                        )
                        request.device = device
                        return (kiosk_user, device)
        except Exception:
            pass

        return None


