"""
monitor/routing.py —— 监控大屏 WebSocket URL 路由

路径：ws://<host>/ws/monitor/
连接后实时接收所有设备的状态推送，用于监控大屏展示。
"""

from django.urls import re_path
from .consumers import MonitorConsumer

websocket_urlpatterns = [
    # 监控大屏 WebSocket 端点（无需参数，订阅所有设备广播）
    re_path(r'^ws/monitor/$', MonitorConsumer.as_asgi()),
]
