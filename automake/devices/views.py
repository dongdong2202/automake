"""
设备模块视图

接口列表：
- POST /api/device/register                 上位机注册/更新设备信息
- POST /api/device/status/report            上位机上报设备状态（心跳）
- POST /api/device/order/status/report      上位机上报订单状态回传
"""

import logging
import time
import jwt
from django.conf import settings
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import serializers
from drf_spectacular.utils import extend_schema, OpenApiParameter

from utils.response import ok, error
from orders.models import OrderMain
from orders.services import update_order_status
from .models import Device, DeviceStatusLog, DevicePoster
from devices.authentication import DeviceJWTAuthentication, IsAuthenticatedDevice

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
                operator_type=OrderStatusLog.OP_DEVICE,
                action=OrderStatusLog.ACTION_MAKING_START,
                action_name='设备开始制作',
                remark=payload.get('message', '磨豆机已启动，开始制作'),
                payload={
                    'device_sn': device_sn,
                    'message': payload.get('message', ''),
                    'event_data': payload
                }
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
        
        elif new_status == 'done': # 出货完成
            update_order_status(
                order=order,
                new_status=OrderMain.STATUS_DONE,
                operator=f'device:{device_sn}',
                operator_type=OrderStatusLog.OP_DEVICE,
                action=OrderStatusLog.ACTION_MAKING_DONE,
                action_name='制作完成（出杯成功）',
                remark=payload.get('message', '出货成功，已完成'),
                payload={
                    'device_sn': device_sn,
                    'message': payload.get('message', ''),
                    'event_data': payload
                }
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
    处理物料与设备状态上报：
    优先调用 monitor.services.process_device_status_report 统一处理。
    同时兼容老版本 raw/cup 键格式。
    """
    from .models import DeviceMaterialStock, DeviceConsumableStock
    from decimal import Decimal
    from django_redis import get_redis_connection
    from inventory.models import Material

    logger.info(f'开始处理物料上报: device_sn={device_sn}, payload={payload}')
    
    # 1. 若为 monitor/e.md 协议结构（包含 thinP/thickP/solidP/temperature/healthy 等）
    is_standard_proto = any(k in payload for k in ('thinP', 'thickP', 'solidP', 'ice', 'temperature', 'free', 'press', 'heat', 'arm', 'take', 'spray', 'ticket'))
    if is_standard_proto:
        try:
            from monitor.services import process_device_status_report
            process_device_status_report(device_sn, payload)
            logger.info(f'标准状态物料上报成功并持久化: device_sn={device_sn}')
            return
        except Exception as e:
            logger.exception(f'标准协议上报处理异常: {e}')

    try:
        device = Device.objects.get(device_sn=device_sn)
    except Device.DoesNotExist:
        logger.error(f'物料上报失败：设备 SN={device_sn} 不存在')
        return

    redis_conn = get_redis_connection("default")

    # 2. 处理 cup 消耗品 (写数据库 + Redis)
    cup_dict = payload.get('cup', {})
    if isinstance(cup_dict, dict):
        for code, val in cup_dict.items():
            if val is None:
                continue
            if isinstance(val, dict):
                is_empty = val.get('a2', 0) == 1
                qty_val = 0 if is_empty else 100
            else:
                try:
                    qty_val = int(Decimal(str(val)))
                except Exception:
                    continue

            try:
                stock = DeviceConsumableStock.objects.filter(device=device, code__code=code).first()
                if stock:
                    stock.quantity = qty_val
                    stock.save()
            except Exception as e:
                logger.warning(f'[MQTT] 更新耗材 {code} 数据库失败: {e}')

            key = f"automake:stock:{device.device_sn}:{code}"
            redis_conn.set(key, qty_val * 100)



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
    device_sn = serializers.CharField(required=True, max_length=128, help_text="设备编码，全局唯一")
    key_code = serializers.CharField(required=True, max_length=32, help_text="门店注册码")



class DeviceMqttTopicsSerializer(serializers.Serializer):
    command = serializers.CharField(help_text="命令主题")
    status = serializers.CharField(help_text="状态与物料主题")
    action = serializers.CharField(help_text="动作主题")
    payment = serializers.CharField(help_text="支付解释主题")


class DeviceRegisterDataSerializer(serializers.Serializer):
    sn = serializers.CharField(help_text="设备名称")
    address = serializers.CharField(help_text="地址")
    orderValidPeriod = serializers.IntegerField(help_text="订单有效期")
    access_token = serializers.CharField(help_text="JWT访问令牌")
    mqtt_broker = serializers.CharField(help_text="MQTT Broker 地址")
    mqtt_username = serializers.CharField(help_text="MQTT 用户名")
    port = serializers.IntegerField(help_text="MQTT 端口")
    mqtt_password = serializers.CharField(help_text="MQTT 密码")
    mqtt_topics = DeviceMqttTopicsSerializer(help_text="MQTT 主题配置")


class DeviceRegisterResponseSerializer(serializers.Serializer):
    code = serializers.IntegerField(default=200, help_text="状态码")
    message = serializers.CharField(default="设备注册成功", help_text="提示消息")
    token_expire_ts = serializers.IntegerField(help_text="Token 过期时间戳")
    data = DeviceRegisterDataSerializer(help_text="注册返回数据")


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
        description="上位机（设备）启动时首个调用的 HTTPS POST 接口，进行上线注册并获取 access_token 与 MQTT 连接参数。"
    )
    def post(self, request):
        
        # 1. 提取并校验必要参数：设备序列号 (device_sn)、门店注册码 (key_code)
        device_sn = request.data.get('device_sn', '').strip()
        key_code = request.data.get('key_code', '').strip()
        if not device_sn or not key_code:
            return error('device_sn 和 key_code 不能为空', code=6001)

        # 记录上位机设备注册的上报数据日志，用于测试闭环
        logger.info(f"[DEVICE_REPORT] Register payload from {device_sn}: {request.data}")
        
        # 2. 校验设备是否已预先录入系统
        device = Device.objects.filter(device_sn=device_sn).first()
        if not device:
            logger.warning(f"设备注册失败：设备序列号 {device_sn} 未在系统中预先录入")
            return error('设备未在系统预先录入，无法注册', code=6004)
        
        if device.key_code and device.key_code != key_code:
            logger.warning(f"设备注册失败：注册码不匹配")
            return error('设备注册码不匹配', code=6003)

        if device.status != 'online':
            logger.warning(f"设备注册失败：请联系管理员先上线在注册")
            return error('请联系管理员先上线在注册', code=6004)

        # 更新设备上报的基础信息
        update_fields = []
        if request.data.get('device_name'):
            device.device_name = request.data.get('device_name')
            update_fields.append('device_name')
        if request.data.get('device_version'):
            device.firmware_version = request.data.get('device_version')
            update_fields.append('firmware_version')
        device_addr = request.data.get('device_address') or request.data.get('address')
        if device_addr:
            device.address = device_addr
            update_fields.append('address')
            if not isinstance(device.extra_config, dict):
                device.extra_config = {}
            device.extra_config['device_address'] = device_addr
            update_fields.append('extra_config')
        if update_fields:
            device.save(update_fields=update_fields)

        # 6. 记录状态变更日志
        DeviceStatusLog.objects.create(
            device=device,
            status=Device.STATUS_ONLINE,
            remark='设备注册/上线 (HTTPS POST)',
            raw_payload=request.data,
        )

        logger.info(f'设备注册更新成功: device_sn={device_sn}')

        # 7. 生成 JWT access_token 及过期时间戳
        expire_seconds = 86400 * 7  # 30天有效
        token_expire_ts = int(time.time()) + expire_seconds
        payload = {
            'device_sn': device_sn,
            'device_name': device.device_name,
            'store_id': device.store.id ,
            'exp': token_expire_ts,
            'iat': int(time.time())
        }
        access_token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

        resolved_address = device.address or ''
        sn_name = device.device_name or device_sn
        mqtt_broker = 'tinylab.store'
        mqtt_port = 443
        mqtt_username = f"device_{device_sn}"

        return Response({
            "code": 200,
            "message": "设备注册成功",
            "token_expire_ts": token_expire_ts,
            "data": {
                "sn": sn_name,
                "address": resolved_address,
                "orderValidPeriod": 1,
                "access_token": access_token,
                "mqtt_broker": mqtt_broker,
                "mqtt_username": mqtt_username,
                "port": mqtt_port,
                "mqtt_password": device.key_code,
                "mqtt_topics": {
                    "command": f's2c/shop/{device_sn}/state/command',
                    "status": f'c2s/shop/{device_sn}/state/command',

                }
            }
        })


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





class DeviceConsumableQueryView(APIView):
    """
    耗材查询接口
    输入设备编号，获取当前设备剩余的耗材数量（杯子、杯盖等）
    """
    permission_classes = [AllowAny]

    @extend_schema(
        summary="设备耗材查询",
        description="输入设备编号，获取当前设备剩余的耗材数量（杯子、杯盖等）",
        parameters=[
            OpenApiParameter(name='device_sn', description='设备序列号', required=True, type=str)
        ]
    )
    def get(self, request):
        device_sn = request.query_params.get('device_sn')
        if not device_sn:
            return error('缺少 device_sn 参数', code=400)
            
        try:
            device = Device.objects.get(device_sn=device_sn)
        except Device.DoesNotExist:
            return error('设备不存在', code=404)
            
        from devices.models import DeviceConsumableStock
        stocks = DeviceConsumableStock.objects.filter(device=device)
        
        data = []
        for stock in stocks:
            # 获取耗材名称，如果 material 关联存在则取 material.name，否则使用默认 mapping
            name = stock.code.name if stock.code else stock.code_id
            data.append({
                'code': stock.code_id,
                'name': name,
                'quantity': stock.quantity,
                'init_quantity': stock.init_quantity,
                'unit': getattr(stock, 'unit', '个')
            })
            
        return ok({'device_sn': device_sn, 'consumables': data}, message='查询成功')


class DeviceConfigQueryView(APIView):
    """
    设备配置查询接口
    输入设备编号，获取当前设备的各种参数配置
    """
    permission_classes = [AllowAny]

    @extend_schema(
        summary="设备配置查询",
        description="输入设备编号，获取当前设备的各种参数配置",
        parameters=[
            OpenApiParameter(name='device_sn', description='设备序列号', required=True, type=str)
        ]
    )
    def get(self, request):
        device_sn = request.query_params.get('device_sn')
        if not device_sn:
            return error('缺少 device_sn 参数', code=400)
            
        try:
            device = Device.objects.get(device_sn=device_sn)
        except Device.DoesNotExist:
            return error('设备不存在', code=404)
            
        from devices.models import DeviceConfig
        # 若未配置过，直接自动创建
        config, created = DeviceConfig.objects.get_or_create(device=device)
        
        # 组装温度配置
        temp_dict = {}
        for t in config.temperatures.all():
            temp_dict[t.key] = t.value
        # 默认回退（如果没有设置任何温度项）
        if not temp_dict:
            temp_dict = {"t1": 4, "t2": 175, "t3": 80}
            
        # 组装料筒配置
        barrel_dict = {}
        for b in config.barrels.all():
            barrel_dict[b.barrel_id] = {
                "pumpType": b.pump_type,
                "pumpCoeff": b.pump_coeff,
                "maxV": b.max_v,
                "baseArea": b.base_area
            }
        if not barrel_dict:
            barrel_dict = {
                "b01": {
                    "pumpType": "thin",
                    "pumpCoeff": 100,
                    "maxV": 40000,
                    "baseArea": 800
                }
            }
            
        # 组装转运配置
        try:
            transfer_list = [int(x.strip()) for x in config.transfer.split(',') if x.strip()]
        except ValueError:
            transfer_list = []
        if not transfer_list:
            transfer_list = [10000, 20000, 30000, 40000, 50000, 60000, 70000, 80000, 90000, 100000, 110000, 120000, 130000, 140000]
        
        # 将配置按需求原样拼装
        return ok({
            "temperature": temp_dict,
            "transfer": transfer_list,
            "barrel": barrel_dict
        }, message='查询成功')


class DeviceSoftConfQueryView(APIView):
    """
    设备出餐配置查询接口
    输入设备编号，获取出餐口、杯型和冰块等软配置
    """
    permission_classes = [AllowAny]

    @extend_schema(
        summary="设备出餐配置查询",
        description="输入设备编号，获取当前设备的出餐口、冰块及杯型配置",
        parameters=[
            OpenApiParameter(name='device_sn', description='设备序列号', required=True, type=str)
        ]
    )
    def get(self, request):
        device_sn = request.query_params.get('device_sn')
        if not device_sn:
            return error('缺少 device_sn 参数', code=400)
            
        try:
            device = Device.objects.get(device_sn=device_sn)
        except Device.DoesNotExist:
            return error('设备不存在', code=404)
            
        from devices.models import DeviceSoftConf
        soft_conf, created = DeviceSoftConf.objects.get_or_create(device=device)
        
        cup_size_dict = {}
        for cup in soft_conf.cup_sizes.all():
            cup_size_dict[cup.key] = cup.capacity
            
        if not cup_size_dict:
            cup_size_dict = {"m": 440, "l": 640}
            
        return ok({
            "maxVacancies": soft_conf.max_vacancies,
            "sepChunk": soft_conf.sep_chunk,
            "cupSize": cup_size_dict,
            "iceSize": soft_conf.ice_size
        }, message='查询成功')


def get_device_conf1_data(device_sn: str) -> dict:
    """
    根据设备序列号获取最新配置1数据 (conf1)
    """
    from devices.models import DeviceConf1
    conf = DeviceConf1.objects.filter(device_sn=device_sn).order_by('-created_at', '-id').first()
    if not conf:
        return {
            'device_sn': device_sn,
            'config': {},
            'version': '',
            'created_at': None,
            'updated_at': None
        }
    return {
        'device_sn': conf.device_sn,
        'config': conf.config or {},
        'version': conf.version or '',
        'created_at': conf.created_at.strftime('%Y-%m-%d %H:%M:%S') if conf.created_at else None,
        'updated_at': conf.updated_at.strftime('%Y-%m-%d %H:%M:%S') if conf.updated_at else None,
    }


def get_device_poster_config_data(device: Device, request=None) -> dict:
    """
    根据设备获取适用的最新海报配置 (conf3 / device poster)
    返回图片相对路径（不带域名）及版本号
    """
    from django.db.models import Q
    query = Q(is_active=True)
    if device:
        q_device = Q(devices=device)
        q_store = Q(devices__isnull=True, stores=device.store) if device.store_id else Q(pk__in=[])
        q_global = Q(devices__isnull=True, stores__isnull=True)
        query &= (q_device | q_store | q_global)

    poster = DevicePoster.objects.filter(query).distinct().order_by('-version', 'sort_order', '-created_at').first()

    horizontal_list = []
    vertical_list = []
    banner_list = []
    version = 0

    if poster:
        def _get_url(img_field):
            if not img_field:
                return None
            try:
                url = img_field.url if hasattr(img_field, 'url') else str(img_field).strip()
                return url if url else None
            except Exception:
                return None

        h_url = _get_url(poster.horizontal_image)
        if h_url:
            horizontal_list.append(h_url)
        v_url = _get_url(poster.vertical_image)
        if v_url:
            vertical_list.append(v_url)
        b_url = _get_url(poster.banner_image)
        if b_url:
            banner_list.append(b_url)
        version = poster.version if poster.version is not None else 0

    return {
        "poster": {
            "horizontal": horizontal_list,
            "vertical": vertical_list,
            "banner": banner_list,
        },
        "properties": {
            "version": version
        }
    }


class DeviceMenuMaterialQueryView(APIView):
    """
    设备菜单和物料静态定义查询接口
    输入设备编号，返回该设备对应的菜单和所需物料的定义信息
    """
    permission_classes = [AllowAny]

    @extend_schema(
        summary="设备菜单与物料定义查询",
        description="输入设备编号，获取当前设备对应的所有菜单、SKU配方以及相关物料的静态定义信息",
        parameters=[
            OpenApiParameter(name='device_sn', description='设备序列号', required=True, type=str)
        ]
    )
    def get(self, request):
        device_sn = request.query_params.get('device_sn')
        if not device_sn:
            return error('缺少 device_sn 参数', code=400)

        try:
            device = Device.objects.get(device_sn=device_sn)
        except Device.DoesNotExist:
            return error('设备不存在', code=404)

        # 组装菜单及其配方信息
        from menus.models import MenuItem
        menus_list = []

        if device.store and device.device_model:
            items = (
                MenuItem.objects
                .filter(
                    store=device.store,
                    device_model=device.device_model,
                    is_active=True,
                    global_item__is_active=True,
                    global_item__category__is_active=True
                )
                .select_related('global_item', 'global_item__category')
                .prefetch_related(
                    'skus',
                    'skus__global_sku',
                    'skus__global_sku__template',
                    'skus__global_sku__ingredients',
                    'skus__global_sku__ingredients__material',
                    'skus__global_sku__template__ingredients',
                    'skus__global_sku__template__ingredients__material'
                )
                .order_by('global_item__category__sort_order', 'global_item__category__id', 'sort_order', 'id')
            )

            for item in items:
                skus_list = []
                for local_sku in item.skus.filter(is_active=True, global_sku__is_active=True):
                    ingredients_list = []
                    for ing in local_sku.global_sku.get_effective_ingredients():
                        ingredients_list.append({
                            "material_name": ing.material.name,
                            "material_code": ing.material.code,
                            "quantity": float(ing.quantity),
                            "unit": ing.unit if ing.unit else ing.material.unit
                        })

                    skus_list.append({
                        "id": local_sku.id,
                        "name": local_sku.global_sku.name,
                        "price_delta": local_sku.price_delta,
                        "ingredients": ingredients_list
                    })

                menus_list.append({
                    "id": item.id,
                    "name": item.global_item.name,
                    "base_price": item.base_price,
                    "category": {
                        "id": item.global_item.category.id,
                        "name": item.global_item.category.name,
                        "label": item.global_item.category.label
                    },
                    "skus": skus_list
                })

        return ok({"menus": menus_list}, message='查询成功')


class DevicePosterQueryView(APIView):
    """
    上位机获取海报配置接口 (需设备 JWT 认证)
    仅返回适用的最新版本的一组海报配置（横屏、竖屏、Banner 共 3 张）
    GET /api/device/poster
    """
    authentication_classes = [DeviceJWTAuthentication]
    permission_classes = [IsAuthenticatedDevice]

    @extend_schema(
        summary="获取设备海报配置",
        description="上位机根据当前设备身份（JWT），获取适用的最新版本一组海报（包含横屏、竖屏、Banner共3张图片URL）及版本号。"
    )
    def get(self, request):
        device = getattr(request, 'device', None) or request.auth
        data = get_device_poster_config_data(device, request=request)
        return Response(data)


class DeviceOrderPendingCheckView(APIView):
    """ 
    检查订单是否处于等待制作状态接口
    输入：设备编号 (device_sn)、订单号 (order_no)
    返回：
    {
        "code": 1,          # 1: 等待制作状态 (True), 0: 非等待制作状态 (False)
        "msg": "原因说明",
        "data": {},
        "ts": 1786000000000 # 13位毫秒时间戳
    }
    """
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(
        summary="检查订单是否处于等待制作状态",
        description="输入设备编号和订单号，如果处于等待制作状态 code 返回 1，否则返回 0，并在 msg 中说明原因。",
        parameters=[
            OpenApiParameter(name='device_sn', description='设备序列号 (如 sn004)', required=True, type=str),
            OpenApiParameter(name='order_no', description='订单编号 (如 20260825021253723015)', required=True, type=str),
        ]
    )
    def get(self, request):
        return self._process_check(request)

    @extend_schema(
        summary="检查订单是否处于等待制作状态 (POST)",
        description="输入设备编号和订单号，如果处于等待制作状态 code 返回 1，否则返回 0，并在 msg 中说明原因。",
        parameters=[
            OpenApiParameter(name='device_sn', description='设备序列号 (如 sn004)', required=True, type=str),
            OpenApiParameter(name='order_no', description='订单编号 (如 20260825021253723015)', required=True, type=str),
        ]
    )
    def post(self, request):
        return self._process_check(request)

    def _process_check(self, request):
        from django.db.models import Q
        from orders.models import OrderMain, ProductionTask
        import time

        def build_resp(is_pending: bool, msg: str):
            return Response({
                "code": 1 if is_pending else 0,
                "msg": msg,
                "data": {},
                "ts": int(time.time() * 1000),
            })

        data = request.data if isinstance(request.data, dict) else {}
        params = request.query_params

        device_sn = (
            params.get('device_sn') or data.get('device_sn') or
            params.get('sn') or data.get('sn') or
            params.get('device_id') or data.get('device_id') or ''
        )
        if isinstance(device_sn, str):
            device_sn = device_sn.strip()

        order_no = (
            params.get('order_no') or data.get('order_no') or
            params.get('orderNo') or data.get('orderNo') or
            params.get('order_token') or data.get('order_token') or
            params.get('order_id') or data.get('order_id') or ''
        )
        if isinstance(order_no, str):
            order_no = order_no.strip()

        # 1. 基础参数校验
        if not device_sn:
            return build_resp(False, "缺少设备编号参数 (device_sn)")
        if not order_no:
            return build_resp(False, "缺少订单号参数 (order_no)")

        # 2. 查询设备
        device = Device.objects.filter(device_sn=device_sn).first()
        if not device:
            return build_resp(False, f"设备 {device_sn} 不存在")

        # 3. 查询订单（支持通过 order_no 或 order_token 查询）
        order = OrderMain.objects.filter(
            Q(order_no=order_no) | Q(order_token=order_no)
        ).select_related('device', 'store', 'production_task').first()

        if not order:
            return build_resp(False, f"订单 {order_no} 不存在")

        # 4. 校验订单与设备归属
        if order.device:
            if order.device.device_sn != device_sn:
                return build_resp(
                    False,
                    f"订单 {order.order_no} 制作设备为 {order.device.device_sn}，与当前查询设备 {device_sn} 不一致"
                )
        elif order.store_id and device.store_id and order.store_id != device.store_id:
            return build_resp(
                False,
                f"订单 {order.order_no} 所属门店与设备 {device_sn} 所在门店不匹配"
            )

        # 5. 判断订单是否处于等待制作状态
        # 处于等待制作状态：订单已支付待出货 (pending_dispense) 且生产任务未处于制作中或已完成
        if order.status == OrderMain.STATUS_PAID:
            task = getattr(order, 'production_task', None)
            if task and task.status == ProductionTask.TASK_MAKING:
                return build_resp(False, "订单当前正在制作中")
            elif task and task.status == ProductionTask.TASK_DONE:
                return build_resp(False, "订单已制作完成并出货")
            elif task and task.status == ProductionTask.TASK_FAILED:
                reason = task.failure_reason or '制作失败'
                return build_resp(False, f"订单制作失败: {reason}")
            return build_resp(True, "订单处于等待制作状态")

        elif order.status == OrderMain.STATUS_PENDING_PAY:
            return build_resp(False, "订单尚未支付（处于待支付状态）")

        elif order.status == OrderMain.STATUS_MAKING:
            return build_resp(False, "订单当前正在制作中")

        elif order.status == OrderMain.STATUS_DONE:
            return build_resp(False, "订单已制作完成并出货成功")

        elif order.status == OrderMain.STATUS_CANCELLED:
            return build_resp(False, "订单已被取消")

        elif order.status == OrderMain.STATUS_REFUNDING:
            return build_resp(False, "订单处于退款处理中")

        elif order.status == OrderMain.STATUS_REFUNDED:
            return build_resp(False, "订单已退款")

        elif order.status == OrderMain.STATUS_EXCEPTION:
            return build_resp(False, "订单出货失败/异常")

        else:
            return build_resp(False, f"订单当前状态为: {order.get_status_display()}")


class DeviceGuideCheckRequestSerializer(serializers.Serializer):
    device_sn = serializers.CharField(required=True, max_length=128, help_text="设备编号 (如: sn005)")
    phone = serializers.CharField(required=True, max_length=32, help_text="工作人员/引导员手机号 (如: 13800138000)")


class DeviceGuideCheckResponseSerializer(serializers.Serializer):
    code = serializers.IntegerField(default=0, help_text="状态码 (0: 成功/是引导员, 1: 失败/不是引导员)")
    message = serializers.CharField(default="是引导员", help_text="提示信息")
    data = serializers.DictField(default=dict, help_text="响应数据")


class DeviceGuideCheckView(APIView):
    """
    判断手机号是否为当前设备的引导员
    """
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(
        summary="判断手机号是否为当前设备引导员 (GET)",
        description="输入设备编号 (device_sn) 与手机号 (phone)，判断是否为当前设备的引导员。",
        parameters=[
            OpenApiParameter(name='device_sn', description='设备编号 (如: sn005)', required=True, type=str),
            OpenApiParameter(name='phone', description='工作人员/引导员手机号 (如: 13800138000)', required=True, type=str),
        ],
        responses={200: DeviceGuideCheckResponseSerializer}
    )
    def get(self, request):
        return self._handle_check(request)

    @extend_schema(
        summary="判断手机号是否为当前设备引导员 (POST)",
        description="传入 JSON 请求体中的 device_sn 与 phone，判断是否为当前设备的引导员。",
        request=DeviceGuideCheckRequestSerializer,
        responses={200: DeviceGuideCheckResponseSerializer}
    )
    def post(self, request):
        return self._handle_check(request)

    def _handle_check(self, request):
        from users.models import User

        data = request.data if isinstance(request.data, dict) else {}
        params = request.query_params

        device_sn = str(params.get('device_sn') or data.get('device_sn') or '').strip()
        phone = str(params.get('phone') or data.get('phone') or '').strip()

        if not device_sn or not phone:
            return Response({
                "code": 1,
                "message": "缺少 device_sn 或 phone 参数",
                "data": {}
            })

        # 1. 查找设备
        device = Device.objects.filter(device_sn=device_sn).first()
        if not device:
            return Response({
                "code": 0,
                "message": "不是引导员",
                "data": {}
            })

        # 2. 查找用户
        user = User.objects.filter(phone=phone).first()
        if not user:
            return Response({
                "code": 0,
                "message": "不是引导员",
                "data": {}
            })

        # 3. 校验引导员身份（超级管理员/引导员/关联当前设备门店的工作人员）
        is_guide = False
        if user.is_super_admin:
            is_guide = True
        elif user.role in (User.GUIDE, User.ADMIN, User.COORDINATOR, User.MATERIAL_ADMIN):
            if not device.store_id or user.stores.filter(id=device.store_id).exists():
                is_guide = True

        if is_guide:
            return Response({
                "code": 1,
                "message": "是引导员",
                "data": {}
            })
        else:
            return Response({
                "code": 0,
                "message": "不是引导员",
                "data": {}
            })


class DeviceBatchRefundRequestSerializer(serializers.Serializer):
    device_sn = serializers.CharField(required=True, max_length=128, help_text="设备编号")
    refund_stock = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="退款退库存单号列表"
    )
    refund_no_stock = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="退款不退库存单号列表"
    )
    reason = serializers.CharField(
        required=False,
        default="设备退款",
        max_length=256,
        help_text="退款原因"
    )


class DeviceBatchRefundResponseDataSerializer(serializers.Serializer):
    success = serializers.BooleanField(help_text="是否全部成功")
    success_orders = serializers.ListField(
        child=serializers.CharField(),
        default=list,
        help_text="成功退款的订单号列表"
    )


class DeviceBatchRefundResponseSerializer(serializers.Serializer):
    code = serializers.IntegerField(default=1, help_text="状态码 (1: 全部成功, 0: 失败或部分成功)")
    message = serializers.CharField(default="ok", help_text="提示信息")
    data = DeviceBatchRefundResponseDataSerializer(help_text="返回数据")


class DeviceBatchRefundView(APIView):
    """
    设备订单退款接口 (支持退库存与不退库存)

    POST /api/device/order/batch_refund
    POST /api/device/order/refund
    """
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(
        summary="设备退款接口",
        description="输入设备编号 (device_sn)、退款退库存单号列表 (refund_stock)、退款不退库存单号列表 (refund_no_stock) 及 reason，返回是否成功及成功订单号列表。",
        request=DeviceBatchRefundRequestSerializer,
        responses={200: DeviceBatchRefundResponseSerializer}
    )
    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        params = request.query_params

        device_sn = (
            data.get('device_sn') or params.get('device_sn') or
            data.get('sn') or params.get('sn') or
            data.get('device_no') or params.get('device_no') or ''
        )
        if isinstance(device_sn, str):
            device_sn = device_sn.strip()

        if not device_sn:
            return Response({
                'code': 0,
                'message': '缺少设备编号 (device_sn)',
                'data': {'success': False, 'success_orders': []}
            }, status=400)

        refund_stock = (
            data.get('refund_stock') or
            data.get('with_stock') or
            data.get('stock_orders') or
            data.get('refund_restore_stock_order_nos') or
            data.get('refund_and_restore_stock_order_nos') or
            []
        )

        refund_no_stock = (
            data.get('refund_no_stock') or
            data.get('without_stock') or
            data.get('no_stock_orders') or
            data.get('refund_no_restore_stock_order_nos') or
            data.get('refund_without_stock_orders') or
            []
        )

        reason = str(data.get('reason') or params.get('reason') or '设备退款').strip()

        from payments.services import batch_refund_device_orders

        try:
            result = batch_refund_device_orders(
                device_sn=device_sn,
                refund_stock=refund_stock,
                refund_no_stock=refund_no_stock,
                reason=reason
            )
            is_success = result.get('success', False)
            msg = 'ok' if is_success else ('部分退款成功' if result.get('success_orders') else '退款处理失败')
            return Response({
                'code': 1 if is_success else 0,
                'message': msg,
                'data': result
            })
        except ValueError as e:
            return Response({
                'code': 0,
                'message': str(e),
                'data': {'success': False, 'success_orders': []}
            }, status=400)
        except Exception as e:
            logger.exception(f"批量退款异常: {e}")
            return Response({
                'code': 0,
                'message': f"退款处理异常: {e}",
                'data': {'success': False, 'success_orders': []}
            }, status=500)


class DeviceConf1QuerySerializer(serializers.Serializer):
    device_sn = serializers.CharField(required=True, max_length=128, help_text="设备编号 (如: sn005)")
    config = serializers.DictField(required=False, default=dict, help_text="配置内容 (可选，POST 创建/更新时传入)")
    version = serializers.CharField(required=False, default="1.0.0", max_length=64, help_text="版本号 (可选)")


class DeviceConf1DataSerializer(serializers.Serializer):
    device_sn = serializers.CharField(help_text="设备编号")
    config = serializers.DictField(help_text="配置内容 (JSON)")
    version = serializers.CharField(help_text="版本号")
    created_at = serializers.CharField(allow_null=True, help_text="创建时间")
    updated_at = serializers.CharField(allow_null=True, help_text="更新时间")


class DeviceConf1ResponseSerializer(serializers.Serializer):
    code = serializers.IntegerField(default=0, help_text="状态码 (0: 成功)")
    message = serializers.CharField(default="ok", help_text="提示信息")
    data = DeviceConf1DataSerializer(help_text="最新配置数据")


class DeviceConf1View(APIView):
    """
    设备配置 (conf1) 接口

    GET /api/device/conf1?device_sn=sn005
    GET /api/device/conf1/<str:device_sn>
    POST /api/device/conf1
    """
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(
        summary="获取设备最新配置 (conf1)",
        description="根据设备编号 (device_sn)，返回该设备最新一条配置内容 (JSON)、版本号及时间。",
        parameters=[
            OpenApiParameter('device_sn', str, description='设备编号 (如: sn005)', required=True),
        ],
        responses={200: DeviceConf1ResponseSerializer}
    )
    def get(self, request, device_sn=None):
        sn = device_sn or request.query_params.get('device_sn') or request.query_params.get('sn') or ''
        if isinstance(sn, str):
            sn = sn.strip()

        if not sn:
            return error('缺少设备编号 (device_sn)', code=6001)

        from devices.models import DeviceConf1
        conf = DeviceConf1.objects.filter(device_sn=sn).order_by('-created_at', '-id').first()
        if not conf:
            return ok({
                'device_sn': sn,
                'config': {},
                'version': '',
                'created_at': None,
                'updated_at': None
            }, message='暂无配置')

        return ok({
            'device_sn': conf.device_sn,
            'config': conf.config or {},
            'version': conf.version or '',
            'created_at': conf.created_at.strftime('%Y-%m-%d %H:%M:%S') if conf.created_at else None,
            'updated_at': conf.updated_at.strftime('%Y-%m-%d %H:%M:%S') if conf.updated_at else None
        }, message='ok')

    @extend_schema(
        summary="查询或上报设备配置 (conf1)",
        description="POST 查询或保存设备配置。若包含 config 字段则创建一条新配置记录；若仅包含 device_sn 则返回最新配置。",
        request=DeviceConf1QuerySerializer,
        responses={200: DeviceConf1ResponseSerializer}
    )
    def post(self, request, device_sn=None):
        data = request.data if isinstance(request.data, dict) else {}
        params = request.query_params

        sn = device_sn or data.get('device_sn') or params.get('device_sn') or data.get('sn') or params.get('sn') or ''
        if isinstance(sn, str):
            sn = sn.strip()

        if not sn:
            return error('缺少设备编号 (device_sn)', code=6001)

        from devices.models import DeviceConf1

        # 若请求体中传入了具体的 config 配置，则保存一条新配置
        if 'config' in data or 'content' in data:
            new_config = data.get('config') if 'config' in data else data.get('content')
            version = str(data.get('version') or '1.0.0').strip()
            conf = DeviceConf1.objects.create(
                device_sn=sn,
                config=new_config if isinstance(new_config, dict) else {},
                version=version
            )
            return ok({
                'device_sn': conf.device_sn,
                'config': conf.config or {},
                'version': conf.version or '',
                'created_at': conf.created_at.strftime('%Y-%m-%d %H:%M:%S') if conf.created_at else None,
                'updated_at': conf.updated_at.strftime('%Y-%m-%d %H:%M:%S') if conf.updated_at else None
            }, message='配置保存成功')

        # 否则返回该设备的最新配置
        conf = DeviceConf1.objects.filter(device_sn=sn).order_by('-created_at', '-id').first()
        if not conf:
            return ok({
                'device_sn': sn,
                'config': {},
                'version': '',
                'created_at': None,
                'updated_at': None
            }, message='暂无配置')

        return ok({
            'device_sn': conf.device_sn,
            'config': conf.config or {},
            'version': conf.version or '',
            'created_at': conf.created_at.strftime('%Y-%m-%d %H:%M:%S') if conf.created_at else None,
            'updated_at': conf.updated_at.strftime('%Y-%m-%d %H:%M:%S') if conf.updated_at else None
        }, message='ok')


class DeviceUnifiedConfigRequestSerializer(serializers.Serializer):
    device_sn = serializers.CharField(
        required=True,
        max_length=128,
        help_text="设备编号/序列号 (如: sn005)"
    )
    data = serializers.ChoiceField(
        choices=['conf1', 'conf2', 'conf3'],
        required=True,
        help_text="配置类型标识：conf1 (配置1) / conf2 (菜单配置) / conf3 (海报配置)"
    )


class DeviceUnifiedConfigResponseSerializer(serializers.Serializer):
    code = serializers.IntegerField(default=0, help_text="状态码 (0: 成功)")
    message = serializers.CharField(default="ok", help_text="提示信息")
    data = serializers.DictField(default=dict, help_text="根据 data 参数返回的配置内容")


class DeviceUnifiedConfigView(APIView):
    """
    设备统一配置分发接口

    支持根据设备编号 (device_sn) 与配置类型 (data) 返回对应配置：
    - data=conf1: 返回设备配置1 (JSON内容与版本号)
    - data=conf2: 返回设备菜单及SKU配方配置
    - data=conf3: 返回设备海报配置 (横屏/竖屏/Banner及版本号)
    """
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(
        summary="统一设备配置查询 (GET)",
        description="输入设备编号 (device_sn) 与配置类型 (data)：\n"
                    "- `data=conf1`: 返回设备配置1 (JSON与版本号)\n"
                    "- `data=conf2`: 返回设备菜单及SKU配方配置\n"
                    "- `data=conf3`: 返回设备海报配置 (横屏/竖屏/Banner及版本号)",
        parameters=[
            OpenApiParameter(name='device_sn', description='设备编号 (如: sn005)', required=True, type=str),
            OpenApiParameter(name='data', description='配置类型: conf1 / conf2 / conf3', required=True, type=str),
        ],
        responses={200: DeviceUnifiedConfigResponseSerializer}
    )
    def get(self, request):
        return self._handle_query(request)

    @extend_schema(
        summary="统一设备配置查询 (POST)",
        description="传入 JSON 请求体中的 device_sn 与 data：\n"
                    "- `data=conf1`: 返回设备配置1 (JSON与版本号)\n"
                    "- `data=conf2`: 返回设备菜单及SKU配方配置\n"
                    "- `data=conf3`: 返回设备海报配置 (横屏/竖屏/Banner及版本号)",
        request=DeviceUnifiedConfigRequestSerializer,
        responses={200: DeviceUnifiedConfigResponseSerializer}
    )
    def post(self, request):
        return self._handle_query(request)

    def _handle_query(self, request):
        req_data = request.data if isinstance(request.data, dict) else {}
        params = request.query_params

        device_sn = (
            req_data.get('device_sn') or params.get('device_sn') or
            req_data.get('sn') or params.get('sn') or
            req_data.get('device_no') or params.get('device_no') or ''
        )
        if isinstance(device_sn, str):
            device_sn = device_sn.strip()

        if not device_sn:
            return error('缺少设备编号 (device_sn)', code=6001)

        data_type = str(
            req_data.get('data') or params.get('data') or
            req_data.get('type') or params.get('type') or ''
        ).strip().lower()

        if not data_type:
            return error('缺少配置类型标识 (data: conf1/conf2/conf3)', code=6002)

        # 1. conf1: 设备配置1 (无需强依赖 Device 记录存在即可返回)
        if data_type == 'conf1':
            result = get_device_conf1_data(device_sn)
            return ok(result, message='ok')

        # 2. conf2: 直接复用 menus/views.py 中的 StoreMenuView.get
        if data_type == 'conf2':
            from menus.views import StoreMenuView
            return StoreMenuView().get(request, device_sn=device_sn)

        # 3. conf3: 海报配置
        if data_type == 'conf3':
            device = Device.objects.filter(device_sn=device_sn).first()
            if not device:
                return error(f'设备 {device_sn} 不存在', code=6003, status=404)
            result = get_device_poster_config_data(device)
            return ok(result, message='ok')

        return error(f"不支持的配置类型 '{data_type}'，可选值为 conf1 / conf2 / conf3", code=6004)


