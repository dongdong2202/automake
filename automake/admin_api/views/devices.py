import logging
from django.db.models import Q
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter
from utils.permissions import IsSuperAdmin, IsAdmin
from utils.response import ok, error
from devices.models import Device, DeviceBarrelDict, DevicePoster, DeviceAlarm
from inventory.models import Material, StoreInventoryRecord
from ..serializers import (
    DeviceAdminSerializer, DeviceBarrelDictSerializer, DevicePosterSerializer,
    StoreInventoryRecordSerializer
)
from ..filters import StandardPagination

logger = logging.getLogger(__name__)


class DeviceListCreateView(APIView):
    """
    设备档案管理接口（列表查询与录入）
    """
    permission_classes = [IsAdmin]

    @extend_schema(
        summary="获取设备列表",
        description="获取设备档案列表，支持按省份 (province)、城市 (city)、状态 (status)、所属门店 (store_id) 及关键字 (search) 进行组合过滤。若不提供省市参数，则返回所有设备。",
        parameters=[
            OpenApiParameter(name='province', description='省份名称（例如：广东省、北京市，支持模糊匹配）', required=False, type=str),
            OpenApiParameter(name='city', description='城市名称（例如：广州市、深圳市，支持模糊匹配）', required=False, type=str),
            OpenApiParameter(name='store_id', description='所属门店 ID', required=False, type=int),
            OpenApiParameter(name='status', description='设备状态 (online/offline/fault)', required=False, type=str),
            OpenApiParameter(name='search', description='搜索关键字（SN、设备名称、地址）', required=False, type=str),
            OpenApiParameter(name='page', description='页码', required=False, type=int),
            OpenApiParameter(name='page_size', description='每页条数', required=False, type=int),
        ],
        responses={200: DeviceAdminSerializer(many=True)}
    )
    def get(self, request):
        user = request.user
        qs = Device.objects.all().select_related('store', 'device_model').order_by('-created_at')

        # if not user.is_super_admin:
        #     qs = qs.filter(store_id__in=user.stores.values_list('id', flat=True))

        store_id = request.query_params.get('store_id')
        status_filter = request.query_params.get('status')
        search = request.query_params.get('search', '').strip()
        province = (request.query_params.get('province') or request.query_params.get('省') or '').strip()
        city = (request.query_params.get('city') or request.query_params.get('市') or '').strip()

        if store_id:
            qs = qs.filter(store_id=store_id)
        if status_filter:
            qs = qs.filter(status=status_filter)
        if province:
            qs = qs.filter(
                Q(province__icontains=province) |
                Q(address__icontains=province) |
                Q(store__address__icontains=province)
            )
        if city:
            qs = qs.filter(
                Q(city__icontains=city) |
                Q(address__icontains=city) |
                Q(store__address__icontains=city)
            )
        if search:
            qs = qs.filter(
                Q(device_sn__icontains=search) |
                Q(device_name__icontains=search) |
                Q(address__icontains=search)
            )

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = DeviceAdminSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @extend_schema(
        summary="录入新设备档案",
        description="录入新设备档案（包含设备序列号 SN、名称、所属门店、省份 province、城市 city、详细地址、经纬度 lat/lng/gps_coordinate 等）。仅超级管理员可操作。",
        request=DeviceAdminSerializer,
        responses={200: DeviceAdminSerializer}
    )
    def post(self, request):
        if not request.user.is_super_admin:
            return error('仅超级管理员可添加设备', code=4031)

        serializer = DeviceAdminSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"[AdminDeviceCreate] 添加设备参数错误: {serializer.errors}")
            return error(str(serializer.errors), code=4001)

        device = serializer.save()
        logger.info(f"[AdminDeviceCreate] 超级管理员 {request.user.username} 录入新设备: sn={device.device_sn}, name={device.device_name}")
        return ok(DeviceAdminSerializer(device).data, message='设备添加成功')


class DeviceDetailView(APIView):
    """
    单个设备档案详情、更新与删除
    """
    permission_classes = [IsAdmin]

    @extend_schema(
        summary="获取指定设备详情",
        description="根据设备 SN 获取设备详情（包含基础信息、经纬度、省市、绑定的料桶映射字典以及实时监控快照）。",
        responses={200: DeviceAdminSerializer}
    )
    def get(self, request, sn):
        device = Device.objects.filter(device_sn=sn).select_related('store', 'device_model').first()
        if not device:
            return error('设备不存在', code=4041)

        if not request.user.is_super_admin and (not device.store or device.store not in request.user.stores.all()):
            return error('无权访问该设备', code=4031)

        data = DeviceAdminSerializer(device).data
        # 附加料桶字典
        barrel_dicts = DeviceBarrelDict.objects.filter(device=device).select_related('material')
        data['barrels'] = DeviceBarrelDictSerializer(barrel_dicts, many=True).data

        # 附加实时监控 Redis 快照
        from monitor.views import get_device_monitor_data_from_redis_or_db
        data['monitor_snapshot'] = get_device_monitor_data_from_redis_or_db(sn, device)

        return ok(data)

    @extend_schema(
        summary="更新设备档案",
        description="更新指定设备配置（包括省份 province、城市 city、经纬度 lat/lng、分配门店等）。仅超级管理员可操作。",
        request=DeviceAdminSerializer,
        responses={200: DeviceAdminSerializer}
    )
    def put(self, request, sn):
        if not request.user.is_super_admin:
            return error('仅超级管理员可修改设备配置', code=4031)

        device = Device.objects.filter(device_sn=sn).first()
        if not device:
            return error('设备不存在', code=4041)

        serializer = DeviceAdminSerializer(device, data=request.data, partial=True)
        if not serializer.is_valid():
            logger.warning(f"[AdminDeviceUpdate] 更新设备参数错误: sn={sn}, errors={serializer.errors}")
            return error(str(serializer.errors), code=4001)

        updated_device = serializer.save()
        logger.info(f"[AdminDeviceUpdate] 超级管理员 {request.user.username} 更新设备: sn={sn}, name={updated_device.device_name}")
        return ok(DeviceAdminSerializer(updated_device).data, message='设备更新成功')

    def delete(self, request, sn):
        if not request.user.is_super_admin:
            return error('仅超级管理员可删除设备', code=4031)

        device = Device.objects.filter(device_sn=sn).first()
        if not device:
            return error('设备不存在', code=4041)

        device_name = device.device_name
        device.delete()
        logger.info(f"[AdminDeviceDelete] 超级管理员 {request.user.username} 删除设备: sn={sn}, name={device_name}")
        return ok(message=f'设备 [{device_name} ({sn})] 已成功删除')


class DeviceBarrelDictListView(APIView):
    """
    GET  /api/admin/devices/<str:sn>/barrels/ - 获取指定设备的料桶字典映射
    POST /api/admin/devices/<str:sn>/barrels/ - 绑定/更新料桶与物料的映射
    """
    permission_classes = [IsAdmin]

    def get(self, request, sn):
        device = Device.objects.filter(device_sn=sn).first()
        if not device:
            return error('设备不存在', code=4041)

        dicts = DeviceBarrelDict.objects.filter(device=device).select_related('material')
        return ok(DeviceBarrelDictSerializer(dicts, many=True).data)

    def post(self, request, sn):
        device = Device.objects.filter(device_sn=sn).first()
        if not device:
            return error('设备不存在', code=4041)

        barrel_code = request.data.get('barrel_code')
        material_code = request.data.get('material_code')

        if not barrel_code or not material_code:
            return error('barrel_code 和 material_code 不能为空', code=4001)

        material = Material.objects.filter(code=material_code).first()
        if not material:
            return error(f'未找到物料编码 {material_code}', code=4042)

        update_defaults = {'material': material, 'created_by': request.user}
        if 'alarm_threshold_1' in request.data:
            update_defaults['alarm_threshold_1'] = request.data.get('alarm_threshold_1')
        if 'alarm_threshold_2' in request.data:
            update_defaults['alarm_threshold_2'] = request.data.get('alarm_threshold_2')

        barrel_obj, created = DeviceBarrelDict.objects.update_or_create(
            device=device,
            barrel_code=barrel_code,
            defaults=update_defaults
        )

        return ok(DeviceBarrelDictSerializer(barrel_obj).data, message='料桶映射配置成功')


class GlobalBarrelDictListView(APIView):
    """
    GET  /api/admin/devices/barrel-dicts/ - 全网设备料桶字典大表（支持分页、设备SN与物料筛选）
    POST /api/admin/devices/barrel-dicts/ - 绑定新料桶字典
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        qs = DeviceBarrelDict.objects.all().select_related('device', 'device__store', 'material', 'created_by').order_by('device__device_sn', 'barrel_code')

        # 门店管理员数据隔离
        if not request.user.is_super_admin:
            qs = qs.filter(device__store__in=request.user.stores.all())

        device_sn = request.query_params.get('device_sn', '').strip()
        material_code = request.query_params.get('material_code', '').strip()
        search = request.query_params.get('search', '').strip()

        if device_sn:
            qs = qs.filter(device__device_sn=device_sn)
        if material_code:
            qs = qs.filter(material__code=material_code)
        if search:
            qs = qs.filter(device__device_name__icontains=search) | qs.filter(material__name__icontains=search)

        serializer = DeviceBarrelDictSerializer(qs, many=True)
        return ok(serializer.data)

    def post(self, request):
        device_sn = request.data.get('device_sn')
        barrel_code = request.data.get('barrel_code')
        material_code = request.data.get('material_code')

        if not device_sn or not barrel_code or not material_code:
            return error('设备SN、料桶编号、物料编码均为必填项', code=4001)

        device = Device.objects.filter(device_sn=device_sn).first()
        if not device:
            return error(f'未找到设备 {device_sn}', code=4041)

        material = Material.objects.filter(code=material_code).first()
        if not material:
            return error(f'未找到物料编码 {material_code}', code=4042)

        update_defaults = {'material': material, 'created_by': request.user}
        if 'alarm_threshold_1' in request.data:
            update_defaults['alarm_threshold_1'] = request.data.get('alarm_threshold_1')
        if 'alarm_threshold_2' in request.data:
            update_defaults['alarm_threshold_2'] = request.data.get('alarm_threshold_2')

        barrel_obj, created = DeviceBarrelDict.objects.update_or_create(
            device=device,
            barrel_code=barrel_code,
            defaults=update_defaults
        )
        return ok(DeviceBarrelDictSerializer(barrel_obj).data, message='料桶映射保存成功')


class GlobalBarrelDictDetailView(APIView):
    """
    DELETE /api/admin/devices/barrel-dicts/<int:pk>/ - 解除料桶映射
    """
    permission_classes = [IsAdmin]

    def delete(self, request, pk):
        item = DeviceBarrelDict.objects.filter(pk=pk).first()
        if not item:
            return error('映射记录不存在', code=4041)

        if not request.user.is_super_admin and item.device.store not in request.user.stores.all():
            return error('无权操作此设备料桶映射', code=4031)

        item.delete()
        return ok(message='料桶映射已解除')


class DevicePosterListView(APIView):
    """
    GET  /api/admin/posters/ - 海报配置列表
    POST /api/admin/posters/ - 上传/新建海报
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        posters = DevicePoster.objects.all().prefetch_related('stores', 'devices').order_by('sort_order', '-version', '-created_at')
        serializer = DevicePosterSerializer(posters, many=True)
        return ok(serializer.data)

    def post(self, request):
        if not request.user.is_super_admin:
            return error('仅超级管理员可管理海报', code=4031)

        serializer = DevicePosterSerializer(data=request.data)
        if not serializer.is_valid():
            return error(str(serializer.errors), code=4001)

        poster = serializer.save()
        return ok(DevicePosterSerializer(poster).data, message='海报配置保存成功')


class DevicePosterDetailView(APIView):
    """
    GET    /api/admin/posters/<int:pk>/ - 海报详情
    PUT    /api/admin/posters/<int:pk>/ - 更新海报
    DELETE /api/admin/posters/<int:pk>/ - 删除海报
    """
    permission_classes = [IsAdmin]

    def get(self, request, pk):
        poster = DevicePoster.objects.filter(pk=pk).first()
        if not poster:
            return error('海报配置不存在', code=4041)
        return ok(DevicePosterSerializer(poster).data)

    def put(self, request, pk):
        if not request.user.is_super_admin:
            return error('仅超级管理员可修改海报', code=4031)

        poster = DevicePoster.objects.filter(pk=pk).first()
        if not poster:
            return error('海报配置不存在', code=4041)

        serializer = DevicePosterSerializer(poster, data=request.data, partial=True)
        if not serializer.is_valid():
            return error(str(serializer.errors), code=4001)

        updated = serializer.save()
        return ok(DevicePosterSerializer(updated).data, message='海报配置更新成功')

    def delete(self, request, pk):
        if not request.user.is_super_admin:
            return error('仅超级管理员可删除海报', code=4031)

        poster = DevicePoster.objects.filter(pk=pk).first()
        if not poster:
            return error('海报配置不存在', code=4041)

        poster.delete()
        return ok(message='海报配置已删除')


class DeviceStockOverviewView(APIView):
    """
    GET /api/admin/devices/stocks-overview/ - 获取设备物料与耗材传感器实时库存看板
    支持 store_id 和 device_sn 筛选
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        user = request.user
        qs = Device.objects.all().select_related('store', 'device_model').order_by('store__id', 'device_sn')

        if not user.is_super_admin:
            qs = qs.filter(store_id__in=user.stores.values_list('id', flat=True))

        store_id = request.query_params.get('store_id')
        device_sn = request.query_params.get('device_sn')

        if store_id:
            qs = qs.filter(store_id=store_id)
        if device_sn:
            qs = qs.filter(device_sn=device_sn)

        from monitor.views import get_device_monitor_data_from_redis_or_db
        from devices.models import DeviceBarrel, DeviceConsumableStock, DeviceBarrelDict

        results = []
        for dev in qs:
            sn = dev.device_sn
            monitor_data = get_device_monitor_data_from_redis_or_db(sn, dev)

            # 1. 解析料桶 (thinP, thickP, solidP)
            barrel_mappings = {
                b.barrel_code: (b.material.code if b.material else '', b.material.name if b.material else '')
                for b in DeviceBarrelDict.objects.filter(device=dev).select_related('material')
            }
            barrel_configs = {
                bc.barrel_id: bc.max_v
                for bc in DeviceBarrel.objects.filter(device=dev)
            }

            barrels = []
            raw_barrels = monitor_data.get('barrel_details', {})
            if not raw_barrels:
                for idx in range(1, 13):
                    b_code = f"b{idx:02d}"
                    raw_barrels[b_code] = {'volume': 0, 'damaged': False}

            for b_code, b_info in raw_barrels.items():
                mat_code, mat_name = barrel_mappings.get(b_code, ('', ''))
                max_v = barrel_configs.get(b_code, 40000)
                vol = b_info.get('volume', 0) if isinstance(b_info, dict) else 0
                damaged = b_info.get('damaged', False) if isinstance(b_info, dict) else False
                pct = round(min(100.0, (vol / max_v) * 100), 1) if max_v > 0 else 0.0

                barrels.append({
                    'barrel_code': b_code,
                    'material_code': mat_code,
                    'material_name': mat_name or f'料桶 {b_code}',
                    'volume': vol,
                    'max_volume': max_v,
                    'percentage': pct,
                    'damaged': damaged,
                    'is_low': vol < 5000 and not damaged
                })

            # 2. 解析耗材仓 (纸杯/塑料杯/杯盖/封口膜)
            consumables = []
            consumable_db = {
                cs.code_id: cs
                for cs in DeviceConsumableStock.objects.filter(device=dev)
            }
            default_consumables = [
                ('paperL', '大号纸杯 (paperL)', '个', 100),
                ('paperM', '中号纸杯 (paperM)', '个', 100),
                ('plasticL', '大号塑料杯 (plasticL)', '个', 100),
                ('plasticM', '中号塑料杯 (plasticM)', '个', 100),
                ('membrane', '封口膜 (membrane)', '张', 500),
                ('lid', '杯盖 (lid)', '个', 200),
            ]

            for code, name, unit, def_init in default_consumables:
                cs_obj = consumable_db.get(code)
                cur_qty = cs_obj.quantity if cs_obj else 80
                init_qty = cs_obj.init_quantity if cs_obj else def_init
                warn_lvl = cs_obj.warn_level if cs_obj else 15
                pct = round(min(100.0, (cur_qty / init_qty) * 100), 1) if init_qty > 0 else 0.0

                consumables.append({
                    'code': code,
                    'name': name,
                    'quantity': cur_qty,
                    'init_quantity': init_qty,
                    'unit': unit,
                    'warn_level': warn_lvl,
                    'percentage': pct,
                    'is_low': cur_qty <= warn_lvl
                })

            results.append({
                'device_sn': sn,
                'device_name': dev.device_name or sn,
                'store_id': dev.store_id,
                'store_name': dev.store.name if dev.store else '未分配门店',
                'status': dev.status,
                'last_heartbeat_at': dev.last_heartbeat_at.strftime('%Y-%m-%d %H:%M:%S') if dev.last_heartbeat_at else None,
                'barrels': barrels,
                'consumables': consumables,
            })

        return ok(results)


class DeviceInventoryRecordListView(APIView):
    """
    GET /api/admin/devices/records/ 或 GET /api/admin/devices/<str:sn>/records/
    查询设备当前的加料/出库流水记录（支持按门店、设备SN、物料及关键字筛选）
    """
    permission_classes = [IsAdmin]

    def get(self, request, sn=None):
        user = request.user
        qs = StoreInventoryRecord.objects.filter(
            device__isnull=False
        ).select_related('store', 'material', 'device', 'operator').order_by('-created_at')

        if not user.is_super_admin:
            qs = qs.filter(store_id__in=user.stores.values_list('id', flat=True))

        target_sn = sn or request.query_params.get('device_sn')
        store_id = request.query_params.get('store_id')
        material_id = request.query_params.get('material_id')
        search = request.query_params.get('search', '').strip()

        if target_sn:
            qs = qs.filter(device__device_sn=target_sn)
        if store_id:
            qs = qs.filter(store_id=store_id)
        if material_id:
            qs = qs.filter(material_id=material_id)
        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(material__name__icontains=search) |
                Q(material__code__icontains=search) |
                Q(device__device_sn__icontains=search) |
                Q(device__device_name__icontains=search) |
                Q(remarks__icontains=search)
            )

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = StoreInventoryRecordSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class DeviceConsumableStockUpdateView(APIView):
    """
    POST /api/admin/devices/<str:sn>/consumables/update/
    PC Web 管理端录入/调整设备耗材库存
    入参：{ "items": [{"code": "paperL", "quantity": 100}, {"code": "lid", "quantity": 100}] }
    """
    permission_classes = [IsAdmin]

    def post(self, request, sn):
        device = Device.objects.filter(device_sn=sn.strip()).first()
        if not device:
            return error('未找到该设备', code=2001, status=404)

        items = request.data.get('items', [])
        if not items or not isinstance(items, list):
            return error('耗材数据 (items) 不能为空且必须为列表', code=2002)

        from inventory.services import update_device_consumable_stock
        updated = update_device_consumable_stock(
            device=device,
            items=items,
            operator=request.user if request.user.is_authenticated else None,
            remarks=f'PC Web管理端耗材录入 ({request.user.username if request.user.is_authenticated else "管理员"})'
        )

        return ok(updated, message='耗材库存已成功录入并实时同步至 Redis')

