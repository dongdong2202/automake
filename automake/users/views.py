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


class AdminLoginView(APIView):
    """
    管理员账号密码登录接口

    POST /api/user/admin/login
    请求体：{ "username": "admin", "password": "..." }
    响应：{ "access": "<JWT>", "refresh": "<JWT>", "user": { ... } }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username', '').strip()
        password = request.data.get('password', '').strip()

        if not username or not password:
            return error('用户名和密码不能为空', code=4001)

        from django.contrib.auth import authenticate
        user = authenticate(request, username=username, password=password)
        if not user:
            # 尝试直接按 User 查找并 check_password
            user_obj = User.objects.filter(username=username).first()
            if user_obj and user_obj.check_password(password):
                user = user_obj

        if not user:
            return error('用户名或密码错误', code=4002)

        if not user.is_active:
            return error('该账号已被禁用', code=4003)

        if not user.is_admin:
            return error('无权登录后台运营系统', code=4004)

        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        refresh_token = str(refresh)

        # 获取用户绑定的门店列表
        stores_data = []
        if user.is_super_admin:
            # 超管可访问所有门店
            from stores.models import Store
            stores_data = [{'id': s.id, 'name': s.name, 'code': s.code or ''} for s in Store.objects.all()]
        else:
            stores_data = [{'id': s.id, 'name': s.name, 'code': s.code or ''} for s in user.stores.all()]

        user_data = {
            'id': user.id,
            'username': user.username or '',
            'role': user.role,
            'is_super_admin': user.is_super_admin,
            'is_material_admin': user.is_material_admin,
            'stores': stores_data,
        }

        logger.info(f"后台运营人员登录成功: username={username}, role={user.role}, ID={user.id}")

        return ok({
            'access': access_token,
            'refresh': refresh_token,
            'user': user_data,
        }, message='登录成功')


class UserCouponListView(APIView):
    """
    用户优惠券列表
    GET /api/user/coupons
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from orders.models import UserCoupon
        from django.utils import timezone
        import datetime

        # 如果是新用户，自动赠送 3 张初始优惠券包
        if not UserCoupon.objects.filter(user=request.user).exists():
            now = timezone.now()
            default_coupons = [
                {'title': '新人专享 ¥5 无门槛立减券', 'coupon_type': UserCoupon.TYPE_DIRECT, 'amount': 500, 'min_spend': 0, 'expires_at': now + datetime.timedelta(days=30)},
                {'title': '秋季饮品满 ¥25 减 ¥6', 'coupon_type': UserCoupon.TYPE_REDUCTION, 'amount': 600, 'min_spend': 2500, 'expires_at': now + datetime.timedelta(days=15)},
                {'title': '全场 8.5 折限时折扣券', 'coupon_type': UserCoupon.TYPE_DISCOUNT, 'amount': 0, 'min_spend': 1500, 'discount_rate': 85, 'expires_at': now + datetime.timedelta(days=7)},
            ]
            for c in default_coupons:
                UserCoupon.objects.create(user=request.user, **c)

        status = request.query_params.get('status', 'available')
        qs = UserCoupon.objects.filter(user=request.user)
        if status:
            qs = qs.filter(status=status)

        data = [
            {
                'id': c.id,
                'title': c.title,
                'coupon_type': c.coupon_type,
                'type_display': c.get_coupon_type_display(),
                'amount': c.amount,
                'min_spend': c.min_spend,
                'discount_rate': c.discount_rate,
                'status': c.status,
                'status_display': c.get_status_display(),
                'expires_at': c.expires_at.strftime('%Y-%m-%d %H:%M')
            }
            for c in qs
        ]
        return ok(data)


class UserCouponClaimView(APIView):
    """
    领取优惠券
    POST /api/user/coupons/claim
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from orders.models import UserCoupon
        from django.utils import timezone
        import datetime

        title = request.data.get('title', '会员活动立减券')
        amount = int(request.data.get('amount', 500))
        min_spend = int(request.data.get('min_spend', 2000))

        coupon = UserCoupon.objects.create(
            user=request.user,
            title=title,
            coupon_type=UserCoupon.TYPE_REDUCTION if min_spend > 0 else UserCoupon.TYPE_DIRECT,
            amount=amount,
            min_spend=min_spend,
            expires_at=timezone.now() + datetime.timedelta(days=14)
        )
        return ok({
            'id': coupon.id,
            'title': coupon.title,
            'amount': coupon.amount,
            'expires_at': coupon.expires_at.strftime('%Y-%m-%d %H:%M')
        }, message='优惠券领取成功')


class UserPointsView(APIView):
    """
    用户积分与变动流水
    GET /api/user/points
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from orders.models import UserPointLog
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        
        # 若无历史流水，初始化送 100 积分
        if profile.points == 0 and not UserPointLog.objects.filter(user=request.user).exists():
            profile.points = 100
            profile.save(update_fields=['points'])
            UserPointLog.objects.create(
                user=request.user,
                points=100,
                balance_after=100,
                action='新会员注册赠送积分'
            )

        logs = UserPointLog.objects.filter(user=request.user)[:20]
        logs_data = [
            {
                'id': log.id,
                'points': log.points,
                'balance_after': log.balance_after,
                'action': log.action,
                'created_at': log.created_at.strftime('%Y-%m-%d %H:%M')
            }
            for log in logs
        ]

        return ok({
            'points': profile.points,
            'logs': logs_data
        })


class UserPhoneBindView(APIView):
    """
    绑定手机号 (支持微信 code 解密或明文手机号)
    POST /api/user/phone/bind
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        phone_code = request.data.get('phone', '').strip()
        if not phone_code:
            return error('手机号参数不能为空', code=1007)

        real_phone = phone_code
        if not phone_code.isdigit():
            # 尝试微信解密
            try:
                real_phone = WechatMiniApp.get_user_phone_number(phone_code)
            except Exception as e:
                logger.warning(f"微信手机号解密失败: {e}")
                return error('手机号解析失败，请重试', code=1008)

        request.user.phone = real_phone
        request.user.save(update_fields=['phone'])
        return ok({'phone': real_phone}, message='手机号绑定成功')

