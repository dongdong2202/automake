from decimal import Decimal
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from utils.permissions import IsSuperAdmin, IsAdmin
from utils.response import ok, error
from stores.models import Store
from devices.models import Device, DeviceConsumableStock
from inventory.models import Material, StoreInventory, StoreInventoryRecord
from ..serializers import (
    StoreAdminSerializer, StoreInventorySerializer, StoreInventoryRecordSerializer
)
from ..filters import StandardPagination


class StoreListCreateView(APIView):
    """
    GET  /api/admin/stores/ - 门店列表（支持分页、搜索与状态过滤）
    POST /api/admin/stores/ - 创建新门店（超管专属）
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        user = request.user
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
            return error(str(serializer.errors), code=4001)

        store = serializer.save()
        return ok(StoreAdminSerializer(store).data, message='门店创建成功')


class StoreDetailView(APIView):
    """
    GET    /api/admin/stores/<int:pk>/ - 门店详情
    PUT    /api/admin/stores/<int:pk>/ - 更新门店
    DELETE /api/admin/stores/<int:pk>/ - 删除门店（超管专属）
    """
    permission_classes = [IsAdmin]

    def get_object(self, pk, user):
        try:
            store = Store.objects.get(pk=pk)
            if not user.is_super_admin and store not in user.stores.all():
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
            return error(str(serializer.errors), code=4001)

        updated_store = serializer.save()
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
            return ok(message=f'门店 [{store_name}] 已成功删除')
        except Exception as e:
            return error(f'删除门店失败: {str(e)}', code=4004)


from django.db.models import Q


class StoreInventoryListView(APIView):
    """
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
    POST /api/admin/stores/<int:store_id>/dispatch-to-device/ - 门店库存出库加料到设备
    请求参数: { "material_id": 1, "device_sn": "SN001", "quantity": 10.0, "remarks": "补料" }
    """
    permission_classes = [IsAdmin]

    def post(self, request, store_id):
        user = request.user
        store = Store.objects.filter(pk=store_id).first()
        if not store:
            return error('门店不存在', code=4041)

        if not user.is_super_admin and store not in user.stores.all():
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

        with transaction.atomic():
            store_inv = StoreInventory.objects.select_for_update().filter(store=store, material_id=material_id).first()
            if not store_inv or store_inv.quantity < quantity:
                cur_qty = store_inv.quantity if store_inv else 0
                return error(f'门店当前物料库存不足（剩余 {cur_qty}），无法出库 {quantity}', code=4005)

            # 1. 扣减门店在店库存
            store_inv.quantity -= quantity
            store_inv.save()

            material = store_inv.material

            # 2. 如果是耗材（如纸杯/杯盖/塑料杯/封口膜），更新设备耗材库存追踪表
            if material.material_type in ['consumable', 'cup']:
                dev_consumable, _ = DeviceConsumableStock.objects.get_or_create(
                    device=device,
                    code_id=material.code,
                    defaults={'quantity': 0, 'unit': material.unit or '个'}
                )
                dev_consumable.quantity += int(quantity)
                dev_consumable.save()

            # 3. 记录门店出库调拨流水
            record = StoreInventoryRecord.objects.create(
                store=store,
                material=material,
                device=device,
                record_type=StoreInventoryRecord.TYPE_OUT_TO_DEVICE,
                quantity=quantity,
                operator=user if user.is_authenticated else None,
                remarks=remarks or f'门店物料出库加料到设备 [{device.device_name or device.device_sn}]'
            )

        return ok(StoreInventorySerializer(store_inv).data, message=f'物料 [{material.name}] 成功出库加料到设备 [{device.device_name or device.device_sn}]')


class StoreInventoryRecordListView(APIView):
    """
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
