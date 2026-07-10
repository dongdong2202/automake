"""
monitor/admin.py —— 设备监控快照后台管理
"""

from django.contrib import admin
from django.utils.html import format_html
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
        'display_status_label', 'display_abnormality', 'reported_at', 'history_link'
    )
    list_filter = ('healthy', 'disconnected')
    search_fields = ('device_sn',)
    ordering = ('device_sn',)
    # 所有字段只读，不允许在后台手动改写监控数据
    readonly_fields = (
        'device_sn', 'healthy', 'disconnected', 'last_time',
        'mem_size', 'abnormality', 'raw_data', 'reported_at', 'created_at'
    )

    def changelist_view(self, request, extra_context=None):
        if 'show_history' in request.GET:
            request.show_history = True
            get_copy = request.GET.copy()
            del get_copy['show_history']
            request.GET = get_copy
        return super().changelist_view(request, extra_context=extra_context)

    def get_queryset(self, request):
        """默认只显示每个设备的最新状态，点击查看历史才显示所有记录"""
        qs = super().get_queryset(request)
        if getattr(request, 'show_history', False):
            return qs
            
        from django.db.models import Max
        latest_ids = DeviceMonitorSnapshot.objects.values('device_sn').annotate(max_id=Max('id')).values('max_id')
        return qs.filter(id__in=latest_ids)

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

    @admin.display(description='异常详情')
    def display_abnormality(self, obj):
        if obj.healthy:
            return format_html('<span style="color: green;">{}</span>', '无异常')
        if not obj.abnormality:
            return format_html('<span style="color: orange;">{}</span>', '未知异常')
        
        details = []
        for key, val in obj.abnormality.items():
            details.append(f"{key}: {val}")
        return format_html('<span style="color: red;">{}</span>', ", ".join(details))

    @admin.display(description='历史记录')
    def history_link(self, obj):
        # 点击后通过 popup 弹窗展示历史记录，附加 _popup=1 隐藏 admin 左侧菜单和顶部导航
        url = f"?q={obj.device_sn}&show_history=1&_popup=1"
        onclick_js = f"window.open('{url}', 'HistoryPopup', 'width=1000,height=800,resizable=yes,scrollbars=yes'); return false;"
        return format_html('<a href="{}" onclick="{}" style="color: #2196f3; font-weight: bold;">查看历史</a>', url, onclick_js)
