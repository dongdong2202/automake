"""
订单模块视图

接口列表：
- POST /api/order/precheck    预校验订单（下单前调用）
- POST /api/order/create      正式创建订单
- GET  /api/order/list        查看我的订单列表
- GET  /api/order/{order_no}  查看订单详情
"""

import logging
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from utils.response import ok, error
from .models import OrderMain
from .serializers import (
    CreateOrderSerializer, OrderDetailSerializer,
    OrderListSerializer
)
from .services import precheck_order, create_order

logger = logging.getLogger(__name__)


class OrderPrecheckView(APIView):
    """
    预校验订单接口

    POST /api/order/precheck
    在用户点击"去结算"时调用，返回可售结果和价格汇总。
    校验通过后，前端展示确认页面，用户确认后再调用 /api/order/create。
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        
        serializer = CreateOrderSerializer(data=request.data)

        if not serializer.is_valid():
            return error(str(serializer.errors), code=4001)

        store_id = serializer.validated_data['store_id']
        items_data = serializer.validated_data['items']
        
        print(store_id, items_data)
        
        try:
            result = precheck_order(store_id, items_data)
        except ValueError as e:
            return error(str(e), code=4002)

        return ok({
            'store_id': store_id,
            'total_amount': result['total_amount'],
            'pay_amount': result['pay_amount'],
            'items': [
                {
                    'item_name': item['item_name'],
                    'sku_name': ", ".join(item['sku_names']) if item['sku_names'] else '常规',
                    'unit_price': item['unit_price'],
                    'quantity': item['quantity'],
                    'subtotal': item['subtotal'],
                }
                for item in result['items']
            ],
        }, message='预校验通过')


class OrderCreateView(APIView):
    """
    创建订单接口

    POST /api/order/create
    依赖预校验已通过（服务端会再次校验）。
    成功后返回 order_no，前端凭此调用支付接口。
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CreateOrderSerializer(data=request.data)
        if not serializer.is_valid():
            return error(str(serializer.errors), code=4001)

        store_id = serializer.validated_data['store_id']
        items_data = serializer.validated_data['items']
        remark = serializer.validated_data.get('remark', '')

        try:
            order = create_order(
                user=request.user,
                store_id=store_id,
                items_data=items_data,
                remark=remark,
            )
        except ValueError as e:
            return error(str(e), code=4003)
        except Exception as e:
            logger.exception(f'创建订单异常: {e}')
            return error('创建订单失败，请稍后重试', code=4004, status=500)

        return ok({
            'order_no': order.order_no,
            'pay_amount': order.pay_amount,
            'status': order.status,
        }, message='下单成功')


class OrderListView(APIView):
    """
    我的订单列表

    GET /api/order/list
    返回当前登录用户的所有订单，按创建时间倒序。
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        orders = (
            OrderMain.objects
            .filter(user=request.user)
            .prefetch_related('items')
            .order_by('-created_at')
        )
        serializer = OrderListSerializer(orders, many=True)
        return ok(serializer.data)


class OrderDetailView(APIView):
    """
    订单详情

    GET /api/order/{order_no}
    只允许查看自己的订单（防止越权）。
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, order_no):
        try:
            order = (
                OrderMain.objects
                .prefetch_related('items', 'status_logs')
                .get(order_no=order_no, user=request.user)  # 用户隔离：只能查自己的
            )
        except OrderMain.DoesNotExist:
            return error('订单不存在', code=4005, status=404)

        serializer = OrderDetailSerializer(order)
        return ok(serializer.data)


class OrderCancelView(APIView):
    """
    取消订单接口

    POST /api/order/{order_no}/cancel
    允许用户或系统手动取消待支付订单，取消时会自动释放锁定的设备物料库存。
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, order_no):
        try:
            order = OrderMain.objects.get(order_no=order_no, user=request.user)
        except OrderMain.DoesNotExist:
            return error('订单不存在', code=4005, status=404)

        from .services import cancel_order
        try:
            cancel_order(order, operator='user', remark=request.data.get('remark', '用户主动取消'))
        except ValueError as e:
            return error(str(e), code=4006)
        except Exception as e:
            logger.exception(f'取消订单异常: {e}')
            return error('取消订单失败，请稍后重试', code=4007, status=500)

        return ok(None, message='订单已成功取消')
