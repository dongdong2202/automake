from django.utils import timezone
from rest_framework.views import APIView
from utils.permissions import IsAdmin
from utils.response import ok, error
from notifications.models import NotifyEvent
from ..serializers import NotifyEventAdminSerializer
from ..filters import StandardPagination


class NotifyEventListView(APIView):
    """
    GET /api/admin/notifications/events/ - 获取告警与通知事件列表
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        user = request.user
        qs = NotifyEvent.objects.all().select_related('device', 'order', 'handled_by').order_by('-created_at')

        if not user.is_super_admin:
            qs = qs.filter(device__store_id__in=user.stores.values_list('id', flat=True))

        level = request.query_params.get('level')
        event_type = request.query_params.get('event_type')
        is_handled = request.query_params.get('is_handled')

        if level:
            qs = qs.filter(level=level)
        if event_type:
            qs = qs.filter(event_type=event_type)
        if is_handled is not None:
            qs = qs.filter(is_handled=(is_handled.lower() in ('true', '1')))

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = NotifyEventAdminSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class NotifyEventHandleView(APIView):
    """
    POST /api/admin/notifications/events/<int:pk>/handle/ - 标记告警事件为已处理
    """
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        event = NotifyEvent.objects.filter(pk=pk).first()
        if not event:
            return error('告警事件不存在', code=4041)

        event.is_handled = True
        event.handled_at = timezone.now()
        event.handled_by = request.user
        event.save(update_fields=['is_handled', 'handled_at', 'handled_by'])

        return ok(message='告警事件已成功标记为已处理')
