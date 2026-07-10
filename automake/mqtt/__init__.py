"""
MQTT 客户端模块

连接 EMQX，实现云端向上位机下发命令，并接收上位机的状态/心跳/物料上报。
使用 paho-mqtt 2.x API（callback_api_version 参数）。

Topic 规范：
  下发命令：  automake/device/{device_sn}/command
  接收回报：  automake/device/{device_sn}/status
"""

import json
import logging
import threading
import paho.mqtt.client as mqtt
from django.conf import settings
from django.db import close_old_connections

logger = logging.getLogger(__name__)

# 全局 MQTT 客户端单例
_client: mqtt.Client = None
_lock = threading.Lock()


def get_mqtt_client() -> mqtt.Client:
    """
    获取全局 MQTT 客户端（单例）

    线程安全。如果客户端尚未创建，则进行初始化并建立异步连接。
    由 paho-mqtt 在后台线程处理自动重连。
    """
    global _client
    if _client is None:
        logger.error(f'MQTT 启动连接不存在')
        with _lock:
            if _client is None:
                
                _client = _create_client()
    else:
        logger.error(f'MQTT 启动连接已经存在')

                
    return _client


def _create_client() -> mqtt.Client:
    """创建并启动 MQTT 客户端"""
    # 单进程模式下，直接使用配置的固定 Client ID
    client_id = settings.MQTT_CLIENT_ID

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        clean_session=True,
    )

    # 设置认证信息（若 EMQX 配置了用户名密码）
    if settings.MQTT_USERNAME:
        client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD)

    # 注册回调
    client.on_connect = _on_connect
    client.on_disconnect = _on_disconnect
    client.on_message = _on_message

    try:
        # 使用 connect_async 以便在 MQTT 代理暂时不可达时也能正常启动，由后台 loop 自动重试连接
        client.connect_async(
            host=settings.MQTT_HOST,
            port=settings.MQTT_PORT,
            keepalive=60,
        )
        # 在后台线程中维持连接（非阻塞）
        client.loop_start()
        logger.info(f'MQTT 客户端已启动 (异步连接模式)，连接至 {settings.MQTT_HOST}:{settings.MQTT_PORT}，Client ID: {client_id}')
    except Exception as e:
        logger.error(f'MQTT 启动连接异常: {e}')

    return client


def _on_connect(client, userdata, flags, reason_code, properties):
    """连接成功回调"""
    if reason_code.is_failure:
        logger.error(f'MQTT 连接失败，原因码: {reason_code}')
        return
    logger.info(f'MQTT 已连接，Client ID: {client._client_id.decode("utf-8") if isinstance(client._client_id, bytes) else client._client_id}，reason_code={reason_code}')
    
    # 订阅所有设备状态、物料及指令 Topic（标准单进程订阅模式）
    try:
        client.subscribe('automake/device/+/status', qos=1)
        client.subscribe('automake/device/+/material', qos=1)
        client.subscribe('automake/device/+/command', qos=1)
        client.subscribe('automake/device/+/heart', qos=1)
        logger.info('MQTT 标准订阅已注册: status, material 和 command')
    except Exception as e:
        logger.error(f'MQTT 注册订阅失败: {e}')


def _on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    """断线回调（paho-mqtt 会自动重连，此处仅记录日志）"""
    logger.warning(f'MQTT 连接断开，reason_code={reason_code}，等待后台自动重连...')


def _on_message(client, userdata, msg):
    """
    接收上位机消息回调

    根据 Topic 分发到不同的处理函数，并处理 Django 线程内数据库连接的自动开关与清理。
    """
    topic = msg.topic
    try:
        payload = json.loads(msg.payload.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error(f'MQTT 消息解析失败，topic={topic}: {e}')
        return

    logger.debug(f'MQTT 收到消息，topic={topic}')

    # 解析 Topic，格式：automake/device/{device_sn}/{type}
    parts = topic.split('/')
    if len(parts) < 4:
        return

    device_sn = parts[2]
    msg_type = parts[3]

    try:
        # 在执行数据库操作前，清理可能已经失效的旧数据库连接
        close_old_connections()

        if msg_type == 'status':
            _handle_device_status(device_sn, payload)
        elif msg_type == 'material':
            _handle_material_report(device_sn, payload)
        elif msg_type == 'command':
            _handle_device_command_intercept(device_sn, topic, payload)
    except Exception as e:
        logger.exception(f'处理 MQTT 消息异常，topic={topic}: {e}')
    finally:
        # 处理完毕后关闭当前线程的数据库连接，防止在常驻后台的 MQTT 线程中造成连接泄露
        close_old_connections()



def _handle_device_status(device_sn: str, payload: dict):
    """
    处理上位机设备/订单状态上报
    """
  
    

    is_health_report = ('temperature' in payload) or ('cup' in payload) 
    
    if is_health_report:
        logger.info(f"[DEVICE_REPORT] MQTT Machine health status payload from {device_sn}: {payload}")
        try:
            from monitor.models import DeviceMonitorSnapshot
            
            # 使用临时对象执行状态检测
            temp_snapshot = DeviceMonitorSnapshot(device_sn=device_sn, raw_data=payload)
            temp_snapshot.check_health_status()
            
            # 和数据库中的最新状态进行比较
            snapshot = DeviceMonitorSnapshot.objects.filter(device_sn=device_sn).order_by('-reported_at').first()
            should_update = False
            
            if not snapshot:
                should_update = True
            elif snapshot.healthy != temp_snapshot.healthy or snapshot.abnormality != temp_snapshot.abnormality:
                should_update = True
                
            if should_update:
                # 状态不一样则新增一条记录，以便追溯历史
                DeviceMonitorSnapshot.objects.create(
                    device_sn=device_sn,
                    raw_data=payload
                )
                logger.info(f"设备 {device_sn} 健康状态发生变化，已新增监控快照。当前健康: {temp_snapshot.healthy}, 异常项: {temp_snapshot.abnormality}")
            else:
                logger.debug(f"设备 {device_sn} 健康状态无变化，跳过数据库更新")

        except Exception as e:
            logger.exception(f'处理设备健康快照检查失败，device_sn={device_sn}: {e}')
            



def _handle_material_report(device_sn: str, payload: dict):
    """
    处理上位机物料状态上报

    payload 示例：
    {
        "materials": [
            {"code": "coffee_bean", "name": "咖啡豆", "quantity": 850, "unit": "g"},
            ...
        ]
    }
    """
    logger.info(f"[DEVICE_REPORT] MQTT Material report payload from {device_sn}: {payload}")
    from devices.views import receive_material_report  # 避免循环导入
    try:
        receive_material_report(device_sn, payload)
    except Exception as e:
        logger.exception(f'处理设备物料状态上报失败，device_sn={device_sn}: {e}')


def issue_device_command(device_sn: str, command_type: str, payload: dict = None, order_no: str = None) -> bool:
    """
    向上位机下发通用指令（如 cancel, reset, sync_resource）并记录到数据库。

    :param device_sn: 目标设备序列号
    :param command_type: 指令类型（例如 DeviceCommand.CMD_CANCEL, CMD_RESET, CMD_SYNC 等）
    :param payload: 指令参数内容
    :param order_no: 关联的订单号（可选）
    :return: True 表示发送成功
    """
    from devices.models import Device, DeviceCommand
    from orders.models import OrderMain
    from django.utils import timezone

    if payload is None:
        payload = {}

    topic = f'automake/device/{device_sn}/command'
    message = {
        'type': command_type,
        **payload,
    }
    if order_no:
        message['order_no'] = order_no

    device = Device.objects.filter(device_sn=device_sn).first()
    order = OrderMain.objects.filter(order_no=order_no).first() if order_no else None

    success = False
    try:
        client = get_mqtt_client()
        result = client.publish(topic, json.dumps(message, ensure_ascii=False), qos=1)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.info(f'MQTT 命令 {command_type} 已发布，device_sn={device_sn}')
            success = True
        else:
            logger.error(f'MQTT {command_type} 发布失败，rc={result.rc}，topic={topic}')
    except Exception as e:
        logger.exception(f'MQTT 发布命令 {command_type} 异常: {e}')

    # 记录设备命令到数据库
    if device:
        try:
            DeviceCommand.objects.create(
                device=device,
                order=order,
                command_type=command_type,
                payload=message,
                status=DeviceCommand.SENT if success else DeviceCommand.FAILED,
                sent_at=timezone.now() if success else None,
            )
        except Exception as db_err:
            logger.error(f'记录设备指令数据库失败: {db_err}')

    return success


def issue_make_command(order_no: str, device_sn: str, command_payload: dict) -> bool:
    """
    向上位机下发制作命令 并记录命令历史与更新生产任务状态

    :param order_no: 订单号
    :param device_sn: 目标设备序列号
    :param command_payload: 命令内容（商品列表等）
    :return: True 表示发送成功
    """
    from orders.models import ProductionTask
    from django.utils import timezone

    # 借用通用指令函数下发并写入 DeviceCommand 历史记录
    success = issue_device_command(
        device_sn=device_sn,
        command_type='make',
        payload=command_payload,
        order_no=order_no
    )

    # 特殊逻辑：如果是制作命令，还需要同步更新生产任务 ProductionTask 状态
    if success:
        try:
            from orders.models import OrderMain
            order = OrderMain.objects.filter(order_no=order_no).first()
            if order:
                ProductionTask.objects.filter(order=order).update(
                    status=ProductionTask.TASK_SENT,
                    sent_at=timezone.now(),
                )
        except Exception as e:
            logger.error(f'更新生产任务状态失败: {e}')

    return success


def _handle_device_command_intercept(device_sn: str, topic: str, payload: dict):
    """
    拦截下发的设备命令并存入 Redis 缓存中，用于上位机模拟器页面展示。
    """
    try:
        from django.core.cache import cache
        import time
        
        # 缓存键名格式：simulator:logs:{device_sn}
        key = f"simulator:logs:{device_sn}"
        logs = cache.get(key, [])
        
        # 记录接收到的命令数据
        logs.append({
            "timestamp": time.time(),
            "type": "recv",
            "topic": topic,
            "payload": payload
        })
        
        # 仅保留最近的 100 条日志
        if len(logs) > 100:
            logs = logs[-100:]
            
        cache.set(key, logs, timeout=86400) # 缓存有效期 1 天
        logger.info(f"[SIMULATOR] 拦截并缓存设备指令: device_sn={device_sn}, topic={topic}")
    except Exception as e:
        logger.error(f"[SIMULATOR] 缓存指令异常: {e}")

