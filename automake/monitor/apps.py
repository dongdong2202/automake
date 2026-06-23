"""
monitor/apps.py —— 监控模块 App 配置
"""

from django.apps import AppConfig


class MonitorConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'monitor'
    verbose_name = '监控与分析'
