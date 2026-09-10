"""
orders/admin.py — 订单与生产任务后台管理

彩色状态标签：
  订单状态（status）→ 彩色徽章
  生产任务状态（status）→ 彩色徽章
"""

from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from .models import OrderMain, OrderItem, OrderStatusLog, ProductionTask


# ── 状态颜色映射 ──────────────────────────────────────────
ORDER_STATUS_BADGE = {
    'pending_payment': ('#f59e0b', '#fffbeb', '⏳ 待支付'),
    'paid':            ('#3b82f6', '#eff6ff', '💳 已支付'),
    'producing':       ('#8b5cf6', '#f5f3ff', '⚙️ 制作中'),
    'done':            ('#10b981', '#ecfdf5', '✅ 已完成'),
    'cancelled':       ('#6b7280', '#f9fafb', '🚫 已取消'),
    'refunding':       ('#f97316', '#fff7ed', '🔄 退款中'),
    'refunded':        ('#06b6d4', '#ecfeff', '💰 已退款'),
    'exception':       ('#ef4444', '#fef2f2', '🔴 异常'),
}

TASK_STATUS_BADGE = {
    'pending':   ('#f59e0b', '#fffbeb', '⏳ 待下发'),
    'sent':      ('#3b82f6', '#eff6ff', '📤 已下发'),
    'producing': ('#8b5cf6', '#f5f3ff', '⚙️ 制作中'),
    'done':      ('#10b981', '#ecfdf5', '✅ 已完成'),
    'failed':    ('#ef4444', '#fef2f2', '❌ 失败'),
    'cancelled': ('#6b7280', '#f9fafb', '🚫 已取消'),
}


def _badge(color, bg, label):
    """生成统一样式的彩色徽章 HTML"""
    return format_html(
        '<span style="display:inline-block;padding:3px 10px;border-radius:20px;'
        'font-size:12px;font-weight:600;color:{};background:{};white-space:nowrap;">'
        '{}</span>',
        color, bg, label
    )


class OrderItemInline(TabularInline):
    """订单商品明细内联展示"""
    model = OrderItem
    extra = 0
    readonly_fields = ('item', 'sku', 'item_name', 'sku_name', 'unit_price', 'quantity', 'subtotal')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class OrderStatusLogInline(TabularInline):
    """订单状态流转历史内联展示"""
    model = OrderStatusLog
    extra = 0
    readonly_fields = ('from_status', 'to_status', 'operator', 'remark', 'created_at')
    can_delete = False
    ordering = ('created_at',)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(OrderMain)
class OrderMainAdmin(ModelAdmin):
    """订单主表管理后台配置"""

    list_display = (
        'order_no', 'user', 'store', 'device',
        'status_badge', 'pay_amount_display', 'paid_at', 'created_at'
    )
    list_filter = ('status', 'store', 'created_at')
    search_fields = ('order_no', 'order_token', 'user__username', 'user__openid')
    readonly_fields = (
        'order_no', 'order_token', 'user', 'store', 'device',
        'total_amount', 'discount_amount', 'pay_amount', 'remark',
        'paid_at', 'done_at', 'created_at', 'updated_at'
    )
    inlines = [OrderItemInline, OrderStatusLogInline]
    actions = ['action_auto_refund', 'action_force_refund']
    date_hierarchy = 'created_at'
    show_full_result_count = False

    @admin.display(description='订单状态')
    def status_badge(self, obj):
        color, bg, label = ORDER_STATUS_BADGE.get(
            obj.status, ('#6b7280', '#f9fafb', obj.status)
        )
        return _badge(color, bg, label)

    @admin.display(description='实付金额')
    def pay_amount_display(self, obj):
        if obj.pay_amount:
            return format_html(
                '<span style="font-weight:600;color:#059669;">¥ {}</span>',
                f'{obj.pay_amount / 100:.2f}'
            )
        return '—'

    @admin.action(description='自动退款（未制作，放库存，自动退款）')
    def action_auto_refund(self, request, queryset):
        from django.contrib import messages
        from orders.services import restore_order_inventory
        from payments.services import refund_order

        success_count = 0
        for order in queryset:
            if order.status == OrderMain.STATUS_DONE:
                self.message_user(request, f'订单 {order.order_no} 已制作完成，物料已被物理消耗，无法使用自动退款，请使用【强制退款】', level=messages.WARNING)
                continue
            if order.status in [OrderMain.STATUS_REFUNDED, OrderMain.STATUS_REFUNDING]:
                self.message_user(request, f'订单 {order.order_no} 已处于退款状态，跳过', level=messages.WARNING)
                continue
            try:
                restore_order_inventory(order, operator=request.user.username, reason=f'后台批量自动退款放库')
                refund_order(order, reason=f'[自动退款] 管理员 {request.user.username} 批量操作')
                success_count += 1
            except Exception as e:
                self.message_user(request, f'订单 {order.order_no} 自动退款失败: {e}', level=messages.ERROR)

        if success_count > 0:
            self.message_user(request, f'成功对 {success_count} 笔未制作订单执行自动退款并释放库存', level=messages.SUCCESS)

    @admin.action(description='强制退款（不退库存，客诉或制作失败）')
    def action_force_refund(self, request, queryset):
        from django.contrib import messages
        from payments.services import refund_order
        from orders.models import ProductionTask

        success_count = 0
        for order in queryset:
            if order.status in [OrderMain.STATUS_REFUNDED, OrderMain.STATUS_REFUNDING]:
                self.message_user(request, f'订单 {order.order_no} 已处于退款状态，跳过', level=messages.WARNING)
                continue
            try:
                ProductionTask.objects.filter(
                    order=order,
                    status__in=[ProductionTask.TASK_PENDING, ProductionTask.TASK_SENT, ProductionTask.TASK_MAKING]
                ).update(status=ProductionTask.TASK_FAILED, failure_reason=f'强制退款: 管理员 {request.user.username}')
                refund_order(order, reason=f'[强制退款] 管理员 {request.user.username} 批量操作(不退库存)')
                success_count += 1
            except Exception as e:
                self.message_user(request, f'订单 {order.order_no} 强制退款失败: {e}', level=messages.ERROR)

        if success_count > 0:
            self.message_user(request, f'成功对 {success_count} 笔订单执行强制退款（未归还物料库存）', level=messages.SUCCESS)


@admin.register(ProductionTask)
class ProductionTaskAdmin(ModelAdmin):
    """设备生产/出货任务管理后台配置"""

    list_display = (
        'id', 'order', 'device', 'status_badge',
        'sent_at', 'done_at', 'created_at'
    )
    list_filter = ('status', 'device', 'created_at')
    search_fields = ('order__order_no', 'order__order_token', 'device__device_sn')
    readonly_fields = (
        'order', 'device', 'status', 'command_payload',
        'failure_reason', 'sent_at', 'done_at', 'created_at', 'updated_at'
    )
    show_full_result_count = False

    @admin.display(description='任务状态')
    def status_badge(self, obj):
        color, bg, label = TASK_STATUS_BADGE.get(
            obj.status, ('#6b7280', '#f9fafb', obj.status)
        )
        return _badge(color, bg, label)
