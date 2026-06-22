"""
消息通知模块 Admin 配置

在 Django 后台提供：
  - WxSubscribeMsg 微信订阅消息发送记录查看与筛选
  - PickupCode 取餐码查看与管理
  - NotifyEvent 系统通知事件查看与处理
"""

from django.contrib import admin
from django.utils import timezone
from .models import WxSubscribeMsg, PickupCode, NotifyEvent


@admin.register(WxSubscribeMsg)
class WxSubscribeMsgAdmin(admin.ModelAdmin):
    """微信订阅消息发送记录"""

    list_display = [
        'id', 'msg_type', 'openid_short', 'status',
        'wx_errcode', 'retry_count', 'created_at', 'sent_at'
    ]
    list_filter = ['msg_type', 'status', 'created_at']
    search_fields = ['openid', 'order__order_no']
    readonly_fields = ['celery_task_id', 'wx_errcode', 'wx_errmsg', 'created_at', 'sent_at']
    ordering = ['-created_at']

    def openid_short(self, obj):
        """显示 openid 前 8 位，防止列表过宽"""
        return obj.openid[:8] + '...' if obj.openid else '-'
    openid_short.short_description = 'OpenID'


@admin.register(PickupCode)
class PickupCodeAdmin(admin.ModelAdmin):
    """取餐码管理"""

    list_display = [
        'code', 'order_no', 'status', 'is_valid_display',
        'expires_at', 'scanned_at', 'created_at'
    ]
    list_filter = ['status', 'created_at']
    search_fields = ['code', 'order__order_no']
    readonly_fields = ['code', 'created_at', 'scanned_at']
    ordering = ['-created_at']

    def order_no(self, obj):
        return obj.order.order_no
    order_no.short_description = '订单号'

    def is_valid_display(self, obj):
        return obj.is_valid
    is_valid_display.boolean = True
    is_valid_display.short_description = '有效'


@admin.register(NotifyEvent)
class NotifyEventAdmin(admin.ModelAdmin):
    """系统通知事件管理"""

    list_display = [
        'id', 'level', 'event_type', 'title',
        'order_no', 'device_sn', 'is_handled', 'created_at'
    ]
    list_filter = ['level', 'event_type', 'is_handled', 'created_at']
    search_fields = ['title', 'content', 'order__order_no', 'device__device_sn']
    readonly_fields = ['created_at', 'handled_at']
    ordering = ['-created_at']
    actions = ['mark_handled']

    def order_no(self, obj):
        return obj.order.order_no if obj.order else '-'
    order_no.short_description = '订单号'

    def device_sn(self, obj):
        return obj.device.device_sn if obj.device else '-'
    device_sn.short_description = '设备 SN'

    @admin.action(description='标记为已处理')
    def mark_handled(self, request, queryset):
        queryset.update(
            is_handled=True,
            handled_at=timezone.now(),
            handled_by=request.user,
        )
        self.message_user(request, f'已标记 {queryset.count()} 条事件为已处理')
