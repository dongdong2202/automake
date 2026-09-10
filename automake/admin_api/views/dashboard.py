"""
运营驾驶舱概览数据统计模块 (Dashboard Analytics View)
======================================================
核心功能：
1. 汇总当日关键业务 KPI（实收营业额、订单量、客单均价、设备在线率、未处理告警、新增用户）；
2. 昨日同期对比与增长率计算（日环比分析）；
3. 设备多维状态统计（在线、离线、故障）；
4. 近 7 天营业额与订单量时序趋势（按日 TruncDate 单次聚合，杜绝 N+1 循环查询）；
5. 热销商品 TOP 10 榜单与物料库存低水位预警列表；
6. 实时最新成交订单流水（select_related / prefetch_related 预加载优化）。
"""

import datetime
import logging
from django.utils import timezone
from django.db.models import Count, Sum, Avg
from django.db.models.functions import TruncDate
from rest_framework.views import APIView
from utils.permissions import IsAdmin
from utils.response import ok, error
from stores.models import Store
from devices.models import Device, DeviceAlarm
from orders.models import OrderMain, OrderItem, ProductionTask
from inventory.models import Material
from users.models import User
from notifications.models import NotifyEvent

logger = logging.getLogger(__name__)


class DashboardStatsView(APIView):
    """
    GET /api/admin/dashboard/stats
    运营驾驶舱实时概览统计数据接口
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        user = request.user
        today = timezone.localdate()
        yesterday = today - datetime.timedelta(days=1)

        # ---------------------------------------------------------
        # 1. 数据权限隔离过滤：
        #    超级管理员可查看全网大盘；普通门店管理员严格限制仅查看归属门店
        # ---------------------------------------------------------
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

        # 具备有效营收贡献的有效订单状态集（已支付待出货、制作中、制作完成）
        paid_statuses = [OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING, OrderMain.STATUS_DONE]

        # ---------------------------------------------------------
        # 2. 今日 vs 昨日 核心收银 KPI 对比（合并 Count + Sum 单次聚合，减少 DB 开销）
        # ---------------------------------------------------------
        today_paid_orders = orders_qs.filter(created_at__date=today, status__in=paid_statuses)
        yesterday_paid_orders = orders_qs.filter(created_at__date=yesterday, status__in=paid_statuses)

        today_agg = today_paid_orders.aggregate(total=Sum('pay_amount'), count=Count('id'))
        yesterday_agg = yesterday_paid_orders.aggregate(total=Sum('pay_amount'), count=Count('id'))

        today_revenue = (today_agg['total'] or 0) / 100.0
        yesterday_revenue = (yesterday_agg['total'] or 0) / 100.0
        today_order_count = today_agg['count'] or 0
        yesterday_order_count = yesterday_agg['count'] or 0

        # 平均客单价 (AOV = 净销售额 / 有效订单数)
        avg_order_value = round(today_revenue / today_order_count, 2) if today_order_count > 0 else 0.0

        # ---------------------------------------------------------
        # 3. 设备状态分布与在线率计算
        # ---------------------------------------------------------
        online_count = devices_qs.filter(status='online').count()
        offline_count = devices_qs.filter(status='offline').count()
        fault_count = devices_qs.filter(status='fault').count()
        total_devices = devices_qs.count()

        # 未处理设备硬件与物料告警数
        unhandled_alarms = alarms_qs.filter(is_handled=False).count()

        # 今日微信小程序新增注册客户数
        today_new_users = User.objects.filter(created_at__date=today).count()

        # ---------------------------------------------------------
        # 4. 近 7 天时序趋势数据（性能优化：使用 TruncDate 单次分组聚合替代 14 次单日循环查询）
        # ---------------------------------------------------------
        seven_days_ago = today - datetime.timedelta(days=6)
        trend_records = orders_qs.filter(
            created_at__date__gte=seven_days_ago,
            created_at__date__lte=today,
            status__in=paid_statuses
        ).annotate(day=TruncDate('created_at')).values('day').annotate(
            day_orders=Count('id'),
            day_revenue=Sum('pay_amount')
        )

        trend_map = {
            r['day'].strftime('%m-%d') if hasattr(r['day'], 'strftime') else str(r['day']): {
                'orders': r['day_orders'],
                'revenue': (r['day_revenue'] or 0) / 100.0
            }
            for r in trend_records
        }

        trend_labels = []
        trend_orders = []
        trend_revenue = []
        for i in range(6, -1, -1):
            d = today - datetime.timedelta(days=i)
            d_str = d.strftime('%m-%d')
            trend_labels.append(d_str)
            item = trend_map.get(d_str, {'orders': 0, 'revenue': 0.0})
            trend_orders.append(item['orders'])
            trend_revenue.append(item['revenue'])

        # ---------------------------------------------------------
        # 5. 畅销爆品榜 TOP 10 (按累计销售杯量排序)
        # ---------------------------------------------------------
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

        # ---------------------------------------------------------
        # 6. 物料安全库存预警前 5 项 (按库存绝对余量由低至高)
        # ---------------------------------------------------------
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

        # ---------------------------------------------------------
        # 7. 实时成交订单流水（预加载 store、device 与 items，消除模板渲染中的 N+1 查询）
        # ---------------------------------------------------------
        recent_orders = orders_qs.select_related('store', 'device').prefetch_related('items').order_by('-created_at')[:10]
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

        # ---------------------------------------------------------
        # 8. 组装并返回标准化响应数据结构
        # ---------------------------------------------------------
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
