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
        new_status = payload.get('status', '').lower()

        try:
            order = OrderMain.objects.get(order_no=order_no)
        except OrderMain.DoesNotExist:
            logger.error(f'设备状态回传：订单不存在，order_no={order_no}')
            return

        import json
        logger.info(json.dumps({
            "event": "device_callback",
            "order_no": order_no,
            "OrderToken": order.order_token,
            "status": new_status,
            "payload": payload
        }, ensure_ascii=False))

        if new_status == 'making':
            update_order_status(
                order=order,
                new_status=OrderMain.STATUS_MAKING,
                operator=f'device:{device_sn}',
                remark=payload.get('message', '磨豆机已启动'),
            )
            ProductionTask.objects.filter(order=order).update(status=ProductionTask.TASK_MAKING)
            logger.info(f'已同步更新生产任务状态为: making，order_no={order_no}')
            # 异步推送订单状态变更通知：制作中（不阻塞主流程）
            try:
                from notifications.services import send_order_status_notify
                # 预估等候时间
                from notifications.views import _estimate_wait_minutes
                wait = _estimate_wait_minutes(order)
                extra = f'预计还需 {wait} 分钟' if wait else ''
                send_order_status_notify(order, OrderMain.STATUS_MAKING, extra_remark=extra)
            except Exception as notify_exc:
                # 通知失败不影响主流程
                logger.warning(f'订单状态通知异常（making）: {notify_exc}')
        
        elif new_status in ('done', 'success'):
            update_order_status(
                order=order,
                new_status=OrderMain.STATUS_DONE,
                operator=f'device:{device_sn}',
                remark=payload.get('message', '出货成功'),
            )
            ProductionTask.objects.filter(order=order).update(
                status=ProductionTask.TASK_DONE,
                done_at=timezone.now()
            )
            logger.info(f'已同步更新生产任务状态为: done，order_no={order_no}')
            # 异步：生成取餐码 + 推送取餐码通知给用户（包括手机鸣馓）
            try:
                from notifications.services import create_pickup_code, send_order_status_notify
                create_pickup_code(order)                        # 生成取餐码并推送取餐码通知
                send_order_status_notify(order, OrderMain.STATUS_DONE, extra_remark='请凭取餐码取餐')  # 订单完成通知
            except Exception as notify_exc:
                logger.warning(f'生成取餐码或通知失败（done）: {notify_exc}')
            
        elif new_status in ('failed', 'dispense_failed', 'exception'):
            # 调用 4.1 明确失败回滚
            from orders.services import process_dispense_failure
            process_dispense_failure(
                order=order,
                operator=f'device:{device_sn}',
                remark=payload.get('message', '物理出库失败')
            )
            ProductionTask.objects.filter(order=order).update(
                status=ProductionTask.TASK_FAILED,
                failure_reason=payload.get('message', '物理出库失败')
            )
            logger.info(f'已执行出库失败回滚，order_no={order_no}')
            # 异步：推送订单失败通知（用户）+ 设备告警（管理员）
            try:
                from notifications.services import send_order_status_notify, send_device_alert
                send_order_status_notify(
                    order, OrderMain.STATUS_EXCEPTION,
                    extra_remark='出餐失败，将尽快为您退款'
                )
                send_device_alert(
                    device=order.device,
                    reason=f'订单 {order_no} 出货失败: {payload.get("message", "")}'.strip(':').strip(),
                )
            except Exception as notify_exc:
                logger.warning(f'订单失败通知异常: {notify_exc}')




def receive_material_report(device_sn: str, payload: dict):
    """
    处理上位机通过 MQTT/HTTP 上报的物料状态，并更新 DB 账面库存和 Redis 可用库存。
    """
    from .models import DeviceMaterialStock
    from decimal import Decimal
    from django_redis import get_redis_connection

    logger.info(f'开始处理物料上报: device_sn={device_sn}, payload={payload}')
    try:
        device = Device.objects.get(device_sn=device_sn)
    except Device.DoesNotExist:
        logger.error(f'物料上报失败：设备 SN={device_sn} 不存在')
        return

    materials = payload.get('materials', [])
    redis_conn = get_redis_connection("default")

    for m in materials:
        code = m.get('code') or m.get('material_code')
        name = m.get('name') or m.get('material_name') or ''
        qty = m.get('quantity')
        if not code or qty is None:
            continue
        
        try:
            qty_decimal = Decimal(str(qty))
        except Exception:
            logger.error(f'无效的物料数量: {qty}')
            continue

        # 检查 Redis 中已有的可用库存当前值，避免因频繁上报且数据无变化时导致的高频 MySQL 写入
        key = f"automake:stock:{device.device_sn}:{code}"
        redis_qty_val = redis_conn.get(key)
        target_redis_val = int(qty_decimal * 100)

        if redis_qty_val is not None and int(redis_qty_val) == target_redis_val:
            # 数据完全一致，直接跳过写操作
            logger.debug(f'物料 {code} 数量未发生变化 ({qty_decimal})，跳过 DB 与 Redis 写入')
            continue

        # 1. 更新数据库 (DB_Book_Stock)
        DeviceMaterialStock.objects.update_or_create(
            device=device,
            material_code=code,
            defaults={
                'material_name': name,
                'quantity': qty_decimal,
            }
        )

        # 2. 直接覆盖 Redis_Available_Stock
        redis_conn.set(key, target_redis_val)

    logger.info(f'物料状态上报成功并持久化: device_sn={device_sn}')


class DeviceRegisterRequestSerializer(serializers.Serializer):
    device_sn = serializers.CharField(required=True, max_length=128, help_text="设备唯一序列号SN，作为身份凭证")
    key_code = serializers.CharField(required=True, max_length=32, help_text="门店注册码")
    store_id = serializers.IntegerField(required=True, help_text="所属门店ID")
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
    请求体：{ "device_sn": "SN001", "key_code": "...", "store_id": 1, "device_name": "...", "device_version": "1.0.0", "device_address": "..." }
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
        
        # 1. 提取并校验必要参数：设备序列号 (device_sn)、门店注册码 (key_code) 与门店 ID (store_id)
        device_sn = request.data.get('device_sn', '').strip()
        key_code = request.data.get('key_code', '').strip()
        store_id = request.data.get('store_id')
        if not device_sn or not key_code or store_id is None:
            return error('device_sn、key_code 和 store_id 不能为空', code=6001)

        # 记录上位机设备注册的上报数据日志，用于测试闭环
        logger.info(f"[DEVICE_REPORT] Register payload from {device_sn}: {request.data}")

        device_name = request.data.get('device_name', '')
        device_version = request.data.get('device_version') or request.data.get('firmware_version') or ''
        device_address = request.data.get('device_address', '')
        device_model = request.data.get('device_model', '')

        # 2. 联动校验门店：必须在对应的 Store 表中存在注册码为 key_code 且 ID 为 store_id 的门店记录
        from stores.models import Store
        store = Store.objects.filter(code=key_code, id=store_id).first()
        if not store:
            logger.warning(f"设备注册/创建失败：未找到注册码为 {key_code} 且 ID 为 {store_id} 的门店记录")
            return error('门店不存在或注册码无效，无法绑定/创建设备', code=6002)

        # 3. 查找或创建设备记录（仅根据唯一键 device_sn 查找，避免 IntegrityError 数据库冲突崩溃）
        extra_config = {'device_address': device_address} if device_address else {}
        device, created = Device.objects.get_or_create(
            device_sn=device_sn,
            defaults={
                'key_code': key_code,
                'store': store,
                'device_name': device_name,
                'device_model': device_model,
                'firmware_version': device_version,
                'status': Device.STATUS_ONLINE,
                'last_heartbeat_at': timezone.now(),
                'mqtt_topic_prefix': f'automake/device/{device_sn}',
                'extra_config': extra_config,
            }
        )

        # 5. 更新 Device 完整数据项（针对已存在的记录，确保信息实时最新）
        if not created:
            if device.key_code != key_code:
                logger.warning(f"设备重新上线失败：设备 {device_sn} 的注册码为 {device.key_code}，但请求的注册码为 {key_code}")
                return error('设备注册码与数据库中不一致，可能存在越权注册', code=6003)

            device.status = Device.STATUS_ONLINE
            device.last_heartbeat_at = timezone.now()
            device.firmware_version = device_version
            device.device_name = device_name
            device.store = store
            device.mqtt_topic_prefix = f'automake/device/{device_sn}'
            if device_model:
                device.device_model = device_model
            
            if not isinstance(device.extra_config, dict):
                device.extra_config = {}
            if device_address:
                device.extra_config['device_address'] = device_address
            device.save()
            action = '重新上线'
        else:
            action = '注册创建'

        # 自动触发该门店的全局菜单同步
        try:
            from menus.models import MenuItem
            MenuItem.sync_store_menu(store)
        except Exception as e:
            logger.error(f'自动同步门店菜单失败: {e}')

        # 4. 记录状态变更日志
        DeviceStatusLog.objects.create(
            device=device,
            status=Device.STATUS_ONLINE,
            remark='设备注册/上线 (HTTPS POST)',
            raw_payload=request.data,
        )

        logger.info(f'设备{action}成功: device_sn={device_sn}')

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
    """
    permission_classes = [AllowAny]

    @extend_schema(
        request=DeviceInventoryOperateSerializer,
        summary="上位机锁定库存",
        description="上位机在制作前调用此接口锁定所需的物料库存。此版本已不再物理锁仓，直接返回成功。"
    )
    def post(self, request):
        serializer = DeviceInventoryOperateSerializer(data=request.data)
        if not serializer.is_valid():
            return error(str(serializer.errors), code=6002)

        device_sn = serializer.validated_data['device_sn']
        try:
            Device.objects.get(device_sn=device_sn)
        except Device.DoesNotExist:
            return error('设备不存在', code=6003)

        return ok(None, message='锁定库存成功')


class DeviceInventoryDeductView(APIView):
    """
    上位机扣减实际库存接口
    """
    permission_classes = [AllowAny]

    @extend_schema(
        request=DeviceInventoryOperateSerializer,
        summary="上位机扣减实际库存",
        description="上位机制作完成后，调用此接口真实扣减物料库存。此版本已不再物理扣仓，直接返回成功。"
    )
    def post(self, request):
        serializer = DeviceInventoryOperateSerializer(data=request.data)
        if not serializer.is_valid():
            return error(str(serializer.errors), code=6002)

        device_sn = serializer.validated_data['device_sn']
        try:
            Device.objects.get(device_sn=device_sn)
        except Device.DoesNotExist:
            return error('设备不存在', code=6003)

        return ok(None, message='扣减实际库存成功')


class DeviceInventoryReleaseView(APIView):
    """
    上位机释放锁定库存接口
    """
    permission_classes = [AllowAny]

    @extend_schema(
        request=DeviceInventoryOperateSerializer,
        summary="上位机释放锁定库存",
        description="上位机在订单制作取消、失败等异常场景下，释放之前锁定的库存。此版本直接返回成功。"
    )
    def post(self, request):
        serializer = DeviceInventoryOperateSerializer(data=request.data)
        if not serializer.is_valid():
            return error(str(serializer.errors), code=6002)

        device_sn = serializer.validated_data['device_sn']
        try:
            Device.objects.get(device_sn=device_sn)
        except Device.DoesNotExist:
            return error('设备不存在', code=6003)

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


class DeviceReconciliationView(APIView):
    """
    上位机断线重连对账接口
    """
    permission_classes = [AllowAny]

    def post(self, request):
        device_sn = request.data.get('device_sn')
        executed_tokens = request.data.get('executed_tokens', [])
        
        if not device_sn:
            return error('device_sn 不能为空', code=6010)

        try:
            from orders.services import reconcile_device_orders
            res = reconcile_device_orders(device_sn, executed_tokens)
            return ok(res, message='对账完成')
        except ValueError as e:
            return error(str(e), code=6011)
        except Exception as e:
            logger.exception(f'对账处理异常: {e}')
            return error('对账处理失败，请稍后重试', code=6012, status=500)




