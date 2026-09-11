import json
import logging
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from django_redis import get_redis_connection

from utils.response import ok, error
from devices.models import Device
from .models import DeviceMonitorSnapshot
from .serializers import DeviceMonitorSnapshotSerializer

logger = logging.getLogger('monitor')


def get_device_monitor_data_from_redis_or_db(device_sn: str, device_obj: Device = None, cached_raw=None) -> dict:
    """
    辅助函数：优先从 Redis 读取设备的实时监控快照，无缓存时回退到 MySQL 数据库
    支持传入 cached_raw 避免批量请求时产生 Redis N+1。
    """
    cached_data = cached_raw
    if cached_data is None:
        redis_conn = get_redis_connection("default")
        snapshot_key = f"automake:monitor:snapshot:{device_sn}"
        cached_data = redis_conn.get(snapshot_key)

    if cached_data:
        try:
            if isinstance(cached_data, bytes):
                cached_data = cached_data.decode('utf-8')
            data = json.loads(cached_data)
            if not isinstance(data, dict):
                data = {}
            data['device_sn'] = device_sn
            if device_obj:
                data['device_name'] = device_obj.device_name
                data['store_id'] = device_obj.store_id
                data['store_name'] = device_obj.store.name if device_obj.store else ''
                if not data.get('reported_at') and device_obj.last_heartbeat_at:
                    data['reported_at'] = device_obj.last_heartbeat_at.isoformat()
            if 'display_status' not in data:
                healthy = data.get('healthy', True)
                disconnected = data.get('disconnected', False)
                if disconnected:
                    data['display_status'] = 'fault'
                elif healthy:
                    data['display_status'] = 'normal'
                else:
                    data['display_status'] = 'warning'
            return data
        except Exception as e:
            logger.warning(f"解析 Redis 设备快照失败: {e}")

    # 回退到数据库查询最新一条快照
    db_snapshot = DeviceMonitorSnapshot.objects.filter(device_sn=device_sn).order_by('-reported_at').first()
    if db_snapshot:
        serializer = DeviceMonitorSnapshotSerializer(db_snapshot)
        res_data = dict(serializer.data)
        if device_obj:
            res_data['device_name'] = device_obj.device_name
            res_data['store_id'] = device_obj.store_id
            res_data['store_name'] = device_obj.store.name if device_obj.store else ''
        return res_data

    # 设备尚无任何上报快照
    status = device_obj.status if device_obj else Device.STATUS_OFFLINE
    return {
        'device_sn': device_sn,
        'device_name': device_obj.device_name if device_obj else '',
        'store_id': device_obj.store_id if device_obj else None,
        'store_name': device_obj.store.name if (device_obj and device_obj.store) else '',
        'healthy': (status == Device.STATUS_ONLINE),
        'disconnected': (status == Device.STATUS_OFFLINE),
        'display_status': 'normal' if status == Device.STATUS_ONLINE else 'fault',
        'free': {},
        'temperature': {},
        'materials': {},
        'cups': {},
        'abnormalities': {},
        'reported_at': device_obj.last_heartbeat_at.isoformat() if (device_obj and device_obj.last_heartbeat_at) else None,
    }


class DeviceMonitorListView(APIView):
    """
    GET /api/monitor/devices/
    返回所有设备的最新监控快照（包含状态、物料、异常信息）。
    采用 Redis MGET 批量高速读取，消除循环单次请求开销。
    """
    permission_classes = [AllowAny]

    def get(self, request):
        devices = list(Device.objects.all().select_related('store').order_by('device_sn'))
        if not devices:
            return ok([])

        redis_conn = get_redis_connection("default")
        keys = [f"automake:monitor:snapshot:{dev.device_sn}" for dev in devices]
        cached_list = redis_conn.mget(*keys) if keys else []
        cached_map = dict(zip([dev.device_sn for dev in devices], cached_list))

        results = []
        for dev in devices:
            raw = cached_map.get(dev.device_sn)
            info = get_device_monitor_data_from_redis_or_db(dev.device_sn, dev, cached_raw=raw)
            results.append(info)
        return ok(results)


class DeviceMonitorDetailView(APIView):
    """
    GET /api/monitor/devices/{sn}/
    返回指定设备序列号的最新监控快照。
    优先直接从 Redis 高速读取。
    """
    permission_classes = [AllowAny]

    def get(self, request, sn):
        device = Device.objects.filter(device_sn=sn).select_related('store').first()
        if not device:
            # 检查是否有快照
            if not DeviceMonitorSnapshot.objects.filter(device_sn=sn).exists():
                return error(f'设备 {sn} 尚无监控数据', code=4041, status=404)

        data = get_device_monitor_data_from_redis_or_db(sn, device)
        return ok(data)

