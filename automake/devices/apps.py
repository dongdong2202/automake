import os
import sys
import threading
from django.apps import AppConfig


class DevicesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'devices'

    def ready(self):
        # 避免在管理命令（如 migrate, makemigrations, test, collectstatic, shell 等）中启动 MQTT 客户端
        skip_commands = {'migrate', 'makemigrations', 'test', 'collectstatic', 'shell', 'showmigrations', 'check'}
        if not any(arg in skip_commands for arg in sys.argv):
            # 同样避免在 Django runserver 自动重载的主进程中重复连接，只在子工作进程或禁用重载时启动
            if os.environ.get('RUN_MAIN') == 'true' or '--noreload' in sys.argv or not any('runserver' in arg for arg in sys.argv):
                from mqtt import get_mqtt_client
                # 异步启动连接，防止阻塞 Django Web 服务的初始化/加载
                threading.Thread(target=get_mqtt_client, daemon=True).start()

