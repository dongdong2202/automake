from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline
from .models import OrderMain, OrderItem, OrderStatusLog, ProductionTask


class OrderItemInline(TabularInline):
    """
    订单商品明细内联展示
    """
    model = OrderItem
    extra = 0
    readonly_fields = ('item', 'sku', 'item_name', 'sku_name', 'unit_price', 'quantity', 'subtotal')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class OrderStatusLogInline(TabularInline):
    """
    订单状态流转历史内联展示
    """
    model = OrderStatusLog
    extra = 0
    readonly_fields = ('from_status', 'to_status', 'operator', 'remark', 'created_at')
    can_delete = False
    ordering = ('created_at',)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(OrderMain)
class OrderMainAdmin(ModelAdmin):
    """
    订单主表管理后台配置
    """
    list_display = (
        'id', 'order_no', 'order_token', 'user', 'store', 
        'device', 'status', 'pay_amount', 'paid_at', 'created_at'
    )
    list_filter = ('status', 'store', 'created_at')
    search_fields = ('order_no', 'order_token', 'user__username', 'user__openid')
    readonly_fields = (
        'order_no', 'order_token', 'user', 'store', 'device', 
        'total_amount', 'discount_amount', 'pay_amount', 'remark', 
        'paid_at', 'done_at', 'created_at', 'updated_at'
    )
    inlines = [OrderItemInline, OrderStatusLogInline]


@admin.register(ProductionTask)
class ProductionTaskAdmin(ModelAdmin):
    """
    设备生产/出货任务管理后台配置
    """
    list_display = ('id', 'order', 'device', 'status', 'sent_at', 'done_at', 'created_at')
    list_filter = ('status', 'device', 'created_at')
    search_fields = ('order__order_no', 'order__order_token', 'device__device_sn')
    readonly_fields = (
        'order', 'device', 'status', 'command_payload', 
        'failure_reason', 'sent_at', 'done_at', 'created_at', 'updated_at'
    )
