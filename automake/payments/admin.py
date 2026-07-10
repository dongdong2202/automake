"""
payments/admin.py — 支付与退款后台管理

彩色状态标签：
  支付状态（status）→ 彩色徽章
  退款状态（status）→ 彩色徽章
  回调处理结果（process_result）→ 彩色徽章
"""

from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from .models import PaymentRecord, PaymentCallbackLog, RefundRecord


# ── 状态颜色映射 ──────────────────────────────────────────
PAYMENT_STATUS_BADGE = {
    'pending': ('#f59e0b', '#fffbeb', '⏳ 待支付'),
    'success': ('#10b981', '#ecfdf5', '✅ 支付成功'),
    'failed':  ('#ef4444', '#fef2f2', '❌ 支付失败'),
    'closed':  ('#6b7280', '#f9fafb', '🚫 已关闭'),
}

REFUND_STATUS_BADGE = {
    'pending': ('#f97316', '#fff7ed', '🔄 申请中'),
    'success': ('#10b981', '#ecfdf5', '✅ 已退款'),
    'failed':  ('#ef4444', '#fef2f2', '❌ 退款失败'),
}

CALLBACK_RESULT_BADGE = {
    'pending': ('#f59e0b', '#fffbeb', '⏳ 处理中'),
    'success': ('#10b981', '#ecfdf5', '✅ 成功'),
    'failed':  ('#ef4444', '#fef2f2', '❌ 失败'),
    'ignored': ('#6b7280', '#f9fafb', '⏭ 已忽略'),
}


def _badge(color, bg, label):
    return format_html(
        '<span style="display:inline-block;padding:3px 10px;border-radius:20px;'
        'font-size:12px;font-weight:600;color:{};background:{};white-space:nowrap;">'
        '{}</span>',
        color, bg, label
    )


@admin.register(PaymentRecord)
class PaymentRecordAdmin(ModelAdmin):
    """支付记录管理后台配置"""

    list_display = (
        'out_trade_no', 'order', 'user',
        'amount_display', 'status_badge', 'pay_method', 'paid_at', 'created_at'
    )
    list_filter = ('status', 'pay_method', 'created_at')
    search_fields = ('transaction_id', 'out_trade_no', 'user__username', 'order__order_no')
    readonly_fields = (
        'order', 'user', 'transaction_id', 'out_trade_no', 'amount',
        'status', 'pay_params', 'paid_at', 'pay_method', 'created_at', 'updated_at'
    )
    show_full_result_count = False

    @admin.display(description='支付状态')
    def status_badge(self, obj):
        color, bg, label = PAYMENT_STATUS_BADGE.get(
            obj.status, ('#6b7280', '#f9fafb', obj.status)
        )
        return _badge(color, bg, label)

    @admin.display(description='支付金额')
    def amount_display(self, obj):
        return format_html(
            '<span style="font-weight:600;color:#059669;">¥ {}</span>',
            f'{obj.amount / 100:.2f}'
        )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            user_stores = request.user.stores.all()
            if user_stores.exists():
                return qs.filter(order__store__in=user_stores)
            return qs.none()
        return qs


@admin.register(PaymentCallbackLog)
class PaymentCallbackLogAdmin(ModelAdmin):
    """支付回调日志管理后台配置"""

    list_display = (
        'id', 'out_trade_no', 'transaction_id',
        'process_result_badge', 'created_at'
    )
    list_filter = ('process_result', 'created_at')
    search_fields = ('out_trade_no', 'transaction_id')
    readonly_fields = (
        'out_trade_no', 'transaction_id', 'raw_body',
        'decrypted_data', 'process_result', 'process_error', 'created_at'
    )

    @admin.display(description='处理结果')
    def process_result_badge(self, obj):
        color, bg, label = CALLBACK_RESULT_BADGE.get(
            obj.process_result, ('#6b7280', '#f9fafb', obj.process_result)
        )
        return _badge(color, bg, label)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            user_stores = request.user.stores.all()
            if user_stores.exists():
                return qs.filter(
                    out_trade_no__in=PaymentRecord.objects.filter(
                        order__store__in=user_stores
                    ).values('out_trade_no')
                )
            return qs.none()
        return qs


@admin.register(RefundRecord)
class RefundRecordAdmin(ModelAdmin):
    """退款记录管理后台配置"""

    list_display = (
        'out_refund_no', 'order', 'payment',
        'refund_amount_display', 'status_badge', 'refunded_at', 'created_at'
    )
    list_filter = ('status', 'created_at')
    search_fields = ('refund_id', 'out_refund_no', 'order__order_no', 'payment__out_trade_no')
    readonly_fields = (
        'order', 'payment', 'refund_id', 'out_refund_no', 'refund_amount',
        'reason', 'status', 'refunded_at', 'created_at'
    )
    show_full_result_count = False

    @admin.display(description='退款状态')
    def status_badge(self, obj):
        color, bg, label = REFUND_STATUS_BADGE.get(
            obj.status, ('#6b7280', '#f9fafb', obj.status)
        )
        return _badge(color, bg, label)

    @admin.display(description='退款金额')
    def refund_amount_display(self, obj):
        return format_html(
            '<span style="font-weight:600;color:#dc2626;">¥ {}</span>',
            f'{obj.refund_amount / 100:.2f}'
        )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            user_stores = request.user.stores.all()
            if user_stores.exists():
                return qs.filter(order__store__in=user_stores)
            return qs.none()
        return qs
