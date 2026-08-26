"""
ASGI 配置 —— 支持 HTTP 和 WebSocket 双协议

使用 django-channels 的 ProtocolTypeRouter 将请求按协议分发：
  - HTTP 请求  → Django 标准 ASGI 应用（views/APIs）
  - WebSocket  → channels URLRouter（路由到对应 Consumer）

启动方式（开发）：
  daphne -b 0.0.0.0 -p 8000 default.asgi:application

生产部署建议：
  通过 nginx 反向代理，将 ws:// 路径转发到 Daphne 或 uvicorn 进程。
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')

# 必须在 django setup 完成后再导入 channels 相关模块
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator

from monitor.routing import websocket_urlpatterns as monitor_ws_patterns

application = ProtocolTypeRouter({
    # HTTP 请求走标准 Django ASGI 应用
    'http': django_asgi_app,

    # WebSocket 请求：
    #   AllowedHostsOriginValidator —— 校验 Origin，防止跨域 WebSocket 请求（生产必须启用）
    #   AuthMiddlewareStack        —— 支持 Django Session 认证（如需 Token 认证可替换）
    #   URLRouter                  —— 按 URL 路径分发到对应 Consumer
    'websocket': AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(monitor_ws_patterns)
        )
    ),
})

