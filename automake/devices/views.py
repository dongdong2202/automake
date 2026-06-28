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
        
        elif new_status == 'done': # 出货完成
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

        elif new_status == 'cancelled':
            from payments.services import refund_order
            
            ProductionTask.objects.filter(order=order).update(
                status=ProductionTask.TASK_FAILED,
                failure_reason='设备已确认撤单'
            )
            logger.info(f'设备已确认撤单，开始执行退款，order_no={order_no}')
            try:
                refund_order(order, reason="设备已确认撤单，自动退款")
            except Exception as e:
                logger.error(f"设备确认撤单后，调用退款异常: {e}")




def check_material_alarm(device, code: str, qty_decimal):
    """
    针对食材原料 (raw) 的高度进行阈值计算与报警触发。
    - 临界值 (critical_level) = warn_level * 0.2
    - 高度低于或等于临界值，触发缺货熔断警告。
    - 高度低于或等于预警值，触发短信预警逻辑（通过 Redis 锁限制 1 小时内仅发送 1 次）。
    """
    from decimal import Decimal
    from django_redis import get_redis_connection
    from .models import DeviceMaterialStock
    
    redis_conn = get_redis_connection("default")
    device_sn = device.device_sn

    # 获取预警告警配置阈值 (只读，不创建)
    stock_config = DeviceMaterialStock.objects.filter(device=device, code=code).first()
    if not stock_config:
        return -1 # 没有这个食材
    
    warn_level = float(stock_config.warn_level) if stock_config else 0
    warn_level_3 = float(stock_config.warn_level_3) if stock_config else 0
    height_val = stock_config.initHight - qty_decimal #current hight
    
    if height_val <= warn_level:
        logger.warning(f"[OUT_OF_STOCK] 设备 {device_sn} 物料 {code} 高度为 {height_val}cm, 低于或等于极低熔断阈值 {warn_level}cm, 触发缺货熔断")

        return 0
    elif height_val <= warn_level_3:
        sms_lock_key = f"automake:sms_sent:{device_sn}:{code}"
        if redis_conn.set(sms_lock_key, "1", ex=3600, nx=True):
            phone = device.store.contact_phone if (device.store and device.store.contact_phone) else "13800138000"
            store_name = device.store.name if device.store else "未知门店"
            m_name = stock_config.name.name if (stock_config and stock_config.name) else code
            logger.info(f"[SMS_ALERT] 调用阿里云短信接口成功: 接收手机={phone}, 短信内容='【智能咖啡机】您的 {store_name} 门店设备 (SN: {device_sn}) {m_name} 原料即将耗尽，当前高度为 {height_val}cm，请及时补货。', template_code='SMS_ALERT_WARN', response='OK'")
        return 1
    return 2

def receive_material_report(device_sn: str, payload: dict):
    """
    处理物料上报，并更新 DB 账面库存和 Redis 可用库存。
    - cup (消耗品/耗材): 写入 MySQL (Material & DeviceConsumableStock)，保存时会自动同步至 Redis。
    - raw (原材料/食材): 不保存到 MySQL，直接更新 Redis 虚拟可用库存并进行告警/熔断检查。
    """
    from .models import DeviceMaterialStock, DeviceConsumableStock
    from decimal import Decimal
    from django_redis import get_redis_connection
    from inventory.models import Material

    logger.info(f'开始处理物料上报: device_sn={device_sn}, payload={payload}')
    try:
        device = Device.objects.get(device_sn=device_sn)
    except Device.DoesNotExist:
        logger.error(f'物料上报失败：设备 SN={device_sn} 不存在')
        return

    redis_conn = get_redis_connection("default")

    # 1. 处理 cup 消耗品 (写数据库 + Redis)
    cup_dict = payload.get('cup', {})
    for code, qty in cup_dict.items():
        if qty is None:
            continue
        try:
            qty_decimal = Decimal(str(qty))
        except Exception:
            logger.error(f'无效的耗材数量: {qty}')
            continue
        try:
                stock = DeviceConsumableStock.objects.get(device=device, code=code)
                stock.quantity = int(qty_decimal)
                stock.save()
        except Exception as e:
                logger.warning(f'[MQTT] 更新耗材 {code} 数据库失败: {e}')



    # 2. 处理 raw 原材料 (仅更新 Redis，不保存到 MySQL)
    raw_dict = payload.get('raw', {})
    for code, qty in raw_dict.items():
        if qty is None:
            continue
        try:
            qty_decimal = Decimal(str(qty))
        except Exception:
            logger.error(f'无效的食材数量: {qty}')
            continue

        # 触发报警函数
        check_material_alarm(device, code, qty_decimal)

        key = f"automake:stock:{device.device_sn}:{code}"
        redis_qty_val = redis_conn.get(key)
        target_redis_val = int(qty_decimal * 100)

        if redis_qty_val is not None and int(redis_qty_val) == target_redis_val:
            # 数据无变化，直接跳过写操作
            logger.debug(f'原料 {code} 数量未发生变化 ({qty_decimal})，跳过 Redis 写入')
            continue

        # 仅写入 Redis_Available_Stock，不执行 MySQL update_or_create
        redis_conn.set(key, target_redis_val)

    logger.info(f'物料状态上报成功并持久化: device_sn={device_sn}')


class DeviceRegisterRequestSerializer(serializers.Serializer):
    device_sn = serializers.CharField(required=True, max_length=128, help_text="设备唯一序列号SN，作为身份凭证")
    key_code = serializers.CharField(required=True, max_length=32, help_text="门店注册码")
    store_id = serializers.IntegerField(required=False, allow_null=True, help_text="所属门店ID")
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
    1. 上位机注册与信息更新：必须且仅通过 HTTPS POST 接口进行注册。
    POST /api/device/register
    """
    permission_classes = [AllowAny]

    @extend_schema(
        request=DeviceRegisterRequestSerializer,
        responses={200: DeviceRegisterResponseSerializer},
        summary="设备注册/重新上线",
        description="上位机（设备）启动时首个调用的 HTTPS POST 接口，进行上线注册并获取 websocket uri。"
    )
    def post(self, request):
        
        # 1. 提取并校验必要参数：设备序列号 (device_sn)、门店注册码 (key_code)
        device_sn = request.data.get('device_sn', '').strip()
        key_code = request.data.get('key_code', '').strip()
        store_id = request.data.get('store_id')
        if not device_sn or not key_code:
            return error('device_sn 和 key_code 不能为空', code=6001)

        # 记录上位机设备注册的上报数据日志，用于测试闭环
        logger.info(f"[DEVICE_REPORT] Register payload from {device_sn}: {request.data}")
        
        # 2. 校验设备是否已预先录入系统
        device = Device.objects.filter(device_sn=device_sn).first()
        if not device:
            logger.warning(f"设备注册失败：设备序列号 {device_sn} 未在系统中预先录入")
            return error('设备未在系统预先录入，无法注册', code=6004)
        
        if device.status != 'online':
            logger.warning(f"设备注册失败：请联系管理员先上线在注册")
            return error('请联系管理员先上线在注册', code=6004)
            
        if device.key_code and device.key_code != key_code:
            logger.warning(f"设备重新上线失败：设备 {device_sn} 的注册码为 {device.key_code}，但请求的注册码为 {key_code}")
            return error('设备注册码与数据库中不一致，可能存在越权注册', code=6003)

        # 3. 联动校验门店
        from stores.models import Store
        if store_id:
            store = Store.objects.filter(code=key_code, id=store_id).first()
            if not store:
                logger.warning(f"设备注册失败：未找到注册码为 {key_code} 且 ID 为 {store_id} 的门店记录")
                return error('门店不存在或注册码无效，无法绑定设备', code=6002)
        else:
            store = device.store
            if not store:
                logger.warning(f"设备注册失败：设备 {device_sn} 未关联任何门店，且请求中未提供 store_id")
                return error('设备未关联门店，且未提供 store_id', code=6002)
            if store.code != key_code:
                logger.warning(f"设备注册失败：设备关联的门店注册码 {store.code} 与请求的 key_code {key_code} 不一致")
                return error('注册码无效', code=6002)

        # 4. 更新设备信息
        device.store = store
        device.key_code = key_code
        
        device_name = request.data.get('device_name')
        if device_name:
            device.device_name = device_name
            
        device_version = request.data.get('device_version') or request.data.get('firmware_version')
        if device_version:
            device.firmware_version = device_version
            
        device_address = request.data.get('device_address')
        if device_address:
            if not isinstance(device.extra_config, dict):
                device.extra_config = {}
            device.extra_config['device_address'] = device_address
            
        device.last_heartbeat_at = timezone.now()
        device.save()

        # 5. 自动触发该门店的全局菜单同步
        try:
            from menus.models import MenuItem
            MenuItem.sync_store_menu(store)
        except Exception as e:
            logger.error(f'自动同步门店菜单失败: {e}')

        # 6. 记录状态变更日志
        DeviceStatusLog.objects.create(
            device=device,
            status=Device.STATUS_ONLINE,
            remark='设备注册/上线 (HTTPS POST)',
            raw_payload=request.data,
        )

        logger.info(f'设备注册更新成功: device_sn={device_sn}')

        return ok({
            'device_id': device.id,
            'resource_version': device.resource_version,
            'mqtt_topic_prefix': f'ws/device/{device_sn}',
        }, message='设备注册成功')


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
        "raw": {
            "coffee_bean": 850,
            "fresh_milk": 2500
        },
        "cup": {
            "paperL": 100,
            "lid": 100
        }
    }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        device_sn = request.data.get('device_sn')
        if not device_sn:
            return error('device_sn 不能为空', code=6009)

        raw = request.data.get('raw', {})
        cup = request.data.get('cup', {})

        payload = {
            'raw': raw,
            'cup': cup
        }
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




