from rest_framework.views import APIView
from utils.permissions import IsAdmin
from utils.response import ok, error
from orders.models import OrderMain, OrderItem, ProductionTask
from payments.services import refund_order
from ..serializers import OrderAdminSerializer
from ..filters import StandardPagination


class OrderListView(APIView):
    """
    GET /api/admin/orders/ - 订单列表
    支持状态、门店、时间范围过滤及订单号搜索
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        user = request.user
        qs = OrderMain.objects.all().select_related('store', 'device', 'pickup_code').prefetch_related('items').order_by('-created_at')

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
    GET /api/admin/orders/<str:order_no>/ - 获取订单详情及生产任务状态
    """
    permission_classes = [IsAdmin]

    def get(self, request, order_no):
        order = OrderMain.objects.filter(order_no=order_no).select_related(
            'store', 'device', 'pickup_code'
        ).prefetch_related('items', 'status_logs').first()

        if not order:
            return error('订单不存在', code=4041)

        if not request.user.is_super_admin and order.store not in request.user.stores.all():
            return error('无权查看该订单', code=4031)

        data = OrderAdminSerializer(order).data
        # 补充流转日志
        data['status_logs'] = [
            {
                'from_status': log.from_status,
                'to_status': log.to_status,
                'operator': log.operator,
                'remark': log.remark,
                'created_at': log.created_at.isoformat()
            }
            for log in order.status_logs.all()
        ]
        return ok(data)


class OrderRefundActionView(APIView):
    """
    POST /api/admin/orders/<str:order_no>/refund/ - 管理员发起退款
    """
    permission_classes = [IsAdmin]

    def post(self, request, order_no):
        order = OrderMain.objects.filter(order_no=order_no).first()
        if not order:
            return error('订单不存在', code=4041)

        if not request.user.is_super_admin and order.store not in request.user.stores.all():
            return error('无权操作该订单', code=4031)

        reason = request.data.get('reason', '管理员人工申请退款')
        try:
            refund_order(order, reason=reason)
            return ok(message='退款申请已提交并完成处理')
        except Exception as e:
            return error(f'退款处理异常: {str(e)}', code=4001)
