"""
订单模块视图 (orders.views)

接口列表：
- POST /api/order/precheck          预校验订单（下单前计算价格与库存可用性）
- POST /api/order/create            正式创建订单
- GET  /api/order/list              查看当前登录用户的历史订单列表
- GET  /api/order/{order_no}        查看订单详情
- POST /api/order/{order_no}/cancel 取消待支付订单
- GET  /api/order/{order_no}/invoice 查看电子发票
- POST /api/order/{order_no}/invoice 申请开具电子发票
"""

import logging
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.authentication import SessionAuthentication
from rest_framework.throttling import UserRateThrottle
from users.authentication import OptionalJWTAuthentication, UnifiedOrderAuthentication

from utils.response import ok, error
from .models import OrderMain
from .serializers import (
    CreateOrderSerializer, OrderDetailSerializer,
    OrderListSerializer
)
from .services import precheck_order, create_order

logger = logging.getLogger(__name__)


class OrderRateThrottle(UserRateThrottle):
    """下单频率限制器，防止恶意刷单"""
    scope = "order"


def _get_user_order(user, order_no: str, prefetch_related: list = None) -> OrderMain:
    """
    内部辅助函数：获取指定用户的特定订单（严格隔离用户数据，防止越权访问）

    Args:
        user: 当前登录用户
        order_no: 订单编号 (order_no)
        prefetch_related: 可选的预加载反向关联字段列表

    Returns:
        OrderMain: 对应的订单模型对象

    Raises:
        OrderMain.DoesNotExist: 当订单不存在或属于其他用户时抛出
    """
    qs = OrderMain.objects.filter(order_no=order_no, user=user)
    if prefetch_related:
        qs = qs.prefetch_related(*prefetch_related)
    order = qs.first()
    if not order:
        raise OrderMain.DoesNotExist(f"订单 {order_no} 不存在或无权访问")
    return order


class OrderPrecheckView(APIView):
    """
    预校验订单接口

    POST /api/order/precheck
    在用户点击"去结算"或上位机选品时调用，返回可售结果和物料余量比对。
    校验通过后，前端展示确认页面，用户确认后再调用 /api/order/create。
    开放查询权限（AllowAny），同时兼容顾客用户 JWT 与上位机终端设备 Token。
    """
    authentication_classes = [UnifiedOrderAuthentication, SessionAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [OrderRateThrottle]

    def post(self, request):
        serializer = CreateOrderSerializer(data=request.data)
        user_id = getattr(request.user, 'id', None)
        if not serializer.is_valid():
            logger.warning(f"用户/客户端 {user_id} 预校验订单参数错误: {serializer.errors}")
            return error(str(serializer.errors), code=4001)

        store_id = serializer.validated_data['store_id']
        items_data = serializer.validated_data['items']
        device_sn = serializer.validated_data.get('device_sn') or request.data.get('device_sn')

        logger.info(f"用户/客户端 {user_id} 预校验订单: store_id={store_id}, device_sn={device_sn}, items_count={len(items_data)}")

        try:
            result = precheck_order(store_id, items_data, device_sn=device_sn)
            logger.debug(f"precheck_order {result}")
        except ValueError as e:
            logger.warning(f"用户/客户端 {user_id} 预校验失败: {e}")
            material_checks = getattr(e, 'material_checks', None)
            return error(str(e), code=4002, data={'material_checks': material_checks} if material_checks else None)

        logger.debug(f"用户/客户端 {user_id} 预校验成功，返回支付金额: {result['pay_amount']}")
        return ok({
            'store_id': store_id,
            'device_sn': result['device'].device_sn if result.get('device') else device_sn,
            'total_amount': result['total_amount'],
            'pay_amount': result['pay_amount'],
            'material_checks': result.get('material_checks', []),
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
    依赖预校验已通过（服务端会再次原子校验）。
    成功后返回 order_no，前端凭此调用支付接口。
    原生兼容顾客用户 JWT 与上位机触控终端设备 Token。
    """
    authentication_classes = [UnifiedOrderAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [OrderRateThrottle]

    def post(self, request):
        serializer = CreateOrderSerializer(data=request.data)
        user_id = getattr(request.user, 'id', None)
        if not serializer.is_valid():
            logger.warning(f"用户/客户端 {user_id} 创建订单参数错误: {serializer.errors}")
            return error(str(serializer.errors), code=4001)

        store_id = serializer.validated_data['store_id']
        items_data = serializer.validated_data['items']
        remark = serializer.validated_data.get('remark', '')
        device_sn = (
            serializer.validated_data.get('device_sn') or
            request.data.get('device_sn') or
            getattr(getattr(request, 'device', None), 'device_sn', None)
        )

        logger.info(f"用户/客户端 {user_id} 发起创建订单: store_id={store_id}, device_sn={device_sn}")

        try:
            order = create_order(
                user=request.user,
                store_id=store_id,
                items_data=items_data,
                remark=remark,
                device_sn=device_sn,
            )
        except ValueError as e:
            logger.warning(f"用户/客户端 {user_id} 创建订单业务校验失败: {e}")
            return error(str(e), code=4003)
        except Exception as e:
            logger.exception(f'创建订单系统异常: {e}')
            return error('创建订单失败，请稍后重试', code=4004, status=500)

        logger.info(f"用户/客户端 {user_id} 下单成功: order_no={order.order_no}, pay_amount={order.pay_amount}")
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
            order = _get_user_order(request.user, order_no, prefetch_related=['items', 'status_logs'])
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
            order = _get_user_order(request.user, order_no)
        except OrderMain.DoesNotExist:
            return error('订单不存在', code=4005, status=404)

        from .services import cancel_order
        try:
            cancel_order(order, operator='user', remark=request.data.get('remark', '用户主动取消'))
            logger.info(f"用户 {request.user.id} 成功取消订单: order_no={order_no}")
        except ValueError as e:
            logger.warning(f"取消订单失败: order_no={order_no}, error={e}")
            return error(str(e), code=4006)
        except Exception as e:
            logger.exception(f'取消订单系统异常: {e}')
            return error('取消订单失败，请稍后重试', code=4007, status=500)

        return ok(None, message='订单已成功取消')


class OrderInvoiceView(APIView):
    """
    电子发票申请与查询接口

    POST /api/order/<order_no>/invoice   申请开具电子发票
    GET  /api/order/<order_no>/invoice   查询开票记录
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, order_no):
        try:
            order = _get_user_order(request.user, order_no)
        except OrderMain.DoesNotExist:
            return error('订单不存在', code=4005, status=404)

        invoice = getattr(order, 'invoice', None)
        if not invoice:
            return ok(None, message='该订单暂未申请开票')

        return ok({
            'order_no': order.order_no,
            'invoice_type': invoice.invoice_type,
            'title': invoice.title,
            'tax_no': invoice.tax_no,
            'email': invoice.email,
            'amount': invoice.amount,
            'status': invoice.status,
            'status_display': invoice.get_status_display(),
            'invoice_url': invoice.invoice_url or f"https://tinylab.store/media/invoices/{order_no}.pdf",
            'created_at': invoice.created_at.isoformat()
        })

    def post(self, request, order_no):
        try:
            order = _get_user_order(request.user, order_no)
        except OrderMain.DoesNotExist:
            return error('订单不存在', code=4005, status=404)

        if order.status not in (OrderMain.STATUS_DONE, OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING):
            return error('仅已支付或已完成的订单支持申请开票', code=4008)

        from .models import OrderInvoice
        if hasattr(order, 'invoice'):
            return error('该订单已申请过发票，请勿重复提交', code=4009)

        invoice_type = request.data.get('invoice_type', OrderInvoice.TYPE_PERSONAL)
        title = request.data.get('title', '').strip()
        tax_no = request.data.get('tax_no', '').strip()
        email = request.data.get('email', '').strip()

        if not title:
            return error('发票抬头不能为空', code=4010)
        if invoice_type == OrderInvoice.TYPE_COMPANY and not tax_no:
            return error('企业单位开票必须填写企业税号', code=4011)
        if not email or '@' not in email:
            return error('请输入有效的电子发票接收邮箱', code=4012)

        invoice = OrderInvoice.objects.create(
            order=order,
            user=request.user,
            invoice_type=invoice_type,
            title=title,
            tax_no=tax_no,
            email=email,
            amount=order.pay_amount,
            status=OrderInvoice.STATUS_ISSUED,
            invoice_url=f"https://tinylab.store/media/invoices/{order_no}.pdf"
        )
        logger.info(f"用户 {request.user.id} 申请开具电子发票成功: order_no={order_no}, invoice_id={invoice.id}")

        return ok({
            'order_no': order.order_no,
            'title': invoice.title,
            'amount': invoice.amount,
            'status': invoice.status,
            'status_display': invoice.get_status_display(),
            'invoice_url': invoice.invoice_url
        }, message='电子发票申请成功，已发送至您的邮箱')


class OrderPendingCheckView(APIView):
    """
    检查订单是否处于等待制作状态接口
    """
    permission_classes = [AllowAny]
    throttle_classes = []

    def get(self, request):
        return self._process_check(request)

    def post(self, request):
        return self._process_check(request)

    def _process_check(self, request):
        import time
        from django.db.models import Q
        from rest_framework.response import Response
        from devices.models import Device
        from orders.models import ProductionTask

        def build_resp(is_pending: bool, msg: str):
            return Response({
                "code": 1 if is_pending else 0,
                "msg": msg,
                "data": {},
                "ts": int(time.time() * 1000),
            })

        data = request.data if isinstance(request.data, dict) else {}
        params = request.query_params

        device_sn = (
            params.get('device_sn') or data.get('device_sn') or
            params.get('sn') or data.get('sn') or
            params.get('device_id') or data.get('device_id') or ''
        )
        if isinstance(device_sn, str):
            device_sn = device_sn.strip()

        order_no = (
            params.get('order_no') or data.get('order_no') or
            params.get('orderNo') or data.get('orderNo') or
            params.get('order_token') or data.get('order_token') or
            params.get('order_id') or data.get('order_id') or ''
        )
        if isinstance(order_no, str):
            order_no = order_no.strip()

        if not device_sn:
            return build_resp(False, "缺少设备编号参数 (device_sn)")
        if not order_no:
            return build_resp(False, "缺少订单号参数 (order_no)")

        device = Device.objects.filter(device_sn=device_sn).first()
        if not device:
            return build_resp(False, f"设备 {device_sn} 不存在")

        order = OrderMain.objects.filter(
            Q(order_no=order_no) | Q(order_token=order_no)
        ).select_related('device', 'store', 'production_task').first()

        if not order:
            return build_resp(False, f"订单 {order_no} 不存在")

        if order.device:
            if order.device.device_sn != device_sn:
                return build_resp(
                    False,
                    f"订单 {order.order_no} 制作设备为 {order.device.device_sn}，与当前查询设备 {device_sn} 不一致"
                )
        elif order.store_id and device.store_id and order.store_id != device.store_id:
            return build_resp(
                False,
                f"订单 {order.order_no} 所属门店与设备 {device_sn} 所在门店不匹配"
            )

        if order.status == OrderMain.STATUS_PAID:
            task = getattr(order, 'production_task', None)
            if task and task.status == ProductionTask.TASK_MAKING:
                return build_resp(False, "订单当前正在制作中")
            elif task and task.status == ProductionTask.TASK_DONE:
                return build_resp(False, "订单已制作完成并出货")
            elif task and task.status == ProductionTask.TASK_FAILED:
                reason = task.failure_reason or '制作失败'
                return build_resp(False, f"订单制作失败: {reason}")
            return build_resp(True, "订单处于等待制作状态")

        elif order.status == OrderMain.STATUS_PENDING_PAY:
            return build_resp(False, "订单尚未支付（处于待支付状态）")
        elif order.status == OrderMain.STATUS_MAKING:
            return build_resp(False, "订单当前正在制作中")
        elif order.status == OrderMain.STATUS_DONE:
            return build_resp(False, "订单已制作完成并出货成功")
        elif order.status == OrderMain.STATUS_CANCELLED:
            return build_resp(False, "订单已被取消")
        elif order.status == OrderMain.STATUS_REFUNDING:
            return build_resp(False, "订单处于退款处理中")
        elif order.status == OrderMain.STATUS_REFUNDED:
            return build_resp(False, "订单已退款")
        elif order.status == OrderMain.STATUS_EXCEPTION:
            return build_resp(False, "订单出货失败/异常")

        return build_resp(False, f"订单状态异常: {order.status}")

