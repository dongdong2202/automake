"""
后台订单管理视图 (admin_api.views.orders)

接口列表：
- GET  /api/admin/orders/                 订单分页列表查询（支持状态、门店、时间范围与单号模糊搜索）
- GET  /api/admin/orders/<order_no>/      订单详情查询（包含订单商品与状态流转历史）
- POST /api/admin/orders/<order_no>/refund/ 管理员手动对订单发起退款
"""

import logging
import threading
from rest_framework.views import APIView
from utils.permissions import IsAdmin
from utils.response import ok, error
from orders.models import OrderMain, OrderStatusLog
from payments.services import refund_order
from ..serializers import OrderAdminSerializer
from ..filters import StandardPagination

logger = logging.getLogger(__name__)


class OrderListView(APIView):
    """
    订单列表管理接口

    GET /api/admin/orders/
    支持门店权限隔离：超级管理员可查看全部门店订单，普通管理员仅能查看管辖门店订单。
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        user = request.user
        logger.debug(f"[AdminOrderList] 管理员 {user.username} (ID:{user.id}) 查询订单列表")
        qs = (
            OrderMain.objects.all()
            .select_related('store', 'device', 'pickup_code')
            .prefetch_related('items')
            .order_by('-created_at')
        )

        if not user.is_super_admin:
            qs = qs.filter(store_id__in=user.stores.values_list('id', flat=True))

        store_id = request.query_params.get('store_id')
        status_filter = request.query_params.get('status')
        order_no = request.query_params.get('order_no', '').strip()
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')

        if store_id:
            qs = qs.filter(store_id=store_id)
        if status_filter:
            qs = qs.filter(status=status_filter)
        if order_no:
            qs = qs.filter(order_no__icontains=order_no)
        if start_date:
            qs = qs.filter(created_at__date__gte=start_date)
        if end_date:
            qs = qs.filter(created_at__date__lte=end_date)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = OrderAdminSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class OrderDetailView(APIView):
    """
    订单详情查询接口

    GET /api/admin/orders/<str:order_no>/
    返回订单详细信息及所有状态流转日志 (status_logs)
    """
    permission_classes = [IsAdmin]

    def get(self, request, order_no):
        logger.debug(f"[AdminOrderDetail] 查询订单详情: order_no={order_no}")
        order = OrderMain.objects.filter(order_no=order_no).select_related(
            'store', 'device', 'pickup_code'
        ).prefetch_related('items', 'status_logs').first()

        if not order:
            logger.warning(f"[AdminOrderDetail] 订单不存在: order_no={order_no}")
            return error('订单不存在', code=4041)

        if not request.user.is_super_admin and not request.user.stores.filter(id=order.store_id).exists():
            logger.warning(f"[AdminOrderDetail] 无权查看该订单: order_no={order_no}, user={request.user.username}")
            return error('无权查看该订单', code=4031)

        data = OrderAdminSerializer(order).data
        # 补充履约流转时间线日志
        data['status_logs'] = [
            {
                'id': log.id,
                'action': log.action,
                'action_name': log.action_name,
                'from_status': log.from_status,
                'from_status_display': log.from_status_display,
                'to_status': log.to_status,
                'to_status_display': log.to_status_display,
                'status_flow_display': log.status_flow_display,
                'operator_type': log.operator_type,
                'operator': log.operator,
                'remark': log.remark,
                'pay_method': (log.payload or {}).get('pay_method', ''),
                'pay_method_display': (log.payload or {}).get('pay_method_display', ''),
                'payload': log.payload or {},
                'created_at': log.created_at.isoformat()
            }
            for log in order.status_logs.all().order_by('created_at')
        ]
        return ok(data)


def _get_admin_order_for_refund(request, order_no: str):
    """退款前置鉴权与订单状态校验（提炼共用，避免冗余）"""
    order = OrderMain.objects.filter(order_no=order_no).first()
    if not order:
        logger.warning(f"[AdminOrderRefund] 退款订单不存在: order_no={order_no}")
        return None, error('订单不存在', code=4041)

    if not request.user.is_super_admin and not request.user.stores.filter(id=order.store_id).exists():
        logger.warning(f"[AdminOrderRefund] 无权操作该订单退款: order_no={order_no}, user={request.user.username}")
        return None, error('无权操作该订单', code=4031)

    if order.status in [OrderMain.STATUS_REFUNDED, OrderMain.STATUS_REFUNDING]:
        return None, error('该订单已处于退款或退款中状态，请勿重复操作', code=4004)

    return order, None


def _async_execute_auto_refund(order_id: int, admin_username: str, reason: str, funds_account: str = None, status_mode: str = 'paid'):
    """
    后台异步执行自动退款全流程，并将详细轨迹与每一步状态写入履约流转时间线（零 HTTP 阻塞）
    """
    from orders.models import OrderMain, OrderStatusLog, ProductionTask
    from orders.services import record_order_timeline, restore_order_inventory
    from payments.models import PaymentRecord, get_pay_method_display

    try:
        order = OrderMain.objects.filter(id=order_id).select_related('device').first()
        if not order:
            logger.error(f"[AsyncAutoRefund] 未找到订单: id={order_id}")
            return

        payment = PaymentRecord.objects.filter(order=order, status=PaymentRecord.STATUS_SUCCESS).first()
        pay_method_str = getattr(payment, 'pay_method', 'wechat_jsapi') if payment else ''
        pay_method_text = get_pay_method_display(pay_method_str) if payment else '微信支付'

        # 情况 2：制作中 (STATUS_MAKING)，先向下位机下发 MQTT cancel 并阻塞等待应答
        if status_mode == 'making':
            logger.info(f"[AsyncAutoRefund] 开始向下位机发送 MQTT cancel 确认停机: order_no={order.order_no}")
            if order.device:
                from mqtt import issue_cancel_command_with_ack
                is_ok, msg = issue_cancel_command_with_ack(
                    device_sn=order.device.device_sn,
                    order_no=order.order_no,
                    reason=reason,
                    timeout=5.0
                )
                if not is_ok:
                    logger.warning(f"[AsyncAutoRefund] 上位机拒绝取消或响应超时: order_no={order.order_no}, msg={msg}")
                    record_order_timeline(
                        order=order,
                        action=OrderStatusLog.ACTION_REFUND_FAILED,
                        action_name='自动退款被拒',
                        from_status=OrderMain.STATUS_MAKING,
                        to_status=OrderMain.STATUS_MAKING,
                        operator_type=OrderStatusLog.OP_DEVICE,
                        operator=order.device.device_sn,
                        remark=f'上位机拒绝取消或响应超时 ({msg})，自动退款中止，设备继续制作。若需强退请使用【强制退款】',
                        payload={
                            'reason': reason,
                            'refuse_msg': msg,
                            'pay_method': pay_method_str,
                            'pay_method_display': pay_method_text
                        }
                    )
                    return

            # 上位机同意取消：关停生产任务
            ProductionTask.objects.filter(
                order=order,
                status__in=[ProductionTask.TASK_PENDING, ProductionTask.TASK_SENT, ProductionTask.TASK_MAKING]
            ).update(
                status=ProductionTask.TASK_FAILED,
                failure_reason=f"制作中自动退款取消: {reason}"
            )

        # 执行微信原路退款 (待制作或制作中上位机已同意停机)
        refund_order(order, reason=f"[自动退款] {reason}", funds_account=funds_account, skip_device_cancel=True)

        # 释放物料库存
        res_restore = restore_order_inventory(
            order=order,
            operator=admin_username,
            reason=f"自动退款放库: {reason}"
        )
        restored_mats = res_restore.get('restored_materials', []) if res_restore else []
        mats_str = "，".join([f"{m['name']} x{m['quantity']}{m.get('unit', '')}" for m in restored_mats]) if restored_mats else "无"
        logger.info(f"[AsyncAutoRefund] 订单 {order.order_no} 自动退款异步处理成功，已退款并归还物料: {mats_str}")

    except Exception as e:
        logger.exception(f"[AsyncAutoRefund] 自动退款异步处理异常: order_id={order_id}, error={e}")
        try:
            order = OrderMain.objects.filter(id=order_id).first()
            if order:
                record_order_timeline(
                    order=order,
                    action=OrderStatusLog.ACTION_REFUND_FAILED,
                    action_name='自动退款异常',
                    from_status=order.status,
                    to_status=order.status,
                    operator_type=OrderStatusLog.OP_SYSTEM,
                    operator='system',
                    remark=f'自动退款后台异步处理异常: {str(e)}',
                    payload={'error': str(e)}
                )
        except Exception:
            pass


class OrderAutoRefundView(APIView):
    """
    独立接口 1：自动退款接口（异步执行，退款成功后放库存，轨迹实时写入时间线）
    POST /api/admin/orders/<str:order_no>/refund/auto/

    规则：
    1. STATUS_PAID ('pending_dispense'，已支付待制作)：
       - 不调用上位机 MQTT，立即关停生产任务；
       - 后台异步执行微信线上退款与释放库存，订单关闭；
       - 接口即刻返回，避免任何 HTTP 阻塞。
    2. STATUS_MAKING ('making'，制作中)：
       - 立即在履约时间线记录一条【申请自动退款】日志（记录当前制作中状态与微信支付方式）；
       - 后台异步调用上位机 MQTT cancel，等待上位机通过 MQTT 返回值；
       - 若返回值表示可以取消 (1 / ok / true)：终止生产任务，执行微信线上退款并释放归还物料库存；
       - 若返回值表示不可 (0 / fail / 拒绝) 或 5 秒超时：拒绝退款，不放库存，在时间线沉淀被拒说明；
       - 接口即刻返回，避免任何 HTTP 阻塞。
    3. 其他状态：
       - 直接拒绝退款。
    """
    permission_classes = [IsAdmin]

    def post(self, request, order_no):
        order, err_resp = _get_admin_order_for_refund(request, order_no)
        if err_resp:
            return err_resp

        reason = request.data.get('reason', '') or '自动退款放库'
        funds_account = request.data.get('funds_account', None)
        from orders.models import ProductionTask

        # =========================================================================
        # 情况 1：STATUS_PAID (待制作)
        # 上位机尚未制作，无需与硬件通讯。立即关停任务，启动异步退款与库存释放
        # =========================================================================
        if order.status == OrderMain.STATUS_PAID:
            logger.info(f"[AdminAutoRefund] 订单 {order_no} 处于待制作状态，关停任务并触发异步退款")
            # 1. 关停生产任务，防止后续下发制作
            ProductionTask.objects.filter(
                order=order,
                status__in=[ProductionTask.TASK_PENDING, ProductionTask.TASK_SENT]
            ).update(
                status=ProductionTask.TASK_FAILED,
                failure_reason=f"待制作自动退款取消: {reason}"
            )

            # 2. 异步执行微信退款与库存释放
            run_sync = bool(request.data.get('sync', False))
            if run_sync:
                _async_execute_auto_refund(order.id, request.user.username, reason, funds_account, 'paid')
            else:
                threading.Thread(
                    target=_async_execute_auto_refund,
                    args=(order.id, request.user.username, reason, funds_account, 'paid'),
                    daemon=True
                ).start()

            return ok(message='已提交待制作自动退款申请，系统正在后台执行微信原路退款与库存释放，流转结果请查看履约时间线。')

        # =========================================================================
        # 情况 2：STATUS_MAKING (制作中)
        # 设备已在制作，写入申请时间线，后台异步向设备发送 cancel 并等待 5s
        # =========================================================================
        elif order.status == OrderMain.STATUS_MAKING:
            logger.info(f"[AdminAutoRefund] 订单 {order_no} 处于制作中，写入申请时间线并触发异步确认停机...")
            from payments.models import PaymentRecord, get_pay_method_display
            payment = PaymentRecord.objects.filter(order=order, status=PaymentRecord.STATUS_SUCCESS).first()
            pay_method_str = getattr(payment, 'pay_method', 'wechat_jsapi') if payment else ''
            pay_method_text = get_pay_method_display(pay_method_str) if payment else '微信支付'

            # 记录一条时间线：管理员提交申请，系统正在向设备确认停机
            from orders.services import record_order_timeline
            record_order_timeline(
                order=order,
                action=OrderStatusLog.ACTION_REFUND_APPLIED,
                action_name='申请自动退款',
                from_status=OrderMain.STATUS_MAKING,
                to_status=OrderMain.STATUS_MAKING,
                operator_type=OrderStatusLog.OP_ADMIN,
                operator=request.user.username,
                remark=f'管理员 {request.user.username} 提交自动退款申请，系统正在后台向设备确认停机...',
                payload={
                    'reason': reason,
                    'pay_method': pay_method_str,
                    'pay_method_display': pay_method_text
                }
            )

            # 启动异步线程向设备确认停机并退款
            run_sync = bool(request.data.get('sync', False))
            if run_sync:
                _async_execute_auto_refund(order.id, request.user.username, reason, funds_account, 'making')
            else:
                threading.Thread(
                    target=_async_execute_auto_refund,
                    args=(order.id, request.user.username, reason, funds_account, 'making'),
                    daemon=True
                ).start()

            return ok(message='已提交制作中自动停机退款申请，系统正在与设备确认停机，处理结果已实时写入履约流转时间线。')

        # =========================================================================
        # 情况 3：其他状态，一律不允许自动退款
        # =========================================================================
        else:
            logger.warning(f"[AdminAutoRefund] 订单 {order_no} 处于[{order.get_status_display()}]阶段，拒绝自动退款")
            return error(
                f'当前订单状态为[{order.get_status_display()}]，不支持自动退款（自动退款仅支持待制作或制作中订单）。若需退款请使用【强制退款】。',
                code=4003
            )


class OrderForceRefundView(APIView):
    """
    独立接口 2：强制退款接口（不放库存）
    POST /api/admin/orders/<str:order_no>/refund/force/

    规则：
    1. 管理员最高权限，理论上必须成功；
    2. 无视设备制作状态与网络连接，完全跳过上位机 MQTT 等待 (skip_device_cancel=True)；
    3. 不释放物料库存（物料作为损耗）；
    4. 终止关联的未完成生产任务，微信线上原路退回资金。
    """
    permission_classes = [IsAdmin]

    def post(self, request, order_no):
        order, err_resp = _get_admin_order_for_refund(request, order_no)
        if err_resp:
            return err_resp

        reason = request.data.get('reason', '') or '管理员强制退款'
        funds_account = request.data.get('funds_account', None)

        # 1. 终止未完成的生产任务
        from orders.models import ProductionTask
        ProductionTask.objects.filter(
            order=order,
            status__in=[ProductionTask.TASK_PENDING, ProductionTask.TASK_SENT, ProductionTask.TASK_MAKING]
        ).update(
            status=ProductionTask.TASK_FAILED,
            failure_reason=f"强制退款: {reason}"
        )

        # 2. 线上强制退款：不调上位机、不放库存、直接调用微信原路退款
        logger.info(f"[AdminForceRefund] 管理员 {request.user.username} 对订单 {order_no} 发起【强制退款(不退库存)】, 原因: {reason}")
        try:
            refund_order(order, reason=f"[强制退款] {reason}", funds_account=funds_account, skip_device_cancel=True)
            logger.info(f"[AdminForceRefund] 订单 {order_no} 强制退款成功 (已跳过上位机等待，未释放库存)")
            return ok(message='强制退款成功！资金已原路退回（未归还物料库存）')
        except Exception as e:
            logger.exception(f"[AdminForceRefund] 强制退款异常: order_no={order_no}, error={e}")
            return error(f'强制退款异常: {str(e)}', code=4001)


class OrderRefundActionView(APIView):
    """
    通用退款分发接口（兼容旧路由调用），内部根据 refund_type 转发至对应独立接口
    POST /api/admin/orders/<str:order_no>/refund/
    """
    permission_classes = [IsAdmin]

    def post(self, request, order_no):
        refund_type = request.data.get('refund_type', 'auto')
        if refund_type == 'force':
            return OrderForceRefundView().post(request, order_no)
        elif refund_type == 'auto':
            return OrderAutoRefundView().post(request, order_no)
        else:
            return error(f'未知的退款类型: {refund_type}，请使用 auto 或 force', code=4000)

