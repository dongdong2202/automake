"""
消息通知模块视图

接口列表：
  POST /api/notify/pickup/verify/           设备扫码核销取餐码
  GET  /api/notify/order/{order_no}/status/ 查询订单当前状态与等候时间
  GET  /api/notify/events/                  获取系统通知事件列表（管理员）
  POST /api/notify/events/{id}/handle/      标记通知事件已处理（管理员）
"""

import logging
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from drf_spectacular.utils import extend_schema

from utils.response import ok, error
from orders.models import OrderMain, ProductionTask
from .services import verify_pickup_code
from .models import NotifyEvent, WxSubscribeMsg

logger = logging.getLogger(__name__)


class PickupCodeVerifyView(APIView):
    """
    扫码核销取餐码

    供设备端或后台扫码调用，核销用户的取餐码并返回订单详情。
    此接口允许设备免认证调用（AllowAny），因为设备端持有 device_sn 作为身份标识。
    生产环境建议为设备接口单独配置 device token 认证。
    """
    permission_classes = [AllowAny]

    @extend_schema(
        summary='核销取餐码',
        description='设备扫码后调用，传入取餐码，返回订单信息。成功后取餐码标记为已使用。'
    )
    def post(self, request):
        """
        POST /api/notify/pickup/verify/
        body: {"code": "123456", "device_sn": "SN001"}
        """
        code = request.data.get('code', '').strip()
        device_sn = request.data.get('device_sn', '')

        if not code:
            return error('取餐码不能为空', code=400)

        if len(code) > 8:
            return error('取餐码格式无效', code=400)

        result = verify_pickup_code(code=code, device_sn=device_sn)

        if not result['ok']:
            return error(result['reason'], code=400)

        return ok(result)


class OrderStatusQueryView(APIView):
    """
    查询订单当前状态与预计等候时间

    微信小程序轮询订单状态使用（也可配合 SSE/WebSocket，此处提供 REST 轮询版）。
    返回订单状态、状态中文描述、等候时间预估、取餐码（如已生成）。
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary='查询订单状态',
        description='小程序轮询订单状态，返回状态、等候时间估算、取餐码等信息。'
    )
    def get(self, request, order_no: str):
        """
        GET /api/notify/order/{order_no}/status/
        """
        try:
            # 用户只能查询自己的订单（防越权）
            order = OrderMain.objects.select_related('device').get(
                order_no=order_no,
                user=request.user,
            )
        except OrderMain.DoesNotExist:
            return error('订单不存在', code=404)

        # 计算等候时间预估（仅在排队中/等待制作时有意义）
        wait_minutes = _estimate_wait_minutes(order)

        # 取餐码（仅 success 状态才有）
        pickup_code_data = None
        if order.status == OrderMain.STATUS_DONE:
            try:
                pickup = order.pickup_code
                if pickup.is_valid:
                    pickup_code_data = {
                        'code': pickup.code,
                        'expires_at': pickup.expires_at.isoformat(),
                        'status': pickup.status,
                    }
                else:
                    pickup_code_data = {
                        'code': pickup.code,
                        'status': pickup.status,
                        'expired': True,
                    }
            except Exception:
                # 取餐码尚未生成（Celery 延迟或异常），返回 None，小程序稍后重试
                pass

        return ok({
            'order_no': order.order_no,
            'status': order.status,
            'status_display': order.get_status_display(),
            'wait_minutes': wait_minutes,
            'pickup_code': pickup_code_data,
            'created_at': order.created_at.isoformat(),
            'done_at': order.done_at.isoformat() if order.done_at else None,
        })


def _estimate_wait_minutes(order: OrderMain) -> int | None:
    """
    估算订单等候时间（分钟）

    算法：
      - 同一设备当前状态为 pending_dispense 或 making 的订单数量 × 2 分钟/单
      - 仅在非终态（created/pending_dispense/making）时返回估算值
      - 对于已完成或失败的订单返回 None
    """
    terminal_statuses = (
        OrderMain.STATUS_DONE,
        OrderMain.STATUS_CANCELLED,
        OrderMain.STATUS_EXCEPTION,
        OrderMain.STATUS_REFUNDED,
    )
    if order.status in terminal_statuses:
        return None

    if not order.device:
        return None

    # 查询排在当前订单之前（创建时间更早）且未完成的订单数
    queue_ahead = OrderMain.objects.filter(
        device=order.device,
        status__in=(OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING),
        created_at__lt=order.created_at,
    ).count()

    # 当前订单自身的制作时间预估 + 排队等待时间（每单约 2 分钟）
    estimated = (queue_ahead + 1) * 2
    return estimated


class NotifyEventListView(APIView):
    """
    获取系统通知事件列表（管理员专用）

    支持按 level / event_type / is_handled 过滤，默认返回最近 50 条。
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary='通知事件列表',
        description='管理员获取系统通知事件（告警、状态变更等），支持过滤。'
    )
    def get(self, request):
        user = request.user
        if not user.is_admin:
            return error('无权访问', code=403)

        qs = NotifyEvent.objects.select_related('order', 'device').order_by('-created_at')

        # 过滤参数
        level = request.query_params.get('level')
        event_type = request.query_params.get('event_type')
        is_handled = request.query_params.get('is_handled')

        if level:
            qs = qs.filter(level=level)
        if event_type:
            qs = qs.filter(event_type=event_type)
        if is_handled is not None:
            qs = qs.filter(is_handled=(is_handled.lower() == 'true'))

        # 只有超级管理员可以看到所有门店，门店管理员只看自己门店的设备相关事件
        if user.role == user.ADMIN and user.store:
            qs = qs.filter(
                device__store=user.store
            ) | qs.filter(
                order__store=user.store
            )
            qs = qs.distinct()

        events = list(qs[:50])
        data = [
            {
                'id': e.id,
                'level': e.level,
                'level_display': e.get_level_display(),
                'event_type': e.event_type,
                'event_type_display': e.get_event_type_display(),
                'title': e.title,
                'content': e.content,
                'order_no': e.order.order_no if e.order else None,
                'device_sn': e.device.device_sn if e.device else None,
                'is_handled': e.is_handled,
                'created_at': e.created_at.isoformat(),
            }
            for e in events
        ]
        return ok({'results': data, 'count': len(data)})


class NotifyEventHandleView(APIView):
    """
    标记通知事件为已处理（管理员操作）
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary='标记通知事件已处理',
        description='管理员确认处理某条告警事件后调用，更新 is_handled 为 True。'
    )
    def post(self, request, pk: int):
        user = request.user
        if not user.is_admin:
            return error('无权操作', code=403)

        try:
            event = NotifyEvent.objects.get(pk=pk)
        except NotifyEvent.DoesNotExist:
            return error('事件不存在', code=404)

        if event.is_handled:
            return ok({'message': '该事件已处理'})

        from django.utils import timezone
        event.is_handled = True
        event.handled_at = timezone.now()
        event.handled_by = user
        event.save(update_fields=['is_handled', 'handled_at', 'handled_by'])

        logger.info(f'[Notify] 通知事件已处理: id={pk}, by={user}')
        return ok({'message': '标记成功'})
