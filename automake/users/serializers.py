"""
用户模块序列化器
"""

from rest_framework import serializers
from .models import User, UserProfile


class UserProfileSerializer(serializers.ModelSerializer):
    """用户扩展信息序列化器"""

    class Meta:
        model = UserProfile
        fields = ['nickname', 'avatar_url', 'sex', 'age', 'points']


class UserSerializer(serializers.ModelSerializer):
    """用户基础信息序列化器（对外输出，隐藏敏感字段）"""
    profile = UserProfileSerializer(read_only=True)

    class Meta:
        model = User
        fields = ['id', 'openid', 'phone', 'role', 'profile', 'created_at']
        read_only_fields = fields


class WechatLoginSerializer(serializers.Serializer):
    """
    微信登录请求序列化器

    小程序端调用 wx.login() 获得 code，传给此接口换取 JWT Token。
    """
    code = serializers.CharField(
        min_length=1, max_length=512,
        error_messages={'required': 'code 不能为空', 'blank': 'code 不能为空'}
    )
    # 可选：小程序端通过 wx.getUserInfo 获得的用户信息（头像、昵称）
    nickname = serializers.CharField(required=False, allow_blank=True, max_length=64)
    avatar_url = serializers.URLField(required=False, allow_blank=True)
    # 可选：前端传进来的手机号
    phone = serializers.CharField(required=False, allow_blank=True, max_length=200)
    # 可选：性别 (0未知, 1男, 2女)，年龄
    sex = serializers.IntegerField(required=False, default=0)
    age = serializers.IntegerField(required=False, allow_null=True)


class UpdateProfileSerializer(serializers.ModelSerializer):
    """更新用户扩展信息序列化器"""

    class Meta:
        model = UserProfile
        fields = ['nickname', 'avatar_url', 'sex', 'age']
