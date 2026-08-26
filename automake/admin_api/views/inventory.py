from decimal import Decimal
from django.db import transaction
from rest_framework.views import APIView
from utils.permissions import IsAdmin, IsMaterialAdmin
from utils.response import ok, error
from inventory.models import Material, InventoryRecord
from stores.models import Store
from ..serializers import MaterialSerializer, InventoryRecordSerializer
from ..filters import StandardPagination


class MaterialListCreateView(APIView):
    """
    GET  /api/admin/inventory/materials/ - 物料列表（支持分页、类别过滤与搜索）
    POST /api/admin/inventory/materials/ - 新增物料（物料员/超管）
    """
    permission_classes = [IsMaterialAdmin]

    def get(self, request):
        qs = Material.objects.all().order_by('code')
        mat_type = request.query_params.get('material_type')
        search = request.query_params.get('search', '').strip()

        if mat_type:
            qs = qs.filter(material_type=mat_type)
        if search:
            qs = qs.filter(name__icontains=search) | qs.filter(code__icontains=search)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = MaterialSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        initial_data = request.data.copy()
        initial_qty_val = initial_data.get('quantity', 0)
        try:
            initial_qty = Decimal(str(initial_qty_val))
        except Exception:
            initial_qty = Decimal('0')

        initial_data['quantity'] = 0
        serializer = MaterialSerializer(data=initial_data)
        if not serializer.is_valid():
            return error(str(serializer.errors), code=4001)

        material = serializer.save()

        # 如果建档时录入了大于 0 的初始库存，通过生成初始入库流水记录进行入库并登记保质期批次
        if initial_qty and initial_qty > 0:
            from inventory.models import calculate_default_expiration_date
            exp_date = calculate_default_expiration_date(material)
            record = InventoryRecord(
                material=material,
                record_type=InventoryRecord.RECORD_TYPE_IN,
                quantity=initial_qty,
                price=material.price if material.price is not None else Decimal('0.00'),
                expiration_date=exp_date,
                operator=request.user if request.user.is_authenticated else None,
                remarks='新建物料品类初始建档入库'
            )
            record.save()
            material.refresh_from_db()

        return ok(MaterialSerializer(material).data, message='物料添加成功')


class MaterialDetailView(APIView):
    """
    GET    /api/admin/inventory/materials/<int:pk>/ - 物料详情
    PUT    /api/admin/inventory/materials/<int:pk>/ - 编辑物料
    DELETE /api/admin/inventory/materials/<int:pk>/ - 删除物料
    """
    permission_classes = [IsMaterialAdmin]

    def get(self, request, pk):
        material = Material.objects.filter(pk=pk).first()
        if not material:
            return error('物料不存在', code=4041)
        return ok(MaterialSerializer(material).data)

    def put(self, request, pk):
        material = Material.objects.filter(pk=pk).first()
        if not material:
            return error('物料不存在', code=4041)

        serializer = MaterialSerializer(material, data=request.data, partial=True)
        if not serializer.is_valid():
            return error(str(serializer.errors), code=4001)

        updated_mat = serializer.save()
        return ok(MaterialSerializer(updated_mat).data, message='物料信息修改成功')

    def delete(self, request, pk):
        if not request.user.is_super_admin:
            return error('仅超级管理员可删除物料元数据', code=4031)

        material = Material.objects.filter(pk=pk).first()
        if not material:
            return error('物料不存在', code=4041)

        if material.records.exists():
            return error('该物料已有进出库流水记录，不可直接删除', code=4002)

        material.delete()
        return ok(message='物料删除成功')


class InventoryRecordListCreateView(APIView):
    """
    GET  /api/admin/inventory/records/ - 进出库流水列表
    POST /api/admin/inventory/records/ - 登记入库/出库单（事务保证原子性）
    """
    permission_classes = [IsMaterialAdmin]

    def get(self, request):
        qs = InventoryRecord.objects.all().select_related(
            'material', 'store', 'operator'
        ).order_by('-created_at')

        record_type = request.query_params.get('record_type')
        store_id = request.query_params.get('store_id')
        material_id = request.query_params.get('material_id')

        if record_type:
            qs = qs.filter(record_type=record_type)
        if store_id:
            qs = qs.filter(store_id=store_id)
        if material_id:
            qs = qs.filter(material_id=material_id)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = InventoryRecordSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        """
        向导式入库/出库接口：
        入库请求: { "material_id": 1, "record_type": "in", "quantity": 50.0, "price": 45.0, "remarks": "..." }
        出库请求: { "material_id": 1, "record_type": "out", "quantity": 10.0, "store_id": 100001, "remarks": "..." }
        """
        material_id = request.data.get('material_id')
        record_type = request.data.get('record_type')
        quantity = request.data.get('quantity')
        price = request.data.get('price', 0.0)
        store_id = request.data.get('store_id')
        remarks = request.data.get('remarks', '')

        if not material_id or not record_type or not quantity:
            return error('物料、记录类型和数量为必填项', code=4001)

        try:
            qty_decimal = Decimal(str(quantity))
            if qty_decimal <= 0:
                return error('数量必须大于 0', code=4002)
        except Exception:
            return error('数量格式不正确', code=4003)

        material = Material.objects.filter(pk=material_id).first()
        if not material:
            return error('指定的物料不存在', code=4041)

        store_obj = None
        if record_type == InventoryRecord.RECORD_TYPE_OUT:
            if not store_id:
                return error('出库分拨到门店时，必须选择目标门店', code=4004)
            store_obj = Store.objects.filter(pk=store_id).first()
            if not store_obj:
                return error('指定的目标门店不存在', code=4042)

        try:
            record = InventoryRecord(
                material=material,
                record_type=record_type,
                quantity=qty_decimal,
                price=Decimal(str(price)) if price else None,
                store=store_obj,
                operator=request.user,
                remarks=remarks
            )
            record.save()
            return ok(InventoryRecordSerializer(record).data, message='进出库单登记成功，库存已更新')
        except Exception as e:
            return error(f'登记失败: {str(e)}', code=4005)


class CheckInventoryExpirationView(APIView):
    """
    POST /api/admin/inventory/check-expiration/ - 手动触发全库物料保质期扫描与告警推送
    GET  /api/admin/inventory/expiration-summary/ - 获取全库物料保质期健康汇总与临期批次列表
    """
    permission_classes = [IsMaterialAdmin]

    def post(self, request):
        days = int(request.data.get('days', 30))
        force = bool(request.data.get('force', False))
        from inventory.tasks import check_inventory_expiration_task
        result = check_inventory_expiration_task(alert_days=days, force=force)
        return ok(result, message='物料保质期全库扫描与告警分发完成')

    def get(self, request):
        from django.utils import timezone
        from datetime import timedelta
        today = timezone.now().date()
        threshold_date = today + timedelta(days=30)

        records = InventoryRecord.objects.filter(
            record_type=InventoryRecord.RECORD_TYPE_IN,
            expiration_date__isnull=False,
            expiration_date__lte=threshold_date,
            material__quantity__gt=0
        ).select_related('material', 'store', 'operator').order_by('expiration_date')

        expired_list = []
        expiring_soon_list = []

        for r in records:
            data = InventoryRecordSerializer(r).data
            days_left = data.get('days_until_expiration')
            if days_left is not None and days_left < 0:
                expired_list.append(data)
            else:
                expiring_soon_list.append(data)

        return ok({
            'today': str(today),
            'threshold_days': 30,
            'expired_count': len(expired_list),
            'expiring_soon_count': len(expiring_soon_list),
            'expired_batches': expired_list,
            'expiring_soon_batches': expiring_soon_list,
        })
