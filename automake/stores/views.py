"""
门店模块视图

接口列表：
- GET /api/store/list        获取门店列表（公开，无需登录）
- GET /api/store/{id}/       获取单个门店详情
"""

from rest_framework.views import APIView
from rest_framework.permissions import AllowAny

from utils.response import ok, error
from .models import Store
from .serializers import StoreListSerializer, StoreDetailSerializer


class StoreListView(APIView):
    """
    门店列表接口

    GET /api/store/list
    返回所有营业中（status=open）的门店列表。
    小程序端通过此接口展示可选门店，支持按经纬度排序（前端计算）。
    """
    permission_classes = [AllowAny]  # 门店列表无需登录

    def get(self, request):
        from devices.models import Device
        # 返回所有营业中的门店与下属设备独立列表，按排序权重升序
        # 仅包含 online 正常在线设备，offline 离线或 fault 故障设备直接过滤不返回
        stores = Store.objects.filter(status=Store.STATUS_OPEN).prefetch_related('devices').order_by('sort_order', 'id')
        data = []
        for store in stores:
            online_devices = [d for d in store.devices.all() if d.status == Device.STATUS_ONLINE]
            all_devices_count = store.devices.count()

            if online_devices:
                for dev in online_devices:
                    dev_address = (dev.address or '').strip() or (store.address or '').strip()
                    dev_lat = str(dev.lat) if dev.lat is not None else (str(store.lat) if store.lat is not None else None)
                    dev_lng = str(dev.lng) if dev.lng is not None else (str(store.lng) if store.lng is not None else None)
                    item = {
                        'id': store.id,
                        'device_id': dev.id,
                        'name': dev.device_name or store.name,
                        'store_name': store.name,
                        'address': dev_address,
                        'lat': dev_lat,
                        'lng': dev_lng,
                        'contact_phone': store.contact_phone or '',
                        'status': store.status,
                        'device_status': dev.status,
                        'cover_image': str(store.cover_image) if store.cover_image else '',
                        'business_hours': store.business_hours or {},
                        'sort_order': store.sort_order,
                        'code': dev.key_code or store.code,
                        'device_sn': dev.device_sn,
                        'is_in_business_hours': store.is_in_business_hours,
                        'business_status_text': store.business_status_text
                    }
                    data.append(item)
            elif all_devices_count == 0:
                item = {
                    'id': store.id,
                    'device_id': None,
                    'name': store.name,
                    'store_name': store.name,
                    'address': store.address or '',
                    'lat': str(store.lat) if store.lat is not None else None,
                    'lng': str(store.lng) if store.lng is not None else None,
                    'contact_phone': store.contact_phone or '',
                    'status': store.status,
                    'device_status': 'online',
                    'cover_image': str(store.cover_image) if store.cover_image else '',
                    'business_hours': store.business_hours or {},
                    'sort_order': store.sort_order,
                    'code': store.code,
                    'device_sn': store.code or f"DEV_{store.id}",
                    'is_in_business_hours': store.is_in_business_hours,
                    'business_status_text': store.business_status_text
                }
                data.append(item)
        return ok(data)


class StoreDetailView(APIView):
    """
    门店详情接口

    GET /api/store/{store_id}/
    返回指定门店的详细信息（含营业时间、描述等）。
    """
    permission_classes = [AllowAny]

    def get(self, request, store_id):
        try:
            store = Store.objects.get(pk=store_id)
        except Store.DoesNotExist:
            return error('门店不存在', code=2001, status=404)

        serializer = StoreDetailSerializer(store)
        return ok(serializer.data)
