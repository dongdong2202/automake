import datetime
from django.utils import timezone
from django.db.models import Count, Sum, Avg
from rest_framework.views import APIView
from utils.permissions import IsAdmin
from utils.response import ok, error
from stores.models import Store
from devices.models import Device, DeviceAlarm
from orders.models import OrderMain, OrderItem, ProductionTask
from inventory.models import Material
from users.models import User
from notifications.models import NotifyEvent


class DashboardStatsView(APIView):
    """
    GET /api/admin/dashboard/stats
    运营驾驶舱实时概览统计数据
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        user = request.user
        today = timezone.localdate()
        yesterday = today - datetime.timedelta(days=1)

        # 门店过滤
        store_ids = None
        if not user.is_super_admin:
            store_ids = list(user.stores.values_list('id', flat=True))

        orders_qs = OrderMain.objects.all()
        devices_qs = Device.objects.all()
        alarms_qs = NotifyEvent.objects.all()

        if store_ids is not None:
            orders_qs = orders_qs.filter(store_id__in=store_ids)
            devices_qs = devices_qs.filter(store_id__in=store_ids)
            alarms_qs = alarms_qs.filter(device__store_id__in=store_ids)

        paid_statuses = [OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING, OrderMain.STATUS_DONE]

        # 今日 vs 昨日 营收与订单
        today_paid_orders = orders_qs.filter(created_at__date=today, status__in=paid_statuses)
        yesterday_paid_orders = orders_qs.filter(created_at__date=yesterday, status__in=paid_statuses)

        today_revenue = (today_paid_orders.aggregate(total=Sum('pay_amount'))['total'] or 0) / 100.0
        yesterday_revenue = (yesterday_paid_orders.aggregate(total=Sum('pay_amount'))['total'] or 0) / 100.0
        today_order_count = today_paid_orders.count()
        yesterday_order_count = yesterday_paid_orders.count()

        avg_order_value = round(today_revenue / today_order_count, 2) if today_order_count > 0 else 0.0

        # 设备状态分布
        online_count = devices_qs.filter(status='online').count()
        offline_count = devices_qs.filter(status='offline').count()
        fault_count = devices_qs.filter(status='fault').count()
        total_devices = devices_qs.count()

        # 未处理告警数
        unhandled_alarms = alarms_qs.filter(is_handled=False).count()

        # 今日新增用户
        today_new_users = User.objects.filter(created_at__date=today).count()

        # 近7天趋势数据
        trend_labels = []
        trend_orders = []
        trend_revenue = []
        for i in range(6, -1, -1):
            d = today - datetime.timedelta(days=i)
            trend_labels.append(d.strftime('%m-%d'))
            day_orders = orders_qs.filter(created_at__date=d, status__in=paid_statuses)
            trend_orders.append(day_orders.count())
            day_rev = (day_orders.aggregate(total=Sum('pay_amount'))['total'] or 0) / 100.0
            trend_revenue.append(day_rev)

        # 热门商品 TOP 10
        top_items_qs = OrderItem.objects.filter(
            order__in=orders_qs.filter(status__in=paid_statuses)
        ).values('item_name').annotate(
            total_qty=Sum('quantity'),
            total_amount=Sum('subtotal')
        ).order_by('-total_qty')[:10]

        top_items = [
            {
                'name': item['item_name'],
                'quantity': item['total_qty'],
                'amount': round((item['total_amount'] or 0) / 100.0, 2)
            }
            for item in top_items_qs
        ]

        # 物料预警前 5 项
        materials_qs = Material.objects.all().order_by('quantity')[:5]
        material_warnings = [
            {
                'id': m.id,
                'name': m.name,
                'code': m.code,
                'quantity': float(m.quantity),
                'unit': m.unit,
                'material_type': m.get_material_type_display(),
            }
            for m in materials_qs
        ]

        # 最近 10 条实时订单
        recent_orders = orders_qs.order_by('-created_at')[:10]
        recent_orders_data = [
            {
                'order_no': o.order_no,
                'store_name': o.store.name if o.store else '',
                'device_sn': o.device.device_sn if o.device else '',
                'status': o.status,
                'status_display': o.get_status_display(),
                'pay_amount': round(o.pay_amount / 100.0, 2),
                'created_at': o.created_at.strftime('%H:%M:%S'),
                'items_summary': ', '.join([f"{item.item_name}×{item.quantity}" for item in o.items.all()[:2]])
            }
            for o in recent_orders
        ]

        return ok({
            'kpis': {
                'today_revenue': today_revenue,
                'yesterday_revenue': yesterday_revenue,
                'revenue_growth': round(((today_revenue - yesterday_revenue) / yesterday_revenue * 100), 1) if yesterday_revenue > 0 else 0,
                'today_orders': today_order_count,
                'yesterday_orders': yesterday_order_count,
                'orders_growth': round(((today_order_count - yesterday_order_count) / yesterday_order_count * 100), 1) if yesterday_order_count > 0 else 0,
                'avg_order_value': avg_order_value,
                'online_devices': online_count,
                'total_devices': total_devices,
                'device_online_rate': round(online_count / total_devices * 100, 1) if total_devices > 0 else 0,
                'unhandled_alarms': unhandled_alarms,
                'today_new_users': today_new_users,
                'total_stores': Store.objects.count() if user.is_super_admin else len(store_ids or []),
            },
            'device_status': {
                'online': online_count,
                'offline': offline_count,
                'fault': fault_count,
            },
            'trend': {
                'labels': trend_labels,
                'orders': trend_orders,
                'revenue': trend_revenue,
            },
            'top_items': top_items,
            'material_warnings': material_warnings,
            'recent_orders': recent_orders_data,
        })
