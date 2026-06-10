"""
订单模块序列化器
"""

from rest_framework import serializers
from .models import OrderMain, OrderItem, OrderStatusLog


class OrderItemInputSerializer(serializers.Serializer):
    """
    下单时的商品输入格式

    每个 item 对应购物车中的一条记录：
    { "sku_id": 1, "quantity": 2 }
    或无规格商品：
    { "item_id": 1, "quantity": 1 }
    """
    item_id = serializers.IntegerField(required=False)
    sku_id = serializers.IntegerField(required=False)
    quantity = serializers.IntegerField(min_value=1, max_value=99)

    def validate(self, attrs):
        # item_id 和 sku_id 至少要有一个
        if not attrs.get('item_id') and not attrs.get('sku_id'):
            raise serializers.ValidationError('item_id 和 sku_id 至少填一个')
        return attrs


class CreateOrderSerializer(serializers.Serializer):
    """
    创建订单请求序列化器

    请求体示例：
    {
        "store_id": 1,
        "items": [
            {"sku_id": 3, "quantity": 1},
            {"sku_id": 5, "quantity": 2}
        ],
        "remark": "少糖"
    }
    """
    store_id = serializers.IntegerField()
    items = OrderItemInputSerializer(many=True, min_length=1)
    remark = serializers.CharField(required=False, allow_blank=True, max_length=256)


class OrderItemSerializer(serializers.ModelSerializer):
    """订单明细序列化器（用于展示）"""

    class Meta:
        model = OrderItem
        fields = ['id', 'item_name', 'sku_name', 'unit_price', 'quantity', 'subtotal']


class OrderStatusLogSerializer(serializers.ModelSerializer):
    """订单状态日志序列化器"""

    class Meta:
        model = OrderStatusLog
        fields = ['from_status', 'to_status', 'operator', 'remark', 'created_at']


class OrderDetailSerializer(serializers.ModelSerializer):
    """订单详情序列化器（含明细和状态历史）"""
    items = OrderItemSerializer(many=True, read_only=True)
    status_logs = OrderStatusLogSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = OrderMain
        fields = [
            'id', 'order_no', 'status', 'status_display',
            'total_amount', 'discount_amount', 'pay_amount',
            'remark', 'paid_at', 'done_at', 'created_at',
            'items', 'status_logs',
        ]


class OrderListSerializer(serializers.ModelSerializer):
    """订单列表序列化器（精简字段）"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = OrderMain
        fields = [
            'id', 'order_no', 'status', 'status_display',
            'pay_amount', 'item_count', 'created_at',
        ]

    def get_item_count(self, obj):
        """统计订单总商品数量"""
        return sum(item.quantity for item in obj.items.all())
