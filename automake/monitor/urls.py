"""
monitor/urls.py —— 监控模块 HTTP URL 路由
"""

from django.urls import path
from .views import DeviceMonitorListView, DeviceMonitorDetailView

urlpatterns = [
    # 所有设备监控快照列表
    path('devices/', DeviceMonitorListView.as_view(), name='monitor-device-list'),
    # 指定设备监控快照详情（按序列号查询）
    path('devices/<str:sn>/', DeviceMonitorDetailView.as_view(), name='monitor-device-detail'),
]
