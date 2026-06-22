"""
Django 项目初始化文件

在此处引入 Celery 应用，确保在 Django 启动时自动加载 Celery，
使得 @shared_task 装饰器能够正确工作。
"""

from .celery import app as celery_app

__all__ = ('celery_app',)
