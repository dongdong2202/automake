import datetime
from django.utils import timezone
from stores.models import Store
from devices.models import Device
from orders.models import OrderMain, ProductionTask
from inventory.models import Material

def dashboard_callback(request, context):
    try:
        today = timezone.localdate()
        context.update({
            "store_count": Store.objects.count(),
            "online_device_count": Device.objects.filter(status='online').count(),
            "today_order_count": OrderMain.objects.filter(created_at__date=today).count(),
            "today_task_count": ProductionTask.objects.filter(created_at__date=today).count(),
        })
    except Exception as e:
        context.update({
            "store_count": 0,
            "online_device_count": 0,
            "today_order_count": 0,
            "today_task_count": 0,
        })
    return context
