"""
ws_device consumers.py —— 上位机 WebSocket 消息处理器

协议约定（JSON over WebSocket）：
  - 上位机（Java） → Django Server：发送指令/状态上报
  - Django Server → 上位机（Java）：下发指令/确认/推送

消息格式统一使用 JSON：
{
    "type":    "<消息类型>",   # 必填，决定业务处理逻辑
    "sn":      "<设备编号>",   # 必填，唯一标识上位机设备
    "data":    { ... },        # 可选，携带业务数据
    "msg_id":  "<消息ID>",    # 可选，用于请求-响应追踪
    "ts":      1234567890      # 可选，客户端时间戳（毫秒）
}

已定义的消息类型 (type):
  上行（Java → Server）:
    "register"       —— 设备首次连接注册（携带 sn 和 device_version）
    "heartbeat"      —— 心跳保活（每 30 秒发一次）
    "order_complete" —— 上报订单出餐完成
    "order_failed"   —— 上报订单制作失败
    "status_report"  —— 设备状态上报（温度、余料等）

  下行（Server → Java）:
    "ack"            —— 通用确认回复
    "dispense_order" —— 下发出餐指令
    "error"          —— 错误通知

详细协议见 docs/websocket_dev_guide.md
"""

import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

from orders.models import OrderMain
from orders.services import update_order_status, process_dispense_failure

logger = logging.getLogger('ws_device')


class DeviceConsumer(AsyncWebsocketConsumer):
    """
    上位机 WebSocket 消费者

    路由格式：ws://<host>/ws/device/<sn>/
    每台上位机以其设备编号（sn）作为唯一标识，
    连接后加入以 sn 命名的 Channel Group，
    服务端可通过 group_send 向指定设备推送消息。
    """

    async def connect(self):
        """
        WebSocket 握手建立时调用。
        从 URL 路由中获取设备编号（sn），将连接加入对应 Group。
        """
        # 从 URL 路由捕获的设备编号
        self.sn = self.scope['url_route']['kwargs']['sn']
        # Channel Group 名称：device_<sn>（用于服务端主动推送）
        self.group_name = f'device_{self.sn}'

        # 将当前连接加入设备专属 Group
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )

        # 接受连接
        await self.accept()

        logger.info(f'[WS] 设备连接成功: sn={self.sn}, channel={self.channel_name}')

        # 发送欢迎消息，告知设备连接已建立
        await self.send_json({
            'type': 'connected',
            'sn': self.sn,
            'message': 'WebSocket 连接已建立，请发送 register 消息完成注册。'
        })

    async def disconnect(self, close_code):
        """
        WebSocket 连接断开时调用（主动断开或网络异常）。
        将连接从 Group 中移除。
        """
        logger.info(f'[WS] 设备断开连接: sn={self.sn}, code={close_code}')

        # 从 Group 中移除此连接
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        """
        接收上位机发来的消息（文本 JSON 格式）。
        根据 type 字段分发到对应的处理方法。
        """
        try:
            payload = json.loads(text_data)
        except (json.JSONDecodeError, TypeError):
            # 非法 JSON，返回错误
            await self.send_json({
                'type': 'error',
                'code': 'INVALID_JSON',
                'message': '消息格式错误，请发送有效的 JSON 字符串。'
            })
            return

        msg_type = payload.get('type', '')
        sn = payload.get('sn', self.sn)  # 消息中的 sn 应与 URL 中一致
        msg_id = payload.get('msg_id', '')
        data = payload.get('data', '')

        logger.debug(f'[WS] 收到消息: sn={sn}, type={msg_type}, msg_id={msg_id}, data={data}')

        # ---- 消息类型路由 ----
        if msg_type == 'register':
            await self.handle_register(payload)
        elif msg_type == 'heartbeat':
            await self.handle_heartbeat(payload)
        elif msg_type == 'order_complete':
            await self.handle_order_complete(payload)
        elif msg_type == 'order_failed':
            await self.handle_order_failed(payload)
        elif msg_type == 'status_report':
            await self.handle_status_report(payload)
        else:
            # 未知消息类型
            logger.warning(f'[WS] 未知消息类型: type={msg_type}, sn={sn}')
            await self.send_json({
                'type': 'error',
                'code': 'UNKNOWN_TYPE',
                'msg_id': msg_id,
                'message': f'未知的消息类型: {msg_type}'
            })

    # ================================================================
    # 上行消息处理方法
    # ================================================================

    async def handle_register(self, payload):
        """
        处理设备注册消息。
        上位机连接后应立即发送 register，告知设备版本、编号等信息。
        """
        data = payload.get('data', {})
        device_version = data.get('device_version', 'unknown')
        msg_id = payload.get('msg_id', '')

        logger.info(f'[WS] 设备注册: sn={self.sn}, version={device_version}')

        # 可在此处更新数据库中的设备在线状态（异步调用同步 ORM）
        # await self.update_device_online_status(self.sn, True)

        # 回复注册确认
        await self.send_json({
            'type': 'ack',
            'msg_id': msg_id,
            'action': 'register',
            'sn': self.sn,
            'message': '设备注册成功，已上线。'
        })

    async def handle_heartbeat(self, payload):
        """
        处理心跳消息（Java 端每 30 秒发送一次）。
        服务端直接回 pong，维持连接存活。
        """
        msg_id = payload.get('msg_id', '')
        await self.send_json({
            'type': 'ack',
            'msg_id': msg_id,
            'action': 'heartbeat',
            'sn': self.sn
        })

    async def handle_order_complete(self, payload):
        """
        处理上位机上报的"订单出餐完成"消息。
        data 中需包含 order_no（订单号）。
        """
        data = payload.get('data', {})
        order_no = data.get('order_no', '')
        msg_id = payload.get('msg_id', '')

        if not order_no:
            await self.send_json({
                'type': 'error',
                'code': 'MISSING_FIELD',
                'msg_id': msg_id,
                'message': 'order_complete 消息缺少 data.order_no 字段。'
            })
            return

        logger.info(f'[WS] 收到出餐完成: order_no={order_no}, sn={self.sn}')

        try:
            # 异步查询订单对象
            order = await database_sync_to_async(
                OrderMain.objects.get
            )(order_no=order_no)
            # 更新订单状态为“已完成”
            await database_sync_to_async(update_order_status)(
                order=order,
                new_status=OrderMain.STATUS_DONE,
                operator=f'device_{self.sn}',
                remark='WebSocket 上位机上报出餐完成'
            )
            await self.send_json({
                'type': 'ack',
                'msg_id': msg_id,
                'action': 'order_complete',
                'order_no': order_no,
                'message': '订单状态已更新为完成。'
            })
        except OrderMain.DoesNotExist:
            logger.warning(f'[WS] order_complete: 订单不存在 order_no={order_no}')
            await self.send_json({
                'type': 'error',
                'code': 'ORDER_NOT_FOUND',
                'msg_id': msg_id,
                'message': f'订单不存在: {order_no}'
            })
        except Exception as e:
            logger.error(f'[WS] 处理 order_complete 失败: order_no={order_no}, error={e}')
            await self.send_json({
                'type': 'error',
                'code': 'SERVER_ERROR',
                'msg_id': msg_id,
                'message': f'订单状态更新失败: {str(e)}'
            })

    async def handle_order_failed(self, payload):
        """
        处理上位机上报的"订单制作失败"消息。
        data 中需包含 order_no 和 reason（失败原因）。
        """
        data = payload.get('data', {})
        order_no = data.get('order_no', '')
        reason = data.get('reason', '上位机上报制作失败')
        msg_id = payload.get('msg_id', '')

        if not order_no:
            await self.send_json({
                'type': 'error',
                'code': 'MISSING_FIELD',
                'msg_id': msg_id,
                'message': 'order_failed 消息缺少 data.order_no 字段。'
            })
            return

        logger.info(f'[WS] 收到制作失败: order_no={order_no}, reason={reason}, sn={self.sn}')

        try:
            order = await database_sync_to_async(
                OrderMain.objects.get
            )(order_no=order_no)
            # 调用订单失败回滚服务（包含库存回滚逻辑）
            await database_sync_to_async(process_dispense_failure)(
                order=order,
                operator=f'device_{self.sn}',
                remark=reason
            )
            await self.send_json({
                'type': 'ack',
                'msg_id': msg_id,
                'action': 'order_failed',
                'order_no': order_no,
                'message': '订单状态已更新为失败。'
            })
        except OrderMain.DoesNotExist:
            logger.warning(f'[WS] order_failed: 订单不存在 order_no={order_no}')
            await self.send_json({
                'type': 'error',
                'code': 'ORDER_NOT_FOUND',
                'msg_id': msg_id,
                'message': f'订单不存在: {order_no}'
            })
        except Exception as e:
            logger.error(f'[WS] 处理 order_failed 失败: order_no={order_no}, error={e}')
            await self.send_json({
                'type': 'error',
                'code': 'SERVER_ERROR',
                'msg_id': msg_id,
                'message': f'订单失败状态更新异常: {str(e)}'
            })

    async def handle_status_report(self, payload):
        """
        处理设备状态上报消息。

        上位机协议约定的 data 字段结构：
        {
            "healthy": false,       # 整机健康状态
            "lastTime": 0,          # 上位机时间戳（毫秒）
            "disconnected": false,  # 是否断线
            "memSize": {"master": 1024, "slave": 1024},
            "abnormality": {        # 各传感器/执行机构异常状态
                "temperature": {"mainR": 25.0, "chargeR": 25.0},
                "ice": {"a1": false}, "transfer": {"a1": false},
                "drop": {"a1": false}, "drain": {"a1": false},
                "liquid": {"a1": false}, "solid": {"a1": false},
                "press": {"a1": false}, "cover": {"a1": false},
                "arm": {"a1": false}, "take": {"a1": false}
            }
        }

        处理逻辑：
          1. 解析协议字段，写入/更新 DeviceMonitorSnapshot（upsert）
          2. 向 monitor_dashboard Channel Group 广播最新状态
          3. 向设备回复 ack
        """
        data = payload.get('data', {})
        msg_id = payload.get('msg_id', '')

        logger.info(f'[WS] 设备状态上报: sn={self.sn}, data={data}')

        # ---- 1. 持久化到监控快照表（upsert：存在则更新，不存在则创建）----
        snapshot = await database_sync_to_async(self._upsert_monitor_snapshot)(data)

        # ---- 2. 向监控大屏广播实时状态 ------------------------------------
        # 通过 Channel Layer 向所有连接的监控大屏客户端推送最新状态
        push_payload = {
            'type': 'device_status',           # 前端识别的消息类型
            'device_sn': self.sn,
            'display_status': snapshot.display_status,  # normal / warning / fault
            'healthy': snapshot.healthy,
            'disconnected': snapshot.disconnected,
            'last_time': snapshot.last_time,
            'mem_size': snapshot.mem_size,
            'abnormality': snapshot.abnormality,
            'reported_at': snapshot.reported_at.isoformat(),
        }
        await self.channel_layer.group_send(
            'monitor_dashboard',
            {
                'type': 'monitor.device_status',  # 调用 MonitorConsumer.monitor_device_status
                'payload': push_payload,
            }
        )

        # ---- 3. 向设备回复 ack --------------------------------------------
        await self.send_json({
            'type': 'ack',
            'msg_id': msg_id,
            'action': 'status_report',
            'sn': self.sn,
            'message': '设备状态已收到并更新。'
        })

    def _upsert_monitor_snapshot(self, data: dict):
        """
        同步方法：将 status_report data 写入 DeviceMonitorSnapshot（upsert）。
        由 database_sync_to_async 包裹后在异步环境中调用。
        """
        from monitor.models import DeviceMonitorSnapshot

        # 解析协议字段，提供默认值保证健壮性
        healthy = data.get('healthy', True)
        disconnected = data.get('disconnected', False)
        last_time = data.get('lastTime', 0)
        mem_size = data.get('memSize', {})
        abnormality = data.get('abnormality', {})
        

        # update_or_create：以 device_sn 为唯一键执行 upsert
        snapshot, _ = DeviceMonitorSnapshot.objects.update_or_create(
            device_sn=self.sn,
            defaults={
                'healthy': healthy,
                'disconnected': disconnected,
                'last_time': last_time,
                'mem_size': mem_size,
                'abnormality': abnormality,
                'raw_data': data,   # 完整保存原始数据便于排查
            }
        )
        return snapshot

    # ================================================================
    # 下行消息处理方法（由 Channel Layer group_send 触发）
    # ================================================================

    async def device_message(self, event):
        """
        处理通过 Channel Layer 发来的下行消息。
        其他地方（如 views.py / services.py）调用 group_send 时触发此方法。

        event 格式：
        {
            "type": "device.message",  # Channel Layer 路由键（点替换下划线调用此方法）
            "payload": { ... }          # 实际要发给 Java 客户端的 JSON 数据
        }
        """
        payload = event.get('payload', {})
        logger.debug(f'[WS] 下行推送到设备: sn={self.sn}, payload={payload}')
        await self.send_json(payload)

    # ================================================================
    # 工具方法
    # ================================================================

    async def send_json(self, data: dict):
        """将 dict 序列化为 JSON 字符串发送给客户端"""
        await self.send(text_data=json.dumps(data, ensure_ascii=False))
