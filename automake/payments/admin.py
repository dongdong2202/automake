from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import PaymentRecord, PaymentCallbackLog, RefundRecord


@admin.register(PaymentRecord)
class PaymentRecordAdmin(ModelAdmin):
    """
    支付记录管理后台配置
    """
    list_display = (
        'id', 'order', 'user', 'transaction_id', 'out_trade_no',
        'amount_display', 'status', 'pay_method', 'paid_at', 'created_at'
    )
    list_filter = ('status', 'pay_method', 'created_at')
    search_fields = ('transaction_id', 'out_trade_no', 'user__username', 'order__order_no')
    readonly_fields = (
        'order', 'user', 'transaction_id', 'out_trade_no', 'amount',
        'status', 'pay_params', 'paid_at', 'pay_method', 'created_at', 'updated_at'
    )

    def amount_display(self, obj):
        return f"{obj.amount / 100:.2f} 元"
    amount_display.short_description = "支付金额"

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
    """
    支付回调日志管理后台配置
    """
    list_display = ('id', 'out_trade_no', 'transaction_id', 'process_result', 'created_at')
    list_filter = ('process_result', 'created_at')
    search_fields = ('out_trade_no', 'transaction_id')
    readonly_fields = (
        'out_trade_no', 'transaction_id', 'raw_body',
        'decrypted_data', 'process_result', 'process_error', 'created_at'
    )

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
                return qs.filter(out_trade_no__in=PaymentRecord.objects.filter(order__store__in=user_stores).values('out_trade_no'))
            return qs.none()
        return qs


@admin.register(RefundRecord)
class RefundRecordAdmin(ModelAdmin):
    """
    退款记录管理后台配置
    """
    list_display = (
        'id', 'order', 'payment', 'refund_id', 'out_refund_no',
        'refund_amount_display', 'status', 'refunded_at', 'created_at'
    )
    list_filter = ('status', 'created_at')
    search_fields = ('refund_id', 'out_refund_no', 'order__order_no', 'payment__out_trade_no')
    readonly_fields = (
        'order', 'payment', 'refund_id', 'out_refund_no', 'refund_amount',
        'reason', 'status', 'refunded_at', 'created_at'
    )

    def refund_amount_display(self, obj):
        return f"{obj.refund_amount / 100:.2f} 元"
    refund_amount_display.short_description = "退款金额"

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
