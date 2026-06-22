"""
Celery 异步任务队列配置文件

此文件初始化 Celery 实例，并与 Django 的 settings.py 关联。
"""

import os
from celery import Celery

# 设置 Django 默认配置模块，使 Celery 可以直接访问 Django ORM 和设置
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')

# 创建 Celery 实例，命名为 'default'（与主项目包名一致）
app = Celery('default')

# 使用字符串配置 Celery，这样 worker 进程在启动时不需要序列化整个配置对象。
# namespace='CELERY' 意味着所有 Celery 相关的配置必须以 'CELERY_' 开头。
app.config_from_object('django.conf:settings', namespace='CELERY')

# 自动发现注册在 INSTALLED_APPS 中的所有 Django App 内的 tasks.py 任务文件
app.autodiscover_tasks()

@app.task(bind=True)
def debug_task(self):
    """
    调试任务，用于测试 Celery 队列是否正常工作
    """
    print(f'Request: {self.request!r}')
