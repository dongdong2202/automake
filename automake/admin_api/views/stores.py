"""
后台门店管理与门店物料库存视图 (admin_api.views.stores)

接口列表：
- GET    /api/admin/stores/                             门店列表查询（支持名称、状态组合筛选）
- POST   /api/admin/stores/                             创建新门店（超级管理员专属）
- GET    /api/admin/stores/<int:pk>/                    获取指定门店详情
- PUT    /api/admin/stores/<int:pk>/                    修改门店信息（营业时间、地址、电话等）
- DELETE /api/admin/stores/<int:pk>/                    删除门店（严格防误删校验，存在设备或订单禁止物理删除）
- GET    /api/admin/stores/inventory/                   门店物料库存查询
- POST   /api/admin/stores/<int:store_id>/dispatch-to-device/ 门店物料出库并加料至指定设备
- GET    /api/admin/stores/records/                     门店进出库调拨台账流水
"""

import logging
from decimal import Decimal
from django.db import transaction
from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from utils.permissions import IsSuperAdmin, IsAdmin
from utils.response import ok, error
from stores.models import Store
from devices.models import Device, DeviceConsumableStock
from inventory.models import Material, StoreInventory, StoreInventoryRecord, StoreInventoryBatch
from inventory.services import dispatch_store_to_device_fefo
from ..serializers import (
    StoreAdminSerializer, StoreInventorySerializer, StoreInventoryRecordSerializer, StoreInventoryBatchSerializer
)
from ..filters import StandardPagination

logger = logging.getLogger(__name__)


class StoreListCreateView(APIView):
    """
    门店列表查询与创建接口

    GET  /api/admin/stores/ - 门店列表（支持分页、搜索与状态过滤）
    POST /api/admin/stores/ - 创建新门店（超管专属）
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        user = request.user
        logger.debug(f"[AdminStoreList] 管理员 {user.username} 查询门店列表")
        qs = Store.objects.all().order_by('sort_order', 'id')

        # 门店管理员只能看关联门店
        if not user.is_super_admin:
            qs = qs.filter(id__in=user.stores.values_list('id', flat=True))

        search = request.query_params.get('search', '').strip()
        status_filter = request.query_params.get('status', '').strip()

        if search:
            qs = qs.filter(name__icontains=search)
        if status_filter:
            qs = qs.filter(status=status_filter)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = StoreAdminSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        if not request.user.is_super_admin:
            return error('仅超级管理员可创建门店', code=4031)

        serializer = StoreAdminSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"[AdminStoreCreate] 参数错误: {serializer.errors}")
            return error(str(serializer.errors), code=4001)

        store = serializer.save()
        logger.info(f"[AdminStoreCreate] 超级管理员 {request.user.username} 创建门店成功: store_id={store.id}, name={store.name}")
        return ok(StoreAdminSerializer(store).data, message='门店创建成功')


class StoreDetailView(APIView):
    """
    门店详情查询、更新与删除接口

    GET    /api/admin/stores/<int:pk>/ - 门店详情
    PUT    /api/admin/stores/<int:pk>/ - 更新门店
    DELETE /api/admin/stores/<int:pk>/ - 删除门店（超管专属，具备防误删保护）
    """
    permission_classes = [IsAdmin]

    def get_object(self, pk, user):
        try:
            store = Store.objects.get(pk=pk)
            if not user.is_super_admin and not user.stores.filter(id=store.id).exists():
                return None
            return store
        except Store.DoesNotExist:
            return None

    def get(self, request, pk):
        store = self.get_object(pk, request.user)
        if not store:
            return error('门店不存在或无权访问', code=4041)
        return ok(StoreAdminSerializer(store).data)

    def put(self, request, pk):
        if not request.user.is_super_admin:
            return error('仅超级管理员可修改门店基本信息', code=4031)

        store = self.get_object(pk, request.user)
        if not store:
            return error('门店不存在', code=4041)

        serializer = StoreAdminSerializer(store, data=request.data, partial=True)
        if not serializer.is_valid():
            logger.warning(f"[AdminStoreUpdate] 更新门店参数错误: store_id={pk}, errors={serializer.errors}")
            return error(str(serializer.errors), code=4001)

        updated_store = serializer.save()
        logger.info(f"[AdminStoreUpdate] 超级管理员 {request.user.username} 更新门店: store_id={pk}, name={updated_store.name}")
        return ok(StoreAdminSerializer(updated_store).data, message='门店信息更新成功')

    def delete(self, request, pk):
        if not request.user.is_super_admin:
            return error('仅超级管理员可删除门店', code=4031)

        store = self.get_object(pk, request.user)
        if not store:
            return error('门店不存在', code=4041)

        device_count = store.devices.count()
        if device_count > 0:
            return error(f'该门店下存在 {device_count} 台关联设备，请先在设备管理中解绑或迁移设备后再删除', code=4002)

        order_count = store.orders.count()
        if order_count > 0:
            return error(
                f'该门店已产生 {order_count} 笔历史业务订单，为保证财务与订单履约审计记录完整性，不可物理删除。建议将门店状态设置为“暂停营业”或“已闭店”。',
                code=4003
            )

        try:
            store_name = store.name
            store.delete()
            logger.info(f"[AdminStoreDelete] 超级管理员 {request.user.username} 删除门店: store_id={pk}, name={store_name}")
            return ok(message=f'门店 [{store_name}] 已成功删除')
        except Exception as e:
            logger.exception(f"[AdminStoreDelete] 删除门店异常: store_id={pk}, error={e}")
            return error(f'删除门店失败: {str(e)}', code=4004)


class StoreInventoryListView(APIView):
    """
    门店物料库存查询接口

    GET /api/admin/stores/inventory/ 或 GET /api/admin/stores/<int:store_id>/inventory/
    获取门店当前的物料库存列表（支持全部门店或指定门店筛选）
    """
    permission_classes = [IsAdmin]

    def get(self, request, store_id=None):
        user = request.user
        s_id = store_id or request.query_params.get('store_id')

        qs = StoreInventory.objects.all().select_related('store', 'material').order_by('store__id', 'material__code')

        if not user.is_super_admin:
            qs = qs.filter(store_id__in=user.stores.values_list('id', flat=True))

        if s_id:
            qs = qs.filter(store_id=s_id)

        search = request.query_params.get('search', '').strip()
        mat_type = request.query_params.get('material_type', '').strip()

        if search:
            qs = qs.filter(
                Q(material__name__icontains=search) |
                Q(material__code__icontains=search) |
                Q(store__name__icontains=search)
            )
        if mat_type:
            qs = qs.filter(material__material_type=mat_type)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = StoreInventorySerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class StoreDispatchToDeviceView(APIView):
    """
    门店库存出库加料到设备接口

    POST /api/admin/stores/<int:store_id>/dispatch-to-device/
    请求参数: { "material_id": 1, "device_sn": "SN001", "quantity": 10.0, "remarks": "补料" }
    """
    permission_classes = [IsAdmin]

    def post(self, request, store_id):
        user = request.user
        store = Store.objects.filter(pk=store_id).first()
        if not store:
            return error('门店不存在', code=4041)

        if not user.is_super_admin and not user.stores.filter(id=store.id).exists():
            return error('无权操作该门店库存', code=4031)

        material_id = request.data.get('material_id')
        device_sn = request.data.get('device_sn', '').strip()
        quantity_raw = request.data.get('quantity')
        remarks = request.data.get('remarks', '').strip()

        if not material_id or not device_sn or not quantity_raw:
            return error('material_id, device_sn 和 quantity 为必填项', code=4001)

        try:
            quantity = Decimal(str(quantity_raw))
            if quantity <= 0:
                return error('出库加料数量必须大于 0', code=4002)
        except Exception:
            return error('无效的出库数量', code=4003)

        device = Device.objects.filter(device_sn=device_sn, store=store).first()
        if not device:
            return error(f'设备 {device_sn} 不属于当前门店 [{store.name}]', code=4004)

        try:
            store_inv, records = dispatch_store_to_device_fefo(
                store=store,
                material=material_id,
                device=device,
                quantity=quantity,
                operator=user if user.is_authenticated else None,
                remarks=remarks
            )
        except Exception as e:
            return error(f'加料失败: {str(e)}', code=4005)
        material_name = store_inv.material.name
        logger.info(
            f"[AdminStoreDispatch] 管理员 {user.username} 成功出库加料: store={store.name}, "
            f"device={device.device_sn}, material={material_name}, quantity={quantity}"
        )
        return ok(StoreInventorySerializer(store_inv).data, message=f'物料 [{material_name}] 成功出库加料到设备 [{device.device_name or device.device_sn}]')


class StoreInventoryRecordListView(APIView):
    """
    门店进出库调拨流水台账接口

    GET /api/admin/stores/records/ 或 GET /api/admin/stores/<int:store_id>/records/
    查询门店的进出库调拨流水台账（支持查看全部门店或按门店、类型、物料筛选）
    """
    permission_classes = [IsAdmin]

    def get(self, request, store_id=None):
        user = request.user
        qs = StoreInventoryRecord.objects.all().select_related(
            'store', 'material', 'device', 'operator'
        ).order_by('-created_at')

        if not user.is_super_admin:
            qs = qs.filter(store_id__in=user.stores.values_list('id', flat=True))

        s_id = store_id or request.query_params.get('store_id')
        if s_id:
            qs = qs.filter(store_id=s_id)

        record_type = request.query_params.get('record_type')
        material_id = request.query_params.get('material_id')
        search = request.query_params.get('search', '').strip()

        if record_type:
            qs = qs.filter(record_type=record_type)
        if material_id:
            qs = qs.filter(material_id=material_id)
        if search:
            qs = qs.filter(
                Q(material__name__icontains=search) |
                Q(material__code__icontains=search) |
                Q(store__name__icontains=search) |
                Q(remarks__icontains=search)
            )

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = StoreInventoryRecordSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class StoreBatchListView(APIView):
    """
    门店物料批次库存明细查询接口
    GET /api/admin/stores/<int:store_id>/batches/ 或 GET /api/admin/stores/batches/
    查询门店当前各物料在店批次库存、过期时间与采购成本
    """
    permission_classes = [IsAdmin]

    def get(self, request, store_id=None):
        user = request.user
        qs = StoreInventoryBatch.objects.all().select_related(
            'store', 'material', 'source_inbound'
        ).order_by('expiration_date', 'created_at')

        if not user.is_super_admin:
            qs = qs.filter(store_id__in=user.stores.values_list('id', flat=True))

        s_id = store_id or request.query_params.get('store_id')
        if s_id:
            qs = qs.filter(store_id=s_id)

        material_id = request.query_params.get('material_id')
        if material_id:
            qs = qs.filter(material_id=material_id)

        batch_no = request.query_params.get('batch_no')
        if batch_no:
            qs = qs.filter(batch_no__icontains=batch_no)

        has_stock = request.query_params.get('has_stock')
        if has_stock and str(has_stock).lower() in ('true', '1'):
            qs = qs.filter(quantity__gt=0)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = StoreInventoryBatchSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)
