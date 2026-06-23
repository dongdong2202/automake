"""
monitor/admin.py —— 设备监控快照后台管理
"""

from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import DeviceMonitorSnapshot


@admin.register(DeviceMonitorSnapshot)
class DeviceMonitorSnapshotAdmin(ModelAdmin):
    """
    设备监控快照后台管理

    提供列表展示、筛选与搜索，快照仅由系统自动写入，
    后台管理界面设为只读（禁止手动新增/修改/删除）。
    """
    list_display = (
        'device_sn', 'healthy', 'disconnected',
        'display_status_label', 'reported_at'
    )
    list_filter = ('healthy', 'disconnected')
    search_fields = ('device_sn',)
    ordering = ('device_sn',)
    # 所有字段只读，不允许在后台手动改写监控数据
    readonly_fields = (
        'device_sn', 'healthy', 'disconnected', 'last_time',
        'mem_size', 'abnormality', 'raw_data', 'reported_at', 'created_at'
    )

    def has_add_permission(self, request):
        """禁止后台手动新增，快照由设备上报自动写入"""
        return False

    def has_change_permission(self, request, obj=None):
        """监控数据只读，不允许修改"""
        return False

    def has_delete_permission(self, request, obj=None):
        """允许超级管理员删除过期快照"""
        return request.user.is_superuser

    @admin.display(description='展示状态')
    def display_status_label(self, obj):
        """将 display_status 转换为可读标签"""
        labels = {
            'normal': '✅ 正常',
            'warning': '⚠️ 警告',
            'fault': '🔴 故障',
        }
        return labels.get(obj.display_status, obj.display_status)
