import datetime
import logging
from django.utils import timezone
from django.db.models import Count, Sum, Avg, F, Q, Case, When, Value, IntegerField
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth, ExtractHour, ExtractWeekDay
from rest_framework.views import APIView
from utils.permissions import IsAdmin
from utils.response import ok, error
from stores.models import Store
from devices.models import Device, DeviceAlarm, DeviceStatusLog
from orders.models import OrderMain, OrderItem, ProductionTask
from inventory.models import Material, InventoryRecord
from users.models import User
from notifications.models import NotifyEvent

logger = logging.getLogger(__name__)



def _parse_date_and_store_filters(request):
    """辅助函数：解析日期范围与门店筛选条件"""
    user = request.user
    start_str = request.query_params.get('start_date')
    end_str = request.query_params.get('end_date')
    store_id = request.query_params.get('store_id')
    device_sn = request.query_params.get('device_sn')

    today = timezone.localdate()
    if not start_str:
        start_date = today - datetime.timedelta(days=29)  # 默认近30天
    else:
        try:
            start_date = datetime.datetime.strptime(start_str, '%Y-%m-%d').date()
        except ValueError:
            start_date = today - datetime.timedelta(days=29)

    if not end_str:
        end_date = today
    else:
        try:
            end_date = datetime.datetime.strptime(end_str, '%Y-%m-%d').date()
        except ValueError:
            end_date = today

    # 门店权限过滤
    store_ids = None
    if not user.is_super_admin:
        allowed_ids = list(user.stores.values_list('id', flat=True))
        if store_id:
            store_ids = [int(store_id)] if int(store_id) in allowed_ids else allowed_ids
        else:
            store_ids = allowed_ids
    elif store_id:
        store_ids = [int(store_id)]

    return start_date, end_date, store_ids, device_sn


# ============================================================
# 1. 销售分析 (Sales Analytics)
# ============================================================
class SalesTrendAnalyticsView(APIView):
    """
    GET /api/admin/analytics/sales/trend
    销售趋势（折线图支持按日/周/月聚合）
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        start_date, end_date, store_ids, device_sn = _parse_date_and_store_filters(request)
        granularity = request.query_params.get('granularity', 'day')

        paid_statuses = [OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING, OrderMain.STATUS_DONE]
        qs = OrderMain.objects.filter(
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            status__in=paid_statuses
        )
        if store_ids is not None:
            qs = qs.filter(store_id__in=store_ids)
        if device_sn:
            qs = qs.filter(device__device_sn=device_sn)

        if granularity == 'week':
            trunc_fn = TruncWeek('created_at')
        elif granularity == 'month':
            trunc_fn = TruncMonth('created_at')
        else:
            trunc_fn = TruncDate('created_at')

        records = qs.annotate(period=trunc_fn).values('period').annotate(
            order_count=Count('id'),
            revenue=Sum('pay_amount'),
            avg_val=Avg('pay_amount')
        ).order_by('period')

        results = []
        prev_rev = None
        for r in records:
            rev = (r['revenue'] or 0) / 100.0
            cnt = r['order_count'] or 0
            avg_v = round(((r['avg_val'] or 0) / 100.0), 2)
            growth = 0.0
            if prev_rev is not None and prev_rev > 0:
                growth = round(((rev - prev_rev) / prev_rev * 100), 2)
            prev_rev = rev

            results.append({
                'date': r['period'].strftime('%Y-%m-%d') if hasattr(r['period'], 'strftime') else str(r['period']),
                'order_count': cnt,
                'revenue': round(rev, 2),
                'avg_order_value': avg_v,
                'growth_rate': growth,
            })

        return ok(results)


class SalesByHourAnalyticsView(APIView):
    """
    GET /api/admin/analytics/sales/by-hour
    24小时时段销售热力分布
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        start_date, end_date, store_ids, device_sn = _parse_date_and_store_filters(request)
        paid_statuses = [OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING, OrderMain.STATUS_DONE]

        qs = OrderMain.objects.filter(
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            status__in=paid_statuses
        )
        if store_ids is not None:
            qs = qs.filter(store_id__in=store_ids)
        if device_sn:
            qs = qs.filter(device__device_sn=device_sn)

        records = qs.annotate(hour=ExtractHour('created_at')).values('hour').annotate(
            order_count=Count('id'),
            revenue=Sum('pay_amount')
        ).order_by('hour')

        hour_map = {r['hour']: {'order_count': r['order_count'], 'revenue': round((r['revenue'] or 0) / 100.0, 2)} for r in records}
        results = []
        for h in range(24):
            data = hour_map.get(h, {'order_count': 0, 'revenue': 0.0})
            results.append({
                'hour': f"{h:02d}:00",
                'order_count': data['order_count'],
                'revenue': data['revenue']
            })

        return ok(results)


class SalesByWeekdayAnalyticsView(APIView):
    """
    GET /api/admin/analytics/sales/by-weekday
    星期销售热力图分布
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        start_date, end_date, store_ids, device_sn = _parse_date_and_store_filters(request)
        paid_statuses = [OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING, OrderMain.STATUS_DONE]

        qs = OrderMain.objects.filter(
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            status__in=paid_statuses
        )
        if store_ids is not None:
            qs = qs.filter(store_id__in=store_ids)
        if device_sn:
            qs = qs.filter(device__device_sn=device_sn)

        records = qs.annotate(weekday=ExtractWeekDay('created_at')).values('weekday').annotate(
            order_count=Count('id'),
            revenue=Sum('pay_amount')
        ).order_by('weekday')

        # Django ExtractWeekDay: 1=Sunday, 2=Monday, ..., 7=Saturday
        name_map = {2: '周一', 3: '周二', 4: '周三', 5: '周四', 6: '周五', 7: '周六', 1: '周日'}
        data_map = {r['weekday']: {'order_count': r['order_count'], 'revenue': round((r['revenue'] or 0) / 100.0, 2)} for r in records}

        results = []
        for wd in [2, 3, 4, 5, 6, 7, 1]:
            info = data_map.get(wd, {'order_count': 0, 'revenue': 0.0})
            results.append({
                'weekday': name_map[wd],
                'order_count': info['order_count'],
                'revenue': info['revenue']
            })

        return ok(results)


class SalesByStoreAnalyticsView(APIView):
    """
    GET /api/admin/analytics/sales/by-store
    门店销售排名对比
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        start_date, end_date, store_ids, _ = _parse_date_and_store_filters(request)
        paid_statuses = [OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING, OrderMain.STATUS_DONE]

        qs = OrderMain.objects.filter(
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            status__in=paid_statuses
        )
        if store_ids is not None:
            qs = qs.filter(store_id__in=store_ids)

        records = qs.values('store_id', 'store__name').annotate(
            order_count=Count('id'),
            revenue=Sum('pay_amount'),
            avg_order_value=Avg('pay_amount')
        ).order_by('-revenue')

        results = [
            {
                'store_id': r['store_id'],
                'store_name': r['store__name'] or f"门店#{r['store_id']}",
                'order_count': r['order_count'],
                'revenue': round((r['revenue'] or 0) / 100.0, 2),
                'avg_order_value': round((r['avg_order_value'] or 0) / 100.0, 2),
            }
            for r in records
        ]
        return ok(results)


class SalesByDeviceAnalyticsView(APIView):
    """
    GET /api/admin/analytics/sales/by-device
    设备产能及销售排名
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        start_date, end_date, store_ids, _ = _parse_date_and_store_filters(request)
        paid_statuses = [OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING, OrderMain.STATUS_DONE]

        qs = OrderMain.objects.filter(
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            status__in=paid_statuses,
            device__isnull=False
        )
        if store_ids is not None:
            qs = qs.filter(store_id__in=store_ids)

        records = qs.values('device__device_sn', 'device__device_name', 'store__name').annotate(
            cups_made=Count('id'),
            revenue=Sum('pay_amount')
        ).order_by('-cups_made')

        results = [
            {
                'device_sn': r['device__device_sn'],
                'device_name': r['device__device_name'] or r['device__device_sn'],
                'store_name': r['store__name'] or '',
                'cups_made': r['cups_made'],
                'revenue': round((r['revenue'] or 0) / 100.0, 2)
            }
            for r in records
        ]
        return ok(results)


class SalesFunnelAnalyticsView(APIView):
    """
    GET /api/admin/analytics/sales/funnel
    订单全链路转化漏斗
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        start_date, end_date, store_ids, device_sn = _parse_date_and_store_filters(request)
        qs = OrderMain.objects.filter(created_at__date__gte=start_date, created_at__date__lte=end_date)
        if store_ids is not None:
            qs = qs.filter(store_id__in=store_ids)
        if device_sn:
            qs = qs.filter(device__device_sn=device_sn)

        total_created = qs.count()
        paid_count = qs.filter(status__in=[OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING, OrderMain.STATUS_DONE]).count()
        making_count = qs.filter(status__in=[OrderMain.STATUS_MAKING, OrderMain.STATUS_DONE]).count()
        done_count = qs.filter(status=OrderMain.STATUS_DONE).count()
        refunded_count = qs.filter(status=OrderMain.STATUS_REFUNDED).count()

        results = [
            {'stage': '创建订单', 'count': total_created, 'percentage': 100.0},
            {'stage': '支付成功', 'count': paid_count, 'percentage': round(paid_count / total_created * 100, 1) if total_created > 0 else 0},
            {'stage': '设备制作', 'count': making_count, 'percentage': round(making_count / total_created * 100, 1) if total_created > 0 else 0},
            {'stage': '完成出杯', 'count': done_count, 'percentage': round(done_count / total_created * 100, 1) if total_created > 0 else 0},
            {'stage': '退款', 'count': refunded_count, 'percentage': round(refunded_count / total_created * 100, 1) if total_created > 0 else 0},
        ]
        return ok(results)


# ============================================================
# 2. 财务概览 (Finance Analytics)
# ============================================================
class FinanceSummaryAnalyticsView(APIView):
    """
    GET /api/admin/analytics/finance/summary
    财务汇总 KPI
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        start_date, end_date, store_ids, _ = _parse_date_and_store_filters(request)
        qs = OrderMain.objects.filter(created_at__date__gte=start_date, created_at__date__lte=end_date)
        if store_ids is not None:
            qs = qs.filter(store_id__in=store_ids)

        paid_statuses = [OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING, OrderMain.STATUS_DONE]
        gross_revenue = (qs.filter(status__in=paid_statuses).aggregate(total=Sum('pay_amount'))['total'] or 0) / 100.0
        refund_amount = (qs.filter(status=OrderMain.STATUS_REFUNDED).aggregate(total=Sum('pay_amount'))['total'] or 0) / 100.0
        net_revenue = gross_revenue - refund_amount
        refund_rate = round(refund_amount / gross_revenue * 100, 2) if gross_revenue > 0 else 0.0

        paid_order_count = qs.filter(status__in=paid_statuses).count()
        refund_order_count = qs.filter(status=OrderMain.STATUS_REFUNDED).count()

        return ok({
            'gross_revenue': round(gross_revenue, 2),
            'refund_amount': round(refund_amount, 2),
            'net_revenue': round(net_revenue, 2),
            'refund_rate': refund_rate,
            'paid_orders': paid_order_count,
            'refund_orders': refund_order_count,
            'avg_net_order_value': round(net_revenue / paid_order_count, 2) if paid_order_count > 0 else 0.0
        })


class FinanceTrendAnalyticsView(APIView):
    """
    GET /api/admin/analytics/finance/trend
    营收与退款趋势（双柱+折线混合图）
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        start_date, end_date, store_ids, _ = _parse_date_and_store_filters(request)
        granularity = request.query_params.get('granularity', 'day')

        qs = OrderMain.objects.filter(created_at__date__gte=start_date, created_at__date__lte=end_date)
        if store_ids is not None:
            qs = qs.filter(store_id__in=store_ids)

        trunc_fn = TruncDate('created_at') if granularity == 'day' else (TruncWeek('created_at') if granularity == 'week' else TruncMonth('created_at'))

        paid_statuses = [OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING, OrderMain.STATUS_DONE]

        rev_records = qs.filter(status__in=paid_statuses).annotate(period=trunc_fn).values('period').annotate(
            revenue=Sum('pay_amount')
        )
        ref_records = qs.filter(status=OrderMain.STATUS_REFUNDED).annotate(period=trunc_fn).values('period').annotate(
            refund=Sum('pay_amount')
        )

        rev_map = {r['period']: (r['revenue'] or 0) / 100.0 for r in rev_records}
        ref_map = {r['period']: (r['refund'] or 0) / 100.0 for r in ref_records}

        all_periods = sorted(list(set(list(rev_map.keys()) + list(ref_map.keys()))))
        results = []
        for p in all_periods:
            rev = rev_map.get(p, 0.0)
            ref = ref_map.get(p, 0.0)
            results.append({
                'date': p.strftime('%Y-%m-%d') if hasattr(p, 'strftime') else str(p),
                'revenue': round(rev, 2),
                'refund': round(ref, 2),
                'net_revenue': round(rev - ref, 2)
            })

        return ok(results)


class FinanceCategoryShareAnalyticsView(APIView):
    """
    GET /api/admin/analytics/finance/category-share
    品类营收构成饼图
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        start_date, end_date, store_ids, _ = _parse_date_and_store_filters(request)
        paid_statuses = [OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING, OrderMain.STATUS_DONE]

        items_qs = OrderItem.objects.filter(
            order__created_at__date__gte=start_date,
            order__created_at__date__lte=end_date,
            order__status__in=paid_statuses
        )
        if store_ids is not None:
            items_qs = items_qs.filter(order__store_id__in=store_ids)

        records = items_qs.values('item__global_item__category__name').annotate(
            total_amount=Sum('subtotal'),
            total_qty=Sum('quantity')
        ).order_by('-total_amount')

        results = []
        for r in records:
            cat_name = r['item__global_item__category__name'] or '经典咖啡'
            results.append({
                'name': cat_name,
                'value': round((r['total_amount'] or 0) / 100.0, 2),
                'quantity': r['total_qty']
            })

        return ok(results)


# ============================================================
# 3. 产品分析 (Product Analytics)
# ============================================================
class ProductRankingAnalyticsView(APIView):
    """
    GET /api/admin/analytics/products/ranking
    商品销量与营收排行 TOP 20
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        start_date, end_date, store_ids, _ = _parse_date_and_store_filters(request)
        paid_statuses = [OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING, OrderMain.STATUS_DONE]

        items_qs = OrderItem.objects.filter(
            order__created_at__date__gte=start_date,
            order__created_at__date__lte=end_date,
            order__status__in=paid_statuses
        )
        if store_ids is not None:
            items_qs = items_qs.filter(order__store_id__in=store_ids)

        records = items_qs.values('item_name').annotate(
            total_qty=Sum('quantity'),
            total_revenue=Sum('subtotal'),
            avg_unit_price=Avg('unit_price')
        ).order_by('-total_qty')[:20]

        results = [
            {
                'name': r['item_name'],
                'quantity': r['total_qty'],
                'revenue': round((r['total_revenue'] or 0) / 100.0, 2),
                'avg_price': round((r['avg_unit_price'] or 0) / 100.0, 2)
            }
            for r in records
        ]
        return ok(results)


class ProductSkuPreferencesAnalyticsView(APIView):
    """
    GET /api/admin/analytics/products/sku-preferences
    规格偏好雷达图与偏好分析
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        start_date, end_date, store_ids, _ = _parse_date_and_store_filters(request)
        paid_statuses = [OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING, OrderMain.STATUS_DONE]

        items_qs = OrderItem.objects.filter(
            order__created_at__date__gte=start_date,
            order__created_at__date__lte=end_date,
            order__status__in=paid_statuses
        )
        if store_ids is not None:
            items_qs = items_qs.filter(order__store_id__in=store_ids)

        records = items_qs.values('sku_name').annotate(
            total_qty=Sum('quantity')
        ).order_by('-total_qty')

        results = [
            {'sku': r['sku_name'] or '标准规格', 'quantity': r['total_qty']}
            for r in records if r['sku_name']
        ]
        return ok(results)


# ============================================================
# 4. 设备运维分析 (Device Analytics)
# ============================================================
class DeviceUptimeAnalyticsView(APIView):
    """
    GET /api/admin/analytics/devices/uptime
    设备在线率与健康评分
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        _, _, store_ids, _ = _parse_date_and_store_filters(request)
        devices_qs = Device.objects.all()
        if store_ids is not None:
            devices_qs = devices_qs.filter(store_id__in=store_ids)

        results = []
        for dev in devices_qs:
            status = dev.status
            # 计算健康评分 (在线 100, 离线 50, 故障 20)
            score = 100 if status == 'online' else (50 if status == 'offline' else 20)
            alarm_count = dev.alarms.filter(is_resolved=False).count()
            score = max(10, score - alarm_count * 10)

            results.append({
                'device_sn': dev.device_sn,
                'device_name': dev.device_name or dev.device_sn,
                'store_name': dev.store.name if dev.store else '',
                'status': status,
                'status_display': dev.get_status_display(),
                'health_score': score,
                'unresolved_alarms': alarm_count,
                'last_heartbeat': dev.last_heartbeat_at.isoformat() if dev.last_heartbeat_at else None
            })

        return ok(results)


class DeviceAlarmTrendAnalyticsView(APIView):
    """
    GET /api/admin/analytics/devices/alarm-trend
    告警趋势堆叠面积图
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        start_date, end_date, store_ids, _ = _parse_date_and_store_filters(request)
        events_qs = NotifyEvent.objects.filter(created_at__date__gte=start_date, created_at__date__lte=end_date)
        if store_ids is not None:
            events_qs = events_qs.filter(device__store_id__in=store_ids)

        records = events_qs.annotate(period=TruncDate('created_at')).values('period', 'level').annotate(
            count=Count('id')
        ).order_by('period')

        date_map = {}
        for r in records:
            p_str = r['period'].strftime('%Y-%m-%d')
            if p_str not in date_map:
                date_map[p_str] = {'info': 0, 'warning': 0, 'critical': 0}
            date_map[p_str][r['level']] = r['count']

        results = [
            {
                'date': d,
                'info': counts['info'],
                'warning': counts['warning'],
                'critical': counts['critical']
            }
            for d, counts in sorted(date_map.items())
        ]
        return ok(results)


# ============================================================
# 5. 物料进销存分析 (Material Analytics)
# ============================================================
class MaterialStockStatusAnalyticsView(APIView):
    """
    GET /api/admin/analytics/materials/stock-status
    物料库存状态与剩余百分比
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        materials = Material.objects.all().order_by('code')
        results = []
        for m in materials:
            qty = float(m.quantity)
            # 假定基准容量以 100 单位作为 100% 满仓基准（可根据需要拓展）
            base_capacity = 100.0 if m.unit in ['kg', '升'] else 2000.0
            percent = min(100.0, round((qty / base_capacity * 100.0), 1))
            status = 'normal' if percent >= 60 else ('warning' if percent >= 30 else 'critical')

            results.append({
                'id': m.id,
                'code': m.code,
                'name': m.name,
                'material_type': m.get_material_type_display(),
                'quantity': qty,
                'unit': m.unit,
                'percentage': percent,
                'status': status,
                'retrieve_count': m.retrieve_count
            })

        return ok(results)


class MaterialConsumptionTrendAnalyticsView(APIView):
    """
    GET /api/admin/analytics/materials/consumption
    物料消耗趋势
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        start_date, end_date, store_ids, _ = _parse_date_and_store_filters(request)
        records_qs = InventoryRecord.objects.filter(
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            record_type='out'
        )
        if store_ids is not None:
            records_qs = records_qs.filter(store_id__in=store_ids)

        records = records_qs.annotate(period=TruncDate('created_at')).values(
            'period', 'material__name'
        ).annotate(
            total_qty=Sum('quantity')
        ).order_by('period')

        results = [
            {
                'date': r['period'].strftime('%Y-%m-%d'),
                'material_name': r['material__name'],
                'quantity': float(r['total_qty'] or 0)
            }
            for r in records
        ]
        return ok(results)


class MaterialForecastAnalyticsView(APIView):
    """
    GET /api/admin/analytics/materials/replenishment-forecast
    物料消耗预测与补货建议
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        seven_days_ago = timezone.now() - datetime.timedelta(days=7)
        # 批量聚合所有物料过去 7 天出库总量，单次查询搞定 (消除 N+1)
        recent_outs = InventoryRecord.objects.filter(
            record_type='out',
            created_at__gte=seven_days_ago
        ).values('material_id').annotate(total=Sum('quantity'))
        recent_out_map = {r['material_id']: r['total'] for r in recent_outs}

        materials = Material.objects.all()
        results = []
        for m in materials:
            recent_out = recent_out_map.get(m.id, 0) or 0
            avg_daily = float(recent_out) / 7.0
            qty = float(m.quantity)

            if avg_daily > 0:
                days_left = round(qty / avg_daily, 1)
            else:
                days_left = 999.0

            urgency = 'critical' if days_left <= 2 else ('warning' if days_left <= 5 else 'normal')

            results.append({
                'id': m.id,
                'name': m.name,
                'code': m.code,
                'unit': m.unit,
                'current_stock': qty,
                'avg_daily_consumption': round(avg_daily, 2),
                'days_remaining': days_left,
                'urgency': urgency
            })

        return ok(sorted(results, key=lambda x: x['days_remaining']))


# ============================================================
# 6. 客户分析 (Customer Analytics)
# ============================================================
class CustomerGrowthAnalyticsView(APIView):
    """
    GET /api/admin/analytics/customers/growth
    用户增长与消费频次分析
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        start_date, end_date, _, _ = _parse_date_and_store_filters(request)
        users_qs = User.objects.filter(created_at__date__gte=start_date, created_at__date__lte=end_date)

        records = users_qs.annotate(period=TruncDate('created_at')).values('period').annotate(
            new_users=Count('id')
        ).order_by('period')

        results = [
            {
                'date': r['period'].strftime('%Y-%m-%d'),
                'new_users': r['new_users']
            }
            for r in records
        ]

        total_users = User.objects.count()
        return ok({
            'total_users': total_users,
            'growth_trend': results
        })


class CustomerFrequencyAnalyticsView(APIView):
    """
    GET /api/admin/analytics/customers/order-frequency
    用户消费频次分布
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        from django.db.models import Case, When, IntegerField, Sum, Count

        valid_orders = OrderMain.objects.filter(
            status__in=[OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING, OrderMain.STATUS_DONE]
        )
        aggregated = valid_orders.values('user_id').annotate(order_count=Count('id')).aggregate(
            tier_1=Sum(Case(When(order_count=1, then=1), default=0, output_field=IntegerField())),
            tier_2_3=Sum(Case(When(order_count__gte=2, order_count__lte=3, then=1), default=0, output_field=IntegerField())),
            tier_4_9=Sum(Case(When(order_count__gte=4, order_count__lte=9, then=1), default=0, output_field=IntegerField())),
            tier_10_plus=Sum(Case(When(order_count__gte=10, then=1), default=0, output_field=IntegerField())),
            total_users=Count('user_id')
        )

        tier_1 = aggregated.get('tier_1') or 0
        tier_2_3 = aggregated.get('tier_2_3') or 0
        tier_4_9 = aggregated.get('tier_4_9') or 0
        tier_10_plus = aggregated.get('tier_10_plus') or 0
        total = aggregated.get('total_users') or 1

        results = [
            {'tier': '1次尝鲜', 'count': tier_1, 'percentage': round(tier_1 / total * 100, 1)},
            {'tier': '2-3次回购', 'count': tier_2_3, 'percentage': round(tier_2_3 / total * 100, 1)},
            {'tier': '4-9次活跃', 'count': tier_4_9, 'percentage': round(tier_4_9 / total * 100, 1)},
            {'tier': '10+次忠实', 'count': tier_10_plus, 'percentage': round(tier_10_plus / total * 100, 1)},
        ]
        return ok(results)
