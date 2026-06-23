"""
monitor/consumers.py —— 监控大屏 WebSocket 消费者

路径：ws://<host>/ws/monitor/

前端监控大屏连接此端点后，即可实时接收所有设备的状态推送。
每当设备上报 status_report，ws_device/consumers.py 会向
Channel Group "monitor_dashboard" 广播，此 Consumer 将消息
转发给所有连接的浏览器客户端。

推送消息格式：
{
    "type": "device_status",
    "device_sn": "SN001",
    "display_status": "normal" | "warning" | "fault",
    "healthy": true,
    "disconnected": false,
    "last_time": 0,
    "mem_size": {...},
    "abnormality": {...},
    "reported_at": "2024-01-01T00:00:00Z"
}
"""

import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger('monitor')

# 所有监控大屏客户端共用的 Channel Group 名称
MONITOR_GROUP = 'monitor_dashboard'


class MonitorConsumer(AsyncWebsocketConsumer):
    """
    监控大屏 WebSocket 消费者

    浏览器前端连接后，加入 monitor_dashboard 组，
    接收由 ws_device/consumers.py 广播的实时设备状态更新。
    """

    async def connect(self):
        """握手建立时加入监控大屏组"""
        # 将此连接加入监控大屏广播组
        await self.channel_layer.group_add(MONITOR_GROUP, self.channel_name)
        await self.accept()
        logger.info(f'[Monitor] 监控大屏客户端已连接: channel={self.channel_name}')

    async def disconnect(self, close_code):
        """断开时从广播组移除"""
        await self.channel_layer.group_discard(MONITOR_GROUP, self.channel_name)
        logger.info(f'[Monitor] 监控大屏客户端已断开: channel={self.channel_name}, code={close_code}')

    async def receive(self, text_data):
        """
        监控大屏为纯下行推送，客户端无需发送消息。
        收到消息时忽略（也可扩展为接受"订阅特定设备"指令）。
        """
        pass

    async def monitor_device_status(self, event):
        """
        接收来自 Channel Layer group_send 的设备状态事件，
        并转发给浏览器客户端。

        event 格式：
        {
            "type": "monitor.device_status",   # Channel Layer 路由键
            "payload": { ... }                 # 实际推送给前端的 JSON 数据
        }
        """
        payload = event.get('payload', {})
        logger.debug(f'[Monitor] 推送设备状态到监控大屏: sn={payload.get("device_sn")}')
        await self.send(text_data=json.dumps(payload, ensure_ascii=False))
