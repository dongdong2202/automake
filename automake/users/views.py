"""
用户模块视图

接口列表：
- POST /api/user/login       微信小程序登录，返回 JWT Token
- GET  /api/user/profile     获取当前用户信息
- PUT  /api/user/profile     更新当前用户资料（昵称、头像）
- POST /api/token/refresh    刷新 Access Token（JWT 标准接口）
"""

import logging
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken

from utils.wechat import WechatMiniApp
from utils.response import ok, error
from utils.permissions import IsCustomer
from .models import User, UserProfile
from .serializers import WechatLoginSerializer, UserSerializer, UpdateProfileSerializer

logger = logging.getLogger(__name__)


class WechatLoginView(APIView):
    """
    微信小程序登录接口

    POST /api/user/login
    请求体：{ "code": "<wx.login 返回的 code>", "nickname": "...", "avatar_url": "..." }
    响应：{ "access": "<JWT>", "refresh": "<JWT>", "user": { ... } }

    流程：
    1. 用 code 向微信服务器换取 openid 和 session_key
    2. 根据 openid 查找或创建用户（首次登录自动注册）
    3. 生成 JWT Token 并返回
    """
    permission_classes = [AllowAny]  # 登录接口不需要认证

    def post(self, request):
        logger.info(f"收到微信登录请求: {request.data}")
        serializer = WechatLoginSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"微信登录参数验证失败: {serializer.errors}")
            return error(str(serializer.errors), code=1001)

        code = serializer.validated_data['code']
        nickname = serializer.validated_data.get('nickname', '')
        avatar_url = serializer.validated_data.get('avatar_url', '')
        phone = serializer.validated_data.get('phone', '')

        # 获取并解析真实手机号
        real_phone = ''
        if phone:
            # 判断是明文手机号还是微信 code (明文只包含数字、空格、+、-等符号)
            is_plain = phone.replace('+', '').replace('-', '').replace(' ', '').isdigit()
            if is_plain:
                real_phone = phone
                logger.info(f"收到明文手机号: {real_phone}")
            else:
                logger.info(f"收到手机号获取凭证(code): {phone}，尝试调用微信接口换取真实手机号...")
                try:
                    real_phone = WechatMiniApp.get_user_phone_number(phone)
                    logger.info(f"微信接口解密成功，真实手机号为: {real_phone}")
                except ValueError as e:
                    logger.error(f"微信接口解密手机号失败: {e}")
                    return error(str(e), code=1006)

        logger.debug(f"解析参数: code={code[:10]}... nickname={nickname}, phone={phone}, real_phone={real_phone}")

        # 1. 通过 code 向微信服务器换取 openid
        try:
            logger.info("向微信服务器请求会话信息...")
            wx_data = WechatMiniApp.code_to_session(code)
            logger.info("获取微信会话数据成功")
        except ValueError as e:
            logger.error(f"微信会话获取失败: {e}")
            return error(str(e), code=1002)

        openid = wx_data.get('openid')
        session_key = wx_data.get('session_key', '')
        unionid = wx_data.get('unionid', '')

        if not openid:
            logger.warning("微信返回数据中不包含 openid")
            return error('无法获取微信用户标识', code=1003)

        # 2. 查找或创建用户（原子操作，防止并发重复创建）
        try:
            with transaction.atomic():
                logger.debug(f"尝试获取或创建用户，openid={openid}")
                user, created = User.objects.get_or_create(
                    openid=openid,
                    defaults={
                        'role': User.CUSTOMER,
                        'is_active': True,
                        'phone': real_phone,
                    }
                )
                
                # 如果用户已存在且前端传了新手机号，进行更新
                if not created and real_phone and user.phone != real_phone:
                    logger.info(f"更新用户手机号: {user.phone} -> {real_phone}")
                    user.phone = real_phone
                    user.save(update_fields=['phone'])

                # 更新 unionid（首次获取或之前未获取到的情况）
                if unionid and not user.unionid:
                    logger.info(f"更新用户 unionid: {unionid}")
                    user.unionid = unionid
                    user.save(update_fields=['unionid'])

                # 首次登录：创建用户扩展信息
                profile, profile_created = UserProfile.objects.get_or_create(
                    user=user,
                    defaults={
                        'nickname': nickname,
                        'avatar_url': avatar_url,
                        'session_key': session_key,
                    }
                )
                if not profile_created:
                    # 更新 session_key（每次登录刷新）
                    update_fields = ['session_key']
                    profile.session_key = session_key
                    # 仅在用户主动传来新昵称/头像且原本为空时更新
                    if nickname and not profile.nickname:
                        profile.nickname = nickname
                        update_fields.append('nickname')
                    if avatar_url and not profile.avatar_url:
                        profile.avatar_url = avatar_url
                        update_fields.append('avatar_url')
                    
                    logger.debug(f"更新用户 Profile: {update_fields}")
                    profile.save(update_fields=update_fields)

        except Exception as e:
            logger.exception(f'微信登录创建/查找用户失败，openid={openid}: {e}')
            return error('服务器内部错误，请稍后重试', code=1004, status=500)

        # 3. 生成 JWT Token
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        refresh_token = str(refresh)

        user_data = UserSerializer(user).data
        logger.info(f"用户登录成功: openid={openid}, 新注册={created}, ID={user.id}")

        return ok({
            'access': access_token,
            'refresh': refresh_token,
            'user': user_data,
        }, message='登录成功')


class UserProfileView(APIView):
    """
    用户信息接口

    GET  /api/user/profile  查看当前用户信息
    PUT  /api/user/profile  更新昵称/头像/性别/年龄
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """获取当前登录用户的详细信息"""
        user_data = UserSerializer(request.user).data
        return ok(user_data)

    def put(self, request):
        """更新用户扩展资料（昵称、头像、性别、年龄）"""
        logger.info(f"用户 {request.user.id} 尝试更新个人资料: {request.data}")
        # 确保用户有 profile（理论上登录时已创建，此处保险）
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        serializer = UpdateProfileSerializer(profile, data=request.data, partial=True)
        if not serializer.is_valid():
            logger.warning(f"用户 {request.user.id} 更新个人资料参数验证失败: {serializer.errors}")
            return error(str(serializer.errors), code=1005)
        serializer.save()
        logger.info(f"用户 {request.user.id} 个人资料更新成功: {serializer.validated_data}")
        user_data = UserSerializer(request.user).data
        return ok(user_data, message='资料更新成功')

    def post(self, request):
        """兼容某些前端框架，支持使用 POST 方法更新个人资料"""
        return self.put(request)
    
