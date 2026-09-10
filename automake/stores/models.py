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

    def _parse_business_hours_status(self) -> tuple[bool, str]:
        """
        内部辅助方法：解析当前门店营业状态与提示文案

        Returns:
            tuple[bool, str]: (是否处于营业时间内, 营业状态提示文案)
        """
        from django.utils import timezone
        import datetime

        if self.status != self.STATUS_OPEN:
            return False, '已打烊'

        if not self.business_hours:
            return True, '营业中'

        # 如果 business_hours 的所有星期配置均为空字符串，视为全天24小时营业
        has_any_config = any(bool(str(v).strip()) for v in self.business_hours.values() if v is not None)
        if not has_any_config:
            return True, '营业中'

        # 使用 Django 的 localtime，支持 TIME_ZONE 配置及单元测试 mock
        try:
            now = timezone.localtime()
        except Exception:
            now = timezone.now()

        weekday_map = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
        current_day = weekday_map[now.weekday()]

        time_range = self.business_hours.get(current_day)
        if time_range is None or str(time_range).strip() == '':
            # 今天留空未设置，默认视为全天营业
            return True, '营业中'

        time_range_str = str(time_range).strip().lower()
        if time_range_str in ('closed', '已打烊', '休息', '今日休息'):
            # 明确配置为休息/打烊
            return False, '今日休息'

        if time_range_str in ('24h', '24小时', '全天', '00:00-24:00', '00:00-23:59'):
            return True, '营业中'

        try:
            # 解析时间范围，如 "08:00-22:00" 或跨天 "22:00-02:00"
            start_str, end_str = str(time_range).split('-')
            start_time = datetime.datetime.strptime(start_str.strip(), "%H:%M").time()
            end_time = datetime.datetime.strptime(end_str.strip(), "%H:%M").time()
            current_time = now.time()

            if start_time <= end_time:
                # 正常不跨天营业时间
                in_hours = start_time <= current_time <= end_time
            else:
                # 跨天营业时间处理（如：22:00 到次日 02:00）
                in_hours = current_time >= start_time or current_time <= end_time

            return in_hours, ('营业中' if in_hours else '打烊中')
        except Exception:
            # 解析格式异常等容错处理
            return False, '打烊中'

    @property
    def is_in_business_hours(self):
        """
        判断当前是否在营业时间内 (根据 business_hours JSON 字段及北京时间动态计算)
        支持配置格式：
        {
            "mon": "08:00-22:00",
            "tue": "08:00-22:00",
            "wed": "closed",
            "thu": "08:00-22:00",
            "fri": "08:00-23:00",
            "sat": "09:00-23:00",
            "sun": "09:00-22:00"
        }
        支持跨天配置（如 "22:00-02:00"）
        """
        return self._parse_business_hours_status()[0]

    @property
    def business_status_text(self):
        """返回今日营业状态提示文字：营业中 / 打烊中 / 今日休息（基于北京时间 UTC+8）"""
        return self._parse_business_hours_status()[1]

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
