"""
后台订单管理视图 (admin_api.views.orders)

接口列表：
- GET  /api/admin/orders/                 订单分页列表查询（支持状态、门店、时间范围与单号模糊搜索）
- GET  /api/admin/orders/<order_no>/      订单详情查询（包含订单商品与状态流转历史）
- POST /api/admin/orders/<order_no>/refund/ 管理员手动对订单发起退款
"""

import logging
from rest_framework.views import APIView
from utils.permissions import IsAdmin
from utils.response import ok, error
from orders.models import OrderMain
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
                'to_status': log.to_status,
                'operator_type': log.operator_type,
                'operator': log.operator,
                'remark': log.remark,
                'payload': log.payload or {},
                'created_at': log.created_at.isoformat()
            }
            for log in order.status_logs.all().order_by('created_at')
        ]
        return ok(data)


class OrderRefundActionView(APIView):
    """
    管理员退款操作接口

    POST /api/admin/orders/<str:order_no>/refund/
    """
    permission_classes = [IsAdmin]

    def post(self, request, order_no):
        order = OrderMain.objects.filter(order_no=order_no).first()
        if not order:
            logger.warning(f"[AdminOrderRefund] 退款订单不存在: order_no={order_no}")
            return error('订单不存在', code=4041)

        if not request.user.is_super_admin and not request.user.stores.filter(id=order.store_id).exists():
            logger.warning(f"[AdminOrderRefund] 无权操作该订单退款: order_no={order_no}, user={request.user.username}")
            return error('无权操作该订单', code=4031)

        refund_type = request.data.get('refund_type', 'auto')
        reason = request.data.get('reason', '') or ('自动退款放库' if refund_type == 'auto' else '管理员强制退款')
        offline = bool(request.data.get('offline', False))
        funds_account = request.data.get('funds_account', None)

        if order.status in [OrderMain.STATUS_REFUNDED, OrderMain.STATUS_REFUNDING]:
            return error('该订单已处于退款或退款中状态，请勿重复操作', code=4004)

        if refund_type == 'auto':
            # 自动退款：必须为未制作完成订单（出杯完成物料已被物理消耗，不能放库存）
            if order.status == OrderMain.STATUS_DONE:
                return error('该订单已制作出杯完成，物料已被物理消耗，无法使用自动退款（放库存），请使用【强制退款】', code=4003)

            from orders.services import restore_order_inventory
            res_restore = restore_order_inventory(
                order=order,
                operator=request.user.username,
                reason=f"自动退款放库: {reason}"
            )

            if offline:
                from payments.models import RefundRecord, PaymentRecord
                from orders.models import OrderStatusLog
                import uuid
                from django.utils import timezone

                payment = PaymentRecord.objects.filter(order=order, status=PaymentRecord.STATUS_SUCCESS).first()
                if not payment:
                    return error('订单无成功支付记录，无法退款', code=4002)

                out_refund_no = f"RF-OFFLINE-{uuid.uuid4().hex[:12]}"
                RefundRecord.objects.create(
                    order=order,
                    payment=payment,
                    refund_id=f"offline_{uuid.uuid4().hex[:12]}",
                    out_refund_no=out_refund_no,
                    refund_amount=payment.amount,
                    reason=f"[线下自动退款] {reason}",
                    status=RefundRecord.STATUS_SUCCESS,
                    refunded_at=timezone.now()
                )
                old_status = order.status
                order.status = OrderMain.STATUS_REFUNDED
                order.save(update_fields=['status', 'updated_at'])
                from orders.services import record_order_timeline
                record_order_timeline(
                    order=order,
                    action=OrderStatusLog.ACTION_REFUND_SUCCESS,
                    action_name='线下自动退款完成',
                    from_status=old_status,
                    to_status=order.status,
                    operator_type=OrderStatusLog.OP_ADMIN,
                    operator=request.user.username,
                    remark=f"线下自动退款: {out_refund_no}, 原因: {reason}（已释放库存）",
                    payload={
                        'out_refund_no': out_refund_no,
                        'refund_amount': payment.amount,
                        'reason': reason,
                        'mode': 'offline_auto',
                        'operator_admin': request.user.username
                    }
                )
                logger.info(f"[AdminOrderRefund] 管理员 {request.user.username} 标记订单 {order_no} 线下自动退款完成")
                return ok(message='线下退款已成功记录（自动退款：物料库存已释放归还）')

            logger.info(f"[AdminOrderRefund] 管理员 {request.user.username} 对订单 {order_no} 发起【自动退款(放库存)】, 原因: {reason}")
            try:
                refund_order(order, reason=f"[自动退款] {reason}", funds_account=funds_account)
                restored_mats = res_restore.get('restored_materials', [])
                mats_str = "，".join([f"{m['name']} x{m['quantity']}{m.get('unit', '')}" for m in restored_mats]) if restored_mats else "无"
                logger.info(f"[AdminOrderRefund] 订单 {order_no} 自动退款处理成功，归还物料: {mats_str}")
                return ok(message=f'自动退款成功！资金已原路退回，并释放归还物料：{mats_str}')
            except Exception as e:
                logger.exception(f"[AdminOrderRefund] 自动退款处理异常: order_no={order_no}, error={e}")
                return error(f'退款处理异常: {str(e)}', code=4001)

        elif refund_type == 'force':
            # 强制退款：不归还物料库存（适用于客诉、制作失败、杯体损耗等场景）
            from orders.models import ProductionTask
            ProductionTask.objects.filter(
                order=order,
                status__in=[ProductionTask.TASK_PENDING, ProductionTask.TASK_SENT, ProductionTask.TASK_MAKING]
            ).update(
                status=ProductionTask.TASK_FAILED,
                failure_reason=f"强制退款: {reason}"
            )

            if offline:
                from payments.models import RefundRecord, PaymentRecord
                from orders.models import OrderStatusLog
                import uuid
                from django.utils import timezone

                payment = PaymentRecord.objects.filter(order=order, status=PaymentRecord.STATUS_SUCCESS).first()
                if not payment:
                    return error('订单无成功支付记录，无法退款', code=4002)

                out_refund_no = f"RF-OFFLINE-{uuid.uuid4().hex[:12]}"
                RefundRecord.objects.create(
                    order=order,
                    payment=payment,
                    refund_id=f"offline_{uuid.uuid4().hex[:12]}",
                    out_refund_no=out_refund_no,
                    refund_amount=payment.amount,
                    reason=f"[线下强制退款] {reason}",
                    status=RefundRecord.STATUS_SUCCESS,
                    refunded_at=timezone.now()
                )
                old_status = order.status
                order.status = OrderMain.STATUS_REFUNDED
                order.save(update_fields=['status', 'updated_at'])
                from orders.services import record_order_timeline
                record_order_timeline(
                    order=order,
                    action=OrderStatusLog.ACTION_REFUND_SUCCESS,
                    action_name='线下强制退款完成',
                    from_status=old_status,
                    to_status=order.status,
                    operator_type=OrderStatusLog.OP_ADMIN,
                    operator=request.user.username,
                    remark=f"线下强制退款: {out_refund_no}, 原因: {reason}（未释放库存）",
                    payload={
                        'out_refund_no': out_refund_no,
                        'refund_amount': payment.amount,
                        'reason': reason,
                        'mode': 'offline_force',
                        'operator_admin': request.user.username
                    }
                )
                logger.info(f"[AdminOrderRefund] 管理员 {request.user.username} 标记订单 {order_no} 线下强制退款完成")
                return ok(message='线下退款已成功记录（强制退款：未释放物料库存）')

            logger.info(f"[AdminOrderRefund] 管理员 {request.user.username} 对订单 {order_no} 发起【强制退款(不退库存)】, 原因: {reason}")
            try:
                refund_order(order, reason=f"[强制退款] {reason}", funds_account=funds_account)
                logger.info(f"[AdminOrderRefund] 订单 {order_no} 强制退款处理成功")
                return ok(message='强制退款成功！资金已原路退回（未归还物料库存）')
            except Exception as e:
                logger.exception(f"[AdminOrderRefund] 强制退款处理异常: order_no={order_no}, error={e}")
                return error(f'退款处理异常: {str(e)}', code=4001)

        else:
            return error(f'未知的退款类型: {refund_type}，支持 auto 或 force', code=4000)

