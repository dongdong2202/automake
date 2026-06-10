"""
用户模型模块

定义三种角色的用户体系：
  - SUPER_ADMIN（超级管理员）：全系统权限，可管理门店、菜单、设备
  - ADMIN（管理员）：门店级管理权限
  - CUSTOMER（客户）：普通微信小程序用户，只能下单
"""

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    """
    自定义用户管理器
    支持通过 openid（微信）或 username（后台管理员）创建用户
    """

    def create_user(self, openid, **extra_fields):
        """
        创建普通微信用户（客户角色）
        :param openid: 微信小程序唯一标识
        """
        if not openid:
            raise ValueError('openid 不能为空')
        user = self.model(openid=openid, **extra_fields)
        user.set_unusable_password()  # 微信用户无需密码登录
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password, **extra_fields):
        """
        创建超级管理员（用于 Django Admin 后台登录）
        :param username: 用户名
        :param password: 密码
        """
        extra_fields.setdefault('role', User.SUPER_ADMIN)
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        user = self.model(username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user


class User(AbstractBaseUser, PermissionsMixin):
    """
    统一用户模型

    字段说明：
    - openid：微信小程序标识，客户登录的唯一凭证，后台管理员可为空
    - username：后台管理员使用，客户为空
    - role：角色，决定权限范围
    - is_active：是否激活（禁用用户时设为 False）
    - is_staff：是否可登录 Django Admin
    """

    # 角色常量定义
    SUPER_ADMIN = 'super_admin'  # 超级管理员
    ADMIN = 'admin'              # 管理员（门店级）
    CUSTOMER = 'customer'        # 客户（微信小程序用户）

    ROLE_CHOICES = [
        (SUPER_ADMIN, '超级管理员'),
        (ADMIN, '管理员'),
        (CUSTOMER, '客户'),
    ]

    # 微信标识，客户必填，管理员可空
    openid = models.CharField(
        max_length=128, unique=True, null=True, blank=True,
        db_index=True, verbose_name='微信 openid'
    )
    # 微信 unionid（跨公众号/小程序唯一标识，视业务需要使用）
    unionid = models.CharField(
        max_length=128, null=True, blank=True,
        db_index=True, verbose_name='微信 unionid'
    )
    # 后台管理员用户名（客户为空）
    username = models.CharField(
        max_length=64, unique=True, null=True, blank=True,
        verbose_name='用户名'
    )
    # 手机号（可选，用于通知）
    phone = models.CharField(
        max_length=20, null=True, blank=True,
        verbose_name='手机号'
    )
    # 角色
    role = models.CharField(
        max_length=20, choices=ROLE_CHOICES,
        default=CUSTOMER, db_index=True, verbose_name='角色'
    )
    # 关联的门店（管理员级别绑定门店，超级管理员为空表示全局）
    store = models.ForeignKey(
        'stores.Store', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='admins',
        verbose_name='关联门店'
    )
    # Django 内置权限字段
    is_active = models.BooleanField(default=True, verbose_name='是否激活')
    is_staff = models.BooleanField(default=False, verbose_name='可登录后台')
    # 时间字段
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    objects = UserManager()

    # 以 openid 为核心身份标识（微信用户）；后台管理员用 username
    USERNAME_FIELD = 'openid'
    REQUIRED_FIELDS = []

    class Meta:
        db_table = 'user'
        verbose_name = '用户'
        verbose_name_plural = '用户列表'
        ordering = ['-created_at']

    def __str__(self):
        return self.username or self.openid or f'User({self.pk})'

    def get_username(self):
        """
        获取用户名。
        为了兼容 django-unfold 等模板引擎的头像展示逻辑，
        如果 username 为空则返回 openid，确保返回值不为 None。
        """
        return self.username or self.openid or f"User({self.pk})"

    def get_full_name(self):
        return self.username or self.openid or f"User({self.pk})"

    def get_short_name(self):
        return self.username or self.openid or f"User({self.pk})"

    # ---------- 角色判断快捷方法 ----------

    @property
    def is_super_admin(self):
        """判断是否为超级管理员"""
        return self.role == self.SUPER_ADMIN

    @property
    def is_admin(self):
        """判断是否为管理员或超级管理员"""
        return self.role in (self.SUPER_ADMIN, self.ADMIN)

    @property
    def is_customer(self):
        """判断是否为普通客户"""
        return self.role == self.CUSTOMER


class UserProfile(models.Model):
    """
    用户扩展信息表（与 User 一对一）

    存放头像、昵称、微信会话密钥等非核心字段，
    避免主表过宽，也便于单独更新用户信息。
    """
    user = models.OneToOneField(
        User, on_delete=models.CASCADE,
        related_name='profile', verbose_name='用户'
    )
    nickname = models.CharField(max_length=64, blank=True, verbose_name='昵称')
    avatar_url = models.URLField(max_length=512, blank=True, verbose_name='头像 URL')
    # 性别：0未知，1男，2女
    sex = models.SmallIntegerField(default=0, choices=[(0, '未知'), (1, '男'), (2, '女')], verbose_name='性别')
    # 年龄
    age = models.SmallIntegerField(null=True, blank=True, verbose_name='年龄')
    # 微信会话密钥（敏感，不应长期保存，此处仅做临时存储参考）
    session_key = models.CharField(max_length=128, blank=True, verbose_name='会话密钥')
    # 会员积分（预留字段）
    points = models.IntegerField(default=0, verbose_name='积分')
    # 备注
    remark = models.CharField(max_length=256, blank=True, verbose_name='备注')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'user_profile'
        verbose_name = '用户扩展信息'
        verbose_name_plural = '用户扩展信息'

    def __str__(self):
        return f'{self.user} 的 Profile'
