import datetime
import json
from django.utils import timezone
from django.db.models import Count, Sum
from stores.models import Store
from devices.models import Device
from orders.models import OrderMain, ProductionTask, OrderItem
from inventory.models import Material

def dashboard_callback(request, context):
    try:
        today = timezone.localdate()
        
        # 1. 设备状态分布
        devices = Device.objects.all()
        online_count = devices.filter(status='online').count()
        offline_count = devices.filter(status='offline').count()
        fault_count = devices.filter(status='fault').count()
        
        # 2. 近7天经营数据趋势 (订单量 & 营收)
        labels = []
        orders_data = []
        revenue_data = []
        for i in range(6, -1, -1):
            date = today - datetime.timedelta(days=i)
            labels.append(date.strftime('%m-%d'))
            
            # 只统计已付款及以上状态的订单
            daily_orders = OrderMain.objects.filter(
                created_at__date=date,
                status__in=[OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING, OrderMain.STATUS_DONE]
            )
            orders_count = daily_orders.count()
            revenue = daily_orders.aggregate(total=Sum('pay_amount'))['total'] or 0
            
            orders_data.append(orders_count)
            revenue_data.append(revenue / 100.0)  # 分转元
            
        # 3. 热门商品销量 TOP 5
        top_items = OrderItem.objects.filter(
            order__status__in=[OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING, OrderMain.STATUS_DONE]
        ).values('item_name').annotate(total_qty=Sum('quantity')).order_by('-total_qty')[:5]
        
        top_items_labels = [item['item_name'] for item in top_items]
        top_items_data = [item['total_qty'] for item in top_items]
        
        context.update({
            "store_count": Store.objects.count(),
            "online_device_count": online_count,
            "today_order_count": OrderMain.objects.filter(created_at__date=today).count(),
            "today_task_count": ProductionTask.objects.filter(created_at__date=today).count(),
            
            "device_status_json": json.dumps([online_count, offline_count, fault_count]),
            "trend_labels_json": json.dumps(labels),
            "orders_trend_json": json.dumps(orders_data),
            "revenue_trend_json": json.dumps(revenue_data),
            "top_items_labels_json": json.dumps(top_items_labels),
            "top_items_data_json": json.dumps(top_items_data),
        })
    except Exception as e:
        context.update({
            "store_count": 0,
            "online_device_count": 0,
            "today_order_count": 0,
            "today_task_count": 0,
            "device_status_json": "[]",
            "trend_labels_json": "[]",
            "orders_trend_json": "[]",
            "revenue_trend_json": "[]",
            "top_items_labels_json": "[]",
            "top_items_data_json": "[]",
        })
    return context
