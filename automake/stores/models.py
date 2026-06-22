"""
门店模型模块

门店是整个系统的核心组织单元，菜单、设备、订单均与门店关联。
"""

from django.db import models


class Store(models.Model):
    id = models.IntegerField(primary_key=True, verbose_name='门店ID')
    """
    门店表

    字段说明：
    - name：门店名称
    - address：地址
    - lat/lng：经纬度，用于小程序地图展示和附近门店计算
    - status：运营状态，下线门店不允许点单
    - business_hours：营业时间（JSON 格式，按星期存储）
    - contact_phone：门店联系电话
    - code: 用于注册机器的code，  
    """

    # 运营状态常量
    STATUS_OPEN = 'open'         # 营业中
    STATUS_CLOSED = 'closed'     # 已关闭
    STATUS_PAUSED = 'paused'     # 暂停营业（临时）

    STATUS_CHOICES = [
        (STATUS_OPEN, '营业中'),
        (STATUS_CLOSED, '已关闭'),
        (STATUS_PAUSED, '暂停营业'),
    ]

    name = models.CharField(max_length=128, verbose_name='门店名称')
    description = models.TextField(blank=True, verbose_name='门店描述')
    address = models.CharField(max_length=256, blank=True, verbose_name='详细地址')
    # 经纬度：用于地图展示和附近门店筛选
    lat = models.DecimalField(
        max_digits=10, decimal_places=6, null=True, blank=True, verbose_name='纬度'
    )
    lng = models.DecimalField(
        max_digits=10, decimal_places=6, null=True, blank=True, verbose_name='经度'
    )
    contact_phone = models.CharField(max_length=20, blank=True, verbose_name='联系电话')
    code = models.CharField(max_length=64, unique=True, null=True, blank=True, verbose_name='门店注册码')
    
    # 营业时间（JSON 格式）示例：{"mon": "08:00-22:00", "tue": "08:00-22:00", ...}
    business_hours = models.JSONField(default=dict, blank=True, verbose_name='营业时间')
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default=STATUS_OPEN, db_index=True, verbose_name='运营状态'
    )
    # 门店封面图
    cover_image = models.URLField(max_length=512, blank=True, verbose_name='封面图 URL')
    # 排序权重（数值越小越靠前）
    sort_order = models.IntegerField(default=0, verbose_name='排序权重')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'store'
        verbose_name = '门店'
        verbose_name_plural = '门店列表'
        ordering = ['sort_order', '-created_at']

    def __str__(self):
        return self.name

    @property
    def is_open(self):
        """判断门店是否处于营业状态"""
        return self.status == self.STATUS_OPEN

    @property
    def is_in_business_hours(self):
        """判断当前时间是否在门店营业时间内"""
        from django.utils import timezone
        import datetime

        if not self.business_hours:
            # 如果没有设置营业时间，默认视为全天营业以提高可用性
            return True

        # 获取当前本地时间（已应用 settings 配置的时区）
        now = timezone.localtime()
        weekday_map = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
        current_day = weekday_map[now.weekday()]

        time_range = self.business_hours.get(current_day)
        if not time_range:
            # 今天没有配置营业时间，视为不营业
            return False

        try:
            # 解析时间范围，如 "08:00-22:00"
            start_str, end_str = time_range.split('-')
            start_time = datetime.datetime.strptime(start_str.strip(), "%H:%M").time()
            end_time = datetime.datetime.strptime(end_str.strip(), "%H:%M").time()
            current_time = now.time()

            if start_time <= end_time:
                # 正常不跨天营业时间
                return start_time <= current_time <= end_time
            else:
                # 跨天营业时间处理（如：22:00 到次日 02:00）
                return current_time >= start_time or current_time <= end_time
        except Exception:
            # 解析格式异常等容错处理
            return False

    @property
    def can_provide_service(self):
        """
        判断是否可提供菜单服务
        当处于营业状态且在营业时间内，才能提供服务
        """
        return self.is_open and self.is_in_business_hours

    def clean(self):
        super().clean()
        if self.id is not None:
            if self.id < 100000 or self.id > 999999:
                from django.core.exceptions import ValidationError
                raise ValidationError({'id': '门店ID必须是6位数字（100000 ~ 999999）'})

    def save(self, *args, **kwargs):
        if not self.id:
            # 自动生成 6 位数字的 ID，如果库中无数据则从 100000 开始
            max_id = Store.objects.aggregate(max_id=models.Max('id'))['max_id']
            if max_id is None:
                self.id = 100000
            else:
                self.id = max_id + 1
                if self.id > 999999:
                    raise ValueError("门店ID已超出6位数字限制")
        super().save(*args, **kwargs)
