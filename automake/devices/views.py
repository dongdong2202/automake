"""
设备模块视图

接口列表：
- POST /api/device/register                 上位机注册/更新设备信息
- POST /api/device/status/report            上位机上报设备状态（心跳）
- POST /api/device/order/status/report      上位机上报订单状态回传
"""

import logging
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework import serializers
from drf_spectacular.utils import extend_schema

from utils.response import ok, error
from orders.models import OrderMain
from orders.services import update_order_status
from .models import Device, DeviceStatusLog

logger = logging.getLogger(__name__)


def receive_device_status(device_sn: str, payload: dict):
    """
    处理上位机通过 MQTT 上报的设备/订单状态（内部函数）

    此函数由 MQTT 消息回调调用（非 HTTP 请求）。

    :param device_sn: 设备序列号
    :param payload: 上报内容
    """
    from orders.models import ProductionTask
    from django.utils import timezone

    msg_type = payload.get('type')

    if msg_type == 'heartbeat':
        status_val = payload.get('status', Device.STATUS_ONLINE)
        try:
            device = Device.objects.get(device_sn=device_sn)
        except Device.DoesNotExist:
            logger.error(f'设备心跳上报：设备不存在，device_sn={device_sn}')
            return

        # 状态发生变化时才写日志
        if device.status != status_val:
            DeviceStatusLog.objects.create(
                device=device,
                status=status_val,
                remark='MQTT心跳状态上报',
                raw_payload=payload,
            )

        device.status = status_val
        device.last_heartbeat_at = timezone.now()
        device.save(update_fields=['status', 'last_heartbeat_at', 'updated_at'])
        logger.info(f'设备心跳已通过 MQTT 更新: device_sn={device_sn}, status={status_val}')
        return

    if msg_type == 'order_status':
        order_no = payload.get('order_no', '')
        new_status = payload.get('status', '')

        # 状态映射：上位机状态 → 订单状态
        status_map = {
            'making': OrderMain.STATUS_MAKING,
            'done': OrderMain.STATUS_DONE,
            'failed': OrderMain.STATUS_EXCEPTION,
        }
        order_status = status_map.get(new_status)
        if not order_status:
            logger.warning(f'未知的上位机订单状态: {new_status}')
            return

        try:
            order = OrderMain.objects.get(order_no=order_no)
        except OrderMain.DoesNotExist:
            logger.error(f'设备状态回传：订单不存在，order_no={order_no}')
            return

        update_order_status(
            order=order,
            new_status=order_status,
            operator=f'device:{device_sn}',
            remark=payload.get('message', ''),
        )

        # 同步更新生产任务 (ProductionTask) 状态
        task_status_map = {
            'making': ProductionTask.TASK_MAKING,
            'done': ProductionTask.TASK_DONE,
            'failed': ProductionTask.TASK_FAILED,
        }
        task_status = task_status_map.get(new_status)
        if task_status:
            update_fields = {'status': task_status}
            if task_status == ProductionTask.TASK_DONE:
                update_fields['done_at'] = timezone.now()
            elif task_status == ProductionTask.TASK_FAILED:
                update_fields['failure_reason'] = payload.get('message', '未知错误')

            ProductionTask.objects.filter(order=order).update(**update_fields)
            logger.info(f'已同步更新生产任务状态为: {task_status}，order_no={order_no}')


def receive_material_report(device_sn: str, payload: dict):
    """
    处理上位机通过 MQTT/HTTP 上报的物料状态，更新 MaterialStock 并在库存不足时生成告警。

    :param device_sn: 设备序列号
    :param payload: 上报内容
    """
    from menus.models import MaterialStock
    from devices.models import DeviceAlarm
    from django.db import transaction
    from django.utils import timezone

    try:
        device = Device.objects.get(device_sn=device_sn)
    except Device.DoesNotExist:
        logger.error(f'物料上报：设备不存在，device_sn={device_sn}')
        return

    materials = payload.get('materials', [])
    if not materials:
        logger.warning(f'物料上报：数据载荷中未包含 materials，device_sn={device_sn}')
        return

    alarms_to_create = []

    try:
        with transaction.atomic():
            for m in materials:
                code = m.get('code')
                name = m.get('name', code)
                qty = m.get('quantity', 0.0)
                unit = m.get('unit', '')

                # 查找或创建物料库存
                stock, created = MaterialStock.objects.select_for_update().get_or_create(
                    device=device,
                    material_code=code,
                    defaults={
                        'material_name': name,
                        'current_quantity': qty,
                        'unit': unit,
                        'locked_quantity': 0,
                        'alert_threshold': 100.0 if code == 'coffee_bean' else 500.0,
                    }
                )

                if not created:
                    stock.current_quantity = qty
                    if unit:
                        stock.unit = unit
                    if name:
                        stock.material_name = name

                stock.last_reported_at = timezone.now()
                stock.save()

                # 检查库存是否过低，触发/更新告警
                if stock.is_low:
                    exists = DeviceAlarm.objects.filter(
                        device=device,
                        alarm_type=DeviceAlarm.ALARM_LOW_MATERIAL,
                        is_resolved=False,
                        detail__contains=f'({code})'
                    ).exists()
                    if not exists:
                        alarms_to_create.append(DeviceAlarm(
                            device=device,
                            alarm_type=DeviceAlarm.ALARM_LOW_MATERIAL,
                            detail=f"物料 {stock.material_name} ({code}) 库存不足，当前: {stock.current_quantity}{stock.unit}, 阈值: {stock.alert_threshold}{stock.unit}",
                            is_resolved=False
                        ))
                else:
                    # 如果库存已恢复，自动恢复该物料的未解决告警
                    DeviceAlarm.objects.filter(
                        device=device,
                        alarm_type=DeviceAlarm.ALARM_LOW_MATERIAL,
                        is_resolved=False,
                        detail__contains=f'({code})'
                    ).update(is_resolved=True, resolved_at=timezone.now())

            if alarms_to_create:
                DeviceAlarm.objects.bulk_create(alarms_to_create)

        logger.info(f'物料状态上报已成功处理: device_sn={device_sn}, materials={[(m.get("code"), m.get("quantity")) for m in materials]}')
    except Exception as e:
        logger.exception(f'处理物料上报失败，device_sn={device_sn}: {e}')


class DeviceRegisterRequestSerializer(serializers.Serializer):
    device_sn = serializers.CharField(required=True, max_length=128, help_text="设备唯一序列号SN，作为身份凭证")
    device_name = serializers.CharField(required=False, max_length=128, help_text="设备名称")
    device_version = serializers.CharField(required=False, max_length=64, help_text="设备版本")
    device_address = serializers.CharField(required=False, max_length=256, help_text="设备安装地址")


class DeviceRegisterResponseSerializer(serializers.Serializer):
    device_id = serializers.IntegerField(help_text="设备在系统数据库中的ID")
    resource_version = serializers.IntegerField(help_text="云端分配给设备的资源包版本号")
    mqtt_topic_prefix = serializers.CharField(help_text="该设备需监听/发布的 MQTT 主题前缀")
    config = serializers.DictField(help_text="云端下发给该设备的扩展配置参数")


class DeviceRegisterView(APIView):
    """
    设备注册/更新接口（上位机启动时调用）

    【通信协议说明】
    根据系统架构要求：
    1. 上位机注册与信息更新：必须且仅通过 HTTPS POST 接口（即此视图）进行注册。
    2. 其他通信（心跳、物料、状态上报及云端下发命令）：均必须通过 MQTT 协议进行通信，禁止使用 HTTP/HTTPS。

    POST /api/device/register
    请求体：{ "device_sn": "SN001", "device_name": "...", "device_version": "1.0.0", "device_address": "..." }
    响应：{ "device_id": ..., "resource_version": ..., "mqtt_topic_prefix": "..." }
    """
    # 设备注册接口：使用设备 SN 作为凭证，不需要用户 JWT
    # 生产中可加设备 Token 认证
    permission_classes = [AllowAny]

    @extend_schema(
        request=DeviceRegisterRequestSerializer,
        responses={200: DeviceRegisterResponseSerializer},
        summary="设备注册/重新上线",
        description="上位机（设备）启动时首个调用的 HTTPS POST 接口，进行上线注册并获取 MQTT 联络主题前缀与配置。"
    )
    def post(self, request):
        device_sn = request.data.get('device_sn', '').strip()
        if not device_sn:
            return error('device_sn 不能为空', code=6001)

        # 记录上位机设备注册的上报数据日志，用于测试闭环
        logger.info(f"[DEVICE_REPORT] Register payload from {device_sn}: {request.data}")

        device_name = request.data.get('device_name', '')
        # 兼容处理：支持传入 device_version 或 历史字段 firmware_version
        device_version = request.data.get('device_version') or request.data.get('firmware_version') or ''
        device_address = request.data.get('device_address', '')

        # 将额外数据如 device_address 存入 extra_config 中
        extra_config = {'device_address': device_address} if device_address else {}

        # 查找或创建设备记录
        device, created = Device.objects.get_or_create(
            device_sn=device_sn,
            defaults={
                'device_name': device_name,
                'firmware_version': device_version,
                'status': Device.STATUS_ONLINE,
                'last_heartbeat_at': timezone.now(),
                'mqtt_topic_prefix': f'automake/device/{device_sn}',
                'extra_config': extra_config,
            }
        )

        if not created:
            # 更新已有设备信息
            device.status = Device.STATUS_ONLINE
            device.last_heartbeat_at = timezone.now()
            if device_version:
                device.firmware_version = device_version
            if device_name:
                device.device_name = device_name
            if device_address:
                if not isinstance(device.extra_config, dict):
                    device.extra_config = {}
                device.extra_config['device_address'] = device_address
            device.save(update_fields=[
                'status', 'last_heartbeat_at', 'firmware_version',
                'device_name', 'extra_config', 'updated_at'
            ])

        # 记录状态日志
        DeviceStatusLog.objects.create(
            device=device,
            status=Device.STATUS_ONLINE,
            remark='设备注册/上线 (HTTPS POST)',
            raw_payload=request.data,
        )

        action = '新注册' if created else '重新上线'
        logger.info(f'设备 {action}: device_sn={device_sn}')

        return ok({
            'device_id': device.id,
            'resource_version': device.resource_version,
            'mqtt_topic_prefix': device.mqtt_topic_prefix or f'automake/device/{device_sn}',
            'config': device.extra_config,
        }, message=f'设备{action}成功')


class MaterialItemSerializer(serializers.Serializer):
    material_code = serializers.CharField(required=True, max_length=64, help_text="物料编码")
    quantity = serializers.DecimalField(required=True, max_digits=10, decimal_places=2, help_text="物料数量")


class DeviceInventoryOperateSerializer(serializers.Serializer):
    device_sn = serializers.CharField(required=True, max_length=128, help_text="设备唯一序列号SN")
    order_no = serializers.CharField(required=False, max_length=64, allow_blank=True, help_text="关联订单号")
    materials = MaterialItemSerializer(many=True, required=True, help_text="操作物料列表")


class DeviceInventoryLockView(APIView):
    """
    上位机锁定库存接口

    POST /api/device/inventory/lock
    请求体：{ "device_sn": "SN001", "order_no": "...", "materials": [{ "material_code": "coffee_bean", "quantity": 15.0 }] }
    """
    permission_classes = [AllowAny]

    @extend_schema(
        request=DeviceInventoryOperateSerializer,
        summary="上位机锁定库存",
        description="上位机在制作前调用此接口锁定所需的物料库存，防止其他订单占用（超卖）。"
    )
    def post(self, request):
        serializer = DeviceInventoryOperateSerializer(data=request.data)
        if not serializer.is_valid():
            return error(str(serializer.errors), code=6002)

        device_sn = serializer.validated_data['device_sn']
        order_no = serializer.validated_data.get('order_no')
        materials = serializer.validated_data['materials']

        # 若提供了 order_no 且订单已绑定该设备，说明云端在下单时已预锁过，直接返回成功以防双重锁定
        if order_no:
            try:
                order = OrderMain.objects.get(order_no=order_no)
                if order.device and order.device.device_sn == device_sn:
                    logger.info(f"订单 {order_no} 已经在下单时完成了库存预锁，上位机制作无需重复锁定")
                    return ok(None, message='锁定库存成功（已由云端预锁）')
            except OrderMain.DoesNotExist:
                pass

        try:
            device = Device.objects.get(device_sn=device_sn)
        except Device.DoesNotExist:
            return error('设备不存在', code=6003)

        from menus.models import MaterialStock
        from django.db import transaction

        try:
            with transaction.atomic():
                codes = [m['material_code'] for m in materials]
                stocks = MaterialStock.objects.select_for_update().filter(device=device, material_code__in=codes)
                stock_dict = {s.material_code: s for s in stocks}

                # 校验可用库存是否足够
                for m in materials:
                    code = m['material_code']
                    qty = m['quantity']
                    if code not in stock_dict:
                        return error(f'物料 {code} 未配置在设备库存中', code=6004)
                    
                    stock = stock_dict[code]
                    available = stock.current_quantity - stock.locked_quantity
                    if available < qty:
                        return error(f'物料 {stock.material_name} ({code}) 库存不足，可用: {available}, 锁定请求: {qty}', code=6005)

                # 锁定库存
                for m in materials:
                    code = m['material_code']
                    qty = m['quantity']
                    stock = stock_dict[code]
                    stock.locked_quantity += qty
                    stock.save(update_fields=['locked_quantity', 'updated_at'])

        except Exception as e:
            logger.exception(f'锁定库存失败: {e}')
            return error(f'锁定库存失败: {str(e)}', code=6006)

        return ok(None, message='锁定库存成功')


class DeviceInventoryDeductView(APIView):
    """
    上位机扣减库存接口

    POST /api/device/inventory/deduct
    请求体：{ "device_sn": "SN001", "order_no": "...", "materials": [{ "material_code": "coffee_bean", "quantity": 15.0 }] }
    """
    permission_classes = [AllowAny]

    @extend_schema(
        request=DeviceInventoryOperateSerializer,
        summary="上位机扣减实际库存",
        description="上位机制作完成后，调用此接口真实扣减物料库存，并释放在锁定库存中预占的部分。"
    )
    def post(self, request):
        serializer = DeviceInventoryOperateSerializer(data=request.data)
        if not serializer.is_valid():
            return error(str(serializer.errors), code=6002)

        device_sn = serializer.validated_data['device_sn']
        materials = serializer.validated_data['materials']

        try:
            device = Device.objects.get(device_sn=device_sn)
        except Device.DoesNotExist:
            return error('设备不存在', code=6003)

        from menus.models import MaterialStock
        from devices.models import DeviceAlarm
        from django.db import transaction

        alarms_to_create = []

        try:
            with transaction.atomic():
                codes = [m['material_code'] for m in materials]
                stocks = MaterialStock.objects.select_for_update().filter(device=device, material_code__in=codes)
                stock_dict = {s.material_code: s for s in stocks}

                for m in materials:
                    code = m['material_code']
                    qty = m['quantity']
                    if code not in stock_dict:
                        return error(f'物料 {code} 未配置在设备库存中', code=6004)
                    
                    stock = stock_dict[code]
                    stock.current_quantity -= qty
                    if stock.locked_quantity >= qty:
                        stock.locked_quantity -= qty
                    else:
                        stock.locked_quantity = 0
                    
                    stock.save(update_fields=['current_quantity', 'locked_quantity', 'updated_at'])

                    # 检查库存是否过低
                    if stock.is_low:
                        # 避免重复创建未解决的相同类型相同物料告警
                        exists = DeviceAlarm.objects.filter(
                            device=device,
                            alarm_type=DeviceAlarm.ALARM_LOW_MATERIAL,
                            is_resolved=False,
                            detail__contains=f'({code})'
                        ).exists()
                        if not exists:
                            alarms_to_create.append(DeviceAlarm(
                                device=device,
                                alarm_type=DeviceAlarm.ALARM_LOW_MATERIAL,
                                detail=f"物料 {stock.material_name} ({code}) 库存不足，当前: {stock.current_quantity}{stock.unit}, 阈值: {stock.alert_threshold}{stock.unit}",
                                is_resolved=False
                            ))

                if alarms_to_create:
                    DeviceAlarm.objects.bulk_create(alarms_to_create)

        except Exception as e:
            logger.exception(f'扣减实际库存失败: {e}')
            return error(f'扣减实际库存失败: {str(e)}', code=6007)

        return ok(None, message='扣减实际库存成功')


class DeviceInventoryReleaseView(APIView):
    """
    上位机释放锁定库存接口

    POST /api/device/inventory/release
    请求体：{ "device_sn": "SN001", "order_no": "...", "materials": [{ "material_code": "coffee_bean", "quantity": 15.0 }] }
    """
    permission_classes = [AllowAny]

    @extend_schema(
        request=DeviceInventoryOperateSerializer,
        summary="上位机释放锁定库存",
        description="上位机在订单制作取消、失败等异常场景下，释放之前锁定的库存。"
    )
    def post(self, request):
        serializer = DeviceInventoryOperateSerializer(data=request.data)
        if not serializer.is_valid():
            return error(str(serializer.errors), code=6002)

        device_sn = serializer.validated_data['device_sn']
        materials = serializer.validated_data['materials']

        try:
            device = Device.objects.get(device_sn=device_sn)
        except Device.DoesNotExist:
            return error('设备不存在', code=6003)

        from menus.models import MaterialStock
        from django.db import transaction

        try:
            with transaction.atomic():
                codes = [m['material_code'] for m in materials]
                stocks = MaterialStock.objects.select_for_update().filter(device=device, material_code__in=codes)
                stock_dict = {s.material_code: s for s in stocks}

                for m in materials:
                    code = m['material_code']
                    qty = m['quantity']
                    if code not in stock_dict:
                        continue
                    
                    stock = stock_dict[code]
                    if stock.locked_quantity >= qty:
                        stock.locked_quantity -= qty
                    else:
                        stock.locked_quantity = 0
                    
                    stock.save(update_fields=['locked_quantity', 'updated_at'])

        except Exception as e:
            logger.exception(f'释放锁定库存失败: {e}')
            return error(f'释放锁定库存失败: {str(e)}', code=6008)

        return ok(None, message='释放锁定库存成功')


class DeviceInventoryReportView(APIView):
    """
    上位机上报当前库存接口（HTTP POST 方式）

    POST /api/device/inventory/report
    请求体：
    {
        "device_sn": "SN001",
        "materials": [
            { "material_code": "coffee_bean", "material_name": "咖啡豆", "quantity": 850, "unit": "g" },
            { "material_code": "fresh_milk", "material_name": "鲜牛奶", "quantity": 2500, "unit": "ml" }
        ]
    }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        device_sn = request.data.get('device_sn')
        if not device_sn:
            return error('device_sn 不能为空', code=6009)

        materials = request.data.get('materials', [])
        formatted_materials = []
        for m in materials:
            formatted_materials.append({
                'code': m.get('material_code') or m.get('code'),
                'name': m.get('material_name') or m.get('name'),
                'quantity': m.get('quantity'),
                'unit': m.get('unit')
            })

        payload = {'materials': formatted_materials}
        receive_material_report(device_sn, payload)

        return ok(None, message='物料库存上报成功')


class DeviceHeartbeatView(APIView):
    """
    设备心跳上报接口（已废弃/禁用）
    """
    permission_classes = [AllowAny]

    def post(self, request):
        from rest_framework.response import Response
        from rest_framework import status
        return Response(
            {"code": 400, "message": "设备心跳上报已禁用 HTTP 接口，必须使用 MQTT 协议进行通信"},
            status=status.HTTP_400_BAD_REQUEST
        )


class DeviceOrderStatusReportView(APIView):
    """
    设备订单状态回传接口（已废弃/禁用）
    """
    permission_classes = [AllowAny]

    def post(self, request):
        from rest_framework.response import Response
        from rest_framework import status
        return Response(
            {"code": 400, "message": "订单状态回传已禁用 HTTP 接口，必须使用 MQTT 协议进行通信"},
            status=status.HTTP_400_BAD_REQUEST
        )




