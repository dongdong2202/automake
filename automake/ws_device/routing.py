"""
ws_device routing.py —— WebSocket URL 路由配置

将 WebSocket 连接按路径分发到对应的 Consumer。
路径格式：ws://<host>/ws/device/<sn>/
  <sn> 为设备编号（device serial number），必须与数据库中的设备记录一致。
"""

from django.urls import re_path

from . import consumers

# WebSocket 路由列表（由 asgi.py 的 URLRouter 使用）
websocket_urlpatterns = [
    # 上位机设备专用 WebSocket 连接端点
    # sn：设备序列号，仅允许字母、数字、下划线、连字符
    re_path(r'^ws/device/(?P<sn>[\w\-]+)/$', consumers.DeviceConsumer.as_asgi()),
]
