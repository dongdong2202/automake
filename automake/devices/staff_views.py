"""
物料员与协调员移动端操作 API
提供物料员耗材补料录入、协调员设备运维与取餐操作
"""

import logging
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from utils.response import ok, error
from utils.permissions import IsAdminOrMaterialAdmin, IsAdminUser
from devices.models import Device, DeviceConsumableStock, DeviceMaterialStock, DeviceCommand
from inventory.models import Material
from django_redis import get_redis_connection

logger = logging.getLogger(__name__)


class StaffDeviceListView(APIView):
    """
    工作人员设备列表
    GET /api/staff/devices
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        qs = Device.objects.select_related('store', 'device_model')
        
        # 门店管理员/物料员仅查自己门店的设备；超级管理员查看全部
        if not user.is_super_admin:
            user_stores = user.stores.all()
            if user_stores.exists():
                qs = qs.filter(store__in=user_stores)

        data = [
            {
                'id': d.id,
                'device_sn': d.device_sn,
                'device_name': d.device_name or f"设备 {d.device_sn}",
                'store_id': d.store_id,
                'store_name': d.store.name if d.store else '未分配门店',
                'model_name': d.device_model.name if d.device_model else '标准型号',
                'status': d.status,
                'status_display': d.get_status_display(),
                'address': d.address or (d.store.address if d.store else ''),
                'gps_coordinate': d.gps_coordinate or (f"{d.store.lat},{d.store.lng}" if (d.store and d.store.lat and d.store.lng) else ''),
                'last_heartbeat_at': d.last_heartbeat_at.strftime('%Y-%m-%d %H:%M:%S') if d.last_heartbeat_at else '-'
            }
            for d in qs
        ]
        return ok(data)


class StaffDeviceStockView(APIView):
    """
    查看指定设备的耗材与物料库存
    GET /api/staff/devices/<device_sn>/stock
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, device_sn):
        try:
            device = Device.objects.get(device_sn=device_sn)
        except Device.DoesNotExist:
            return error('未找到该设备', code=2001, status=404)

        # 1. 耗材列表 (杯子、杯盖、封口膜)
        default_consumables = [
            ('paperL', '大号纸杯', '个', 100),
            ('paperM', '中号纸杯', '个', 100),
            ('plasticL', '大号塑料杯', '个', 100),
            ('plasticM', '中号塑料杯', '个', 100),
            ('membrane', '封口膜', '卷/米', 200),
            ('lid', '杯盖', '个', 100),
        ]

        consumable_db = {cs.code_id: cs for cs in DeviceConsumableStock.objects.filter(device=device)}
        consumables_data = []

        for code, name, unit, def_init in default_consumables:
            cs = consumable_db.get(code)
            current_qty = cs.quantity if cs else def_init
            warn_lvl = cs.warn_level if cs else 10
            consumables_data.append({
                'code': code,
                'name': name,
                'quantity': current_qty,
                'unit': unit,
                'warn_level': warn_lvl,
                'is_low': current_qty <= warn_lvl
            })

        # 2. 原材料料位列表
        material_stocks = DeviceMaterialStock.objects.filter(device=device)
        materials_data = [
            {
                'code': ms.code,
                'name': ms.name_id,
                'current_height': float(ms.current_remaining_height),
                'init_height': ms.initHight,
                'unit': ms.unit,
                'warn_level': float(ms.warn_level),
                'is_low': float(ms.current_remaining_height) <= float(ms.warn_level)
            }
            for ms in material_stocks
        ]

        return ok({
            'device_sn': device.device_sn,
            'device_name': device.device_name,
            'store_name': device.store.name if device.store else '',
            'consumables': consumables_data,
            'materials': materials_data
        })


class StaffConsumableUpdateView(APIView):
    """
    物料员手动录入并更新耗材数量
    POST /api/staff/consumables/update
    入参：{ "device_sn": "DEV_001", "items": [{"code": "paperL", "quantity": 85}, ...] }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        device_sn = request.data.get('device_sn', '').strip()
        items = request.data.get('items', [])

        if not device_sn or not items:
            return error('设备序列号和耗材数据不能为空', code=2002)

        try:
            device = Device.objects.get(device_sn=device_sn)
        except Device.DoesNotExist:
            return error('未找到该设备', code=2001, status=404)

        try:
            redis_conn = get_redis_connection("default")
        except Exception:
            redis_conn = None

        updated = []
        for item in items:
            code = item.get('code')
            quantity = int(item.get('quantity', 0))

            # 确保 Material 存在
            material, _ = Material.objects.get_or_create(
                code=code,
                defaults={'name': code, 'material_type': Material.TYPE_CONSUMABLE, 'unit': '个'}
            )

            stock, _ = DeviceConsumableStock.objects.get_or_create(
                device=device,
                code=material,
                defaults={'quantity': quantity}
            )
            stock.quantity = quantity
            stock.save(update_fields=['quantity', 'updated_at'])

            # 同步更新 Redis
            if redis_conn:
                redis_key = f"automake:stock:{device.device_sn}:{code}"
                redis_conn.set(redis_key, quantity * 100)

            updated.append({'code': code, 'quantity': quantity})

        logger.info(f"物料员 {request.user.username} 更新设备 {device_sn} 耗材: {updated}")
        return ok(updated, message='耗材库存已成功更新并同步至云端')


class StaffDeviceActionView(APIView):
    """
    协调员操作设备指令 (重启复位、调拨、开仓)
    POST /api/staff/devices/<device_sn>/action
    入参: { "action": "reset" | "sync" | "dispense", "payload": {} }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, device_sn):
        action = request.data.get('action', 'reset').strip()
        
        try:
            device = Device.objects.get(device_sn=device_sn)
        except Device.DoesNotExist:
            return error('未找到该设备', code=2001, status=404)

        cmd = DeviceCommand.objects.create(
            device=device,
            command_type=DeviceCommand.CMD_RESET if action == 'reset' else DeviceCommand.CMD_SYNC,
            payload={'operator': request.user.username, 'action': action},
            status=DeviceCommand.PENDING
        )

        # 尝试 MQTT 广播下发
        try:
            from mqtt import issue_device_command
            issue_device_command(device_sn=device_sn, command_type=action, payload={'cmd_id': cmd.id})
            cmd.status = DeviceCommand.SENT
            cmd.save(update_fields=['status'])
        except Exception as e:
            logger.warning(f"MQTT 命令下发提示: {e}")

        return ok({'cmd_id': cmd.id, 'action': action}, message=f'已向设备下发 {action} 指令')
