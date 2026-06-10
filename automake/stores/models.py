"""
门店模型模块

门店是整个系统的核心组织单元，菜单、设备、订单均与门店关联。
"""

from django.db import models


class Store(models.Model):
    """
    门店表

    字段说明：
    - name：门店名称
    - address：地址
    - lat/lng：经纬度，用于小程序地图展示和附近门店计算
    - status：运营状态，下线门店不允许点单
    - business_hours：营业时间（JSON 格式，按星期存储）
    - contact_phone：门店联系电话
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
