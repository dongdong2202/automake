"""
ws_device 应用配置
负责上位机（Java WebSocket 客户端）与 Django 服务端的实时双向通信
"""

from django.apps import AppConfig


class WsDeviceConfig(AppConfig):
    """ws_device 应用配置类"""
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ws_device'
    verbose_name = '上位机 WebSocket 通信'
