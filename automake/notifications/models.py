"""
消息通知模型模块

包含三类核心消息：
  1. WxSubscribeMsg  — 微信订阅消息发送记录（警告、状态通知、取餐码）
  2. PickupCode      — 取餐码记录（绑定到订单，线下扫码取餐）
  3. NotifyEvent     — 系统内部通知事件日志（告警、异常等）

设计原则：
  - WxSubscribeMsg 仅记录发送流水，不依赖实时在线
  - PickupCode 通过 code 字段的唯一性保证扫码幂等
  - NotifyEvent 是异常→告警→通知链路中的最终记录节点
"""

import uuid
import random
import string
from django.conf import settings
from django.db import models
from django.utils import timezone


def generate_pickup_code():
    """
    生成 6 位纯数字取餐码
    不用 UUID，方便线下口播或显示屏展示
    通过数据库 unique 约束保证唯一性；生成碰撞由服务层重试处理
    """
    return ''.join(random.choices(string.digits, k=6))


class WxSubscribeMsg(models.Model):
    """
    微信订阅消息发送记录

    微信订阅消息 API 要求用户主动授权订阅才能接收，
    此表记录每次发送请求的流水和状态，用于审计和重发。

    发送类型（msg_type）说明：
      - order_status   订单状态变更通知（制作中、已完成、取餐）
      - alert          告警消息（设备故障、物料不足等，发给管理员）
      - pickup         取餐码通知（订单完成后发给用户）
    """

    # 消息类型枚举
    TYPE_ORDER_STATUS = 'order_status'    # 订单状态通知（发给下单用户）
    TYPE_ALERT = 'alert'                  # 告警消息（发给管理员）
    TYPE_PICKUP = 'pickup'                # 取餐码通知（发给下单用户）

    TYPE_CHOICES = [
        (TYPE_ORDER_STATUS, '订单状态通知'),
        (TYPE_ALERT, '告警通知'),
        (TYPE_PICKUP, '取餐码通知'),
    ]

    # 发送状态枚举
    STATUS_PENDING = 'pending'      # 等待发送（进入 Celery 队列）
    STATUS_SUCCESS = 'success'      # 发送成功
    STATUS_FAILED = 'failed'        # 发送失败（微信接口返回错误或网络错误）
    STATUS_SKIPPED = 'skipped'      # 跳过（用户未授权订阅）

    STATUS_CHOICES = [
        (STATUS_PENDING, '等待发送'),
        (STATUS_SUCCESS, '发送成功'),
        (STATUS_FAILED, '发送失败'),
        (STATUS_SKIPPED, '已跳过'),
    ]

    # 消息接收者（可以是用户或管理员）
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='wx_subscribe_msgs',
        verbose_name='接收用户'
    )
    # 接收者的微信 openid（即使 user 被删除也保留记录）
    openid = models.CharField(max_length=128, db_index=True, verbose_name='接收者 openid')

    # 关联订单（可空，告警消息无需绑定订单）
    order = models.ForeignKey(
        'orders.OrderMain',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='wx_msgs',
        verbose_name='关联订单'
    )

    msg_type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, db_index=True, verbose_name='消息类型'
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default=STATUS_PENDING, db_index=True, verbose_name='发送状态'
    )

    # 微信订阅消息模板 ID（不同类型使用不同模板）
    template_id = models.CharField(max_length=128, verbose_name='模板 ID')

    # 实际发送给微信的 data 字段（JSON，用于追溯）
    data_payload = models.JSONField(default=dict, verbose_name='消息数据')

    # 微信接口返回的 errcode 和 errmsg（成功时 errcode=0）
    wx_errcode = models.IntegerField(null=True, blank=True, verbose_name='微信错误码')
    wx_errmsg = models.CharField(max_length=256, blank=True, verbose_name='微信错误信息')

    # Celery 任务 ID，用于追踪异步任务
    celery_task_id = models.CharField(max_length=64, blank=True, verbose_name='Celery 任务 ID')

    # 重试次数（Celery 重试机制配合使用）
    retry_count = models.SmallIntegerField(default=0, verbose_name='重试次数')

    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='创建时间')
    sent_at = models.DateTimeField(null=True, blank=True, verbose_name='成功发送时间')

    class Meta:
        db_table = 'wx_subscribe_msg'
        verbose_name = '微信订阅消息'
        verbose_name_plural = '微信订阅消息列表'
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.get_msg_type_display()}] → {self.openid} ({self.get_status_display()})'


class PickupCode(models.Model):
    """
    取餐码记录

    订单完成（制作完成）后生成，用户凭码到柜机扫码取货。

    设计要点：
      - code 字段 6 位数字，在同一时间窗口内唯一性通过 unique=True 保障
      - is_used 字段防止重复取餐
      - expires_at 设置有效期（默认 30 分钟），超时自动失效
      - scan_at 记录扫码时间，用于运营分析
    """

    # 取餐码状态
    STATUS_ACTIVE = 'active'      # 有效，可以使用
    STATUS_USED = 'used'          # 已使用
    STATUS_EXPIRED = 'expired'    # 已过期

    STATUS_CHOICES = [
        (STATUS_ACTIVE, '有效'),
        (STATUS_USED, '已使用'),
        (STATUS_EXPIRED, '已过期'),
    ]

    # 取餐码与订单一对一关联
    order = models.OneToOneField(
        'orders.OrderMain',
        on_delete=models.CASCADE,
        related_name='pickup_code',
        verbose_name='关联订单'
    )

    # 6 位数字取餐码（DB 层面 unique 保证唯一）
    code = models.CharField(
        max_length=8, unique=True,
        default=generate_pickup_code,
        db_index=True, verbose_name='取餐码'
    )

    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES,
        default=STATUS_ACTIVE, db_index=True, verbose_name='状态'
    )

    # 取餐码有效期，默认创建后 30 分钟
    expires_at = models.DateTimeField(verbose_name='过期时间')

    # 扫码取餐时间（已使用后填写）
    scanned_at = models.DateTimeField(null=True, blank=True, verbose_name='扫码时间')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='生成时间')

    class Meta:
        db_table = 'pickup_code'
        verbose_name = '取餐码'
        verbose_name_plural = '取餐码列表'
        ordering = ['-created_at']

    def __str__(self):
        return f'取餐码 {self.code} (订单 {self.order.order_no})'

    @property
    def is_valid(self) -> bool:
        """判断取餐码是否仍然有效（未使用且未过期）"""
        return self.status == self.STATUS_ACTIVE and timezone.now() < self.expires_at


class NotifyEvent(models.Model):
    """
    系统内部通知事件日志

    记录所有需要通知管理员或用户的事件，包括：
      - 设备故障告警
      - 物料不足告警
      - 订单异常告警
      - 其他系统告警

    此表是告警链路的最终记录节点，上游是 exception_event / alarm_event，
    下游是 WxSubscribeMsg（实际消息发送记录）。
    """

    # 通知级别
    LEVEL_INFO = 'info'          # 普通信息（如订单状态变更）
    LEVEL_WARNING = 'warning'    # 警告（如物料不足）
    LEVEL_CRITICAL = 'critical'  # 严重告警（如设备故障、断线）

    LEVEL_CHOICES = [
        (LEVEL_INFO, '信息'),
        (LEVEL_WARNING, '警告'),
        (LEVEL_CRITICAL, '严重告警'),
    ]

    # 事件类型
    EVENT_ORDER_STATUS = 'order_status'     # 订单状态变更
    EVENT_DEVICE_ALERT = 'device_alert'     # 设备告警
    EVENT_MATERIAL_LOW = 'material_low'     # 物料不足
    EVENT_PICKUP_READY = 'pickup_ready'     # 取餐就绪
    EVENT_SYSTEM = 'system'                 # 系统事件

    EVENT_CHOICES = [
        (EVENT_ORDER_STATUS, '订单状态'),
        (EVENT_DEVICE_ALERT, '设备告警'),
        (EVENT_MATERIAL_LOW, '物料不足'),
        (EVENT_PICKUP_READY, '取餐就绪'),
        (EVENT_SYSTEM, '系统事件'),
    ]

    level = models.CharField(
        max_length=10, choices=LEVEL_CHOICES,
        default=LEVEL_INFO, db_index=True, verbose_name='通知级别'
    )
    event_type = models.CharField(
        max_length=20, choices=EVENT_CHOICES,
        db_index=True, verbose_name='事件类型'
    )

    # 关联对象（弱关联，可为空）
    order = models.ForeignKey(
        'orders.OrderMain',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='notify_events',
        verbose_name='关联订单'
    )
    device = models.ForeignKey(
        'devices.Device',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='notify_events',
        verbose_name='关联设备'
    )

    # 事件标题和详情
    title = models.CharField(max_length=128, verbose_name='标题')
    content = models.TextField(verbose_name='内容')

    # 事件附带的原始数据（用于调试和重放）
    extra_data = models.JSONField(default=dict, blank=True, verbose_name='附加数据')

    # 是否已处理（管理员确认后标记）
    is_handled = models.BooleanField(default=False, db_index=True, verbose_name='已处理')
    handled_at = models.DateTimeField(null=True, blank=True, verbose_name='处理时间')
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='handled_notify_events',
        verbose_name='处理人'
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='发生时间')

    class Meta:
        db_table = 'notify_event'
        verbose_name = '通知事件'
        verbose_name_plural = '通知事件列表'
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.get_level_display()}] {self.title}'
