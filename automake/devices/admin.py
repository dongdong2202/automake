from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from .models import Device, DeviceCommand, DeviceStatusLog, DeviceAlarm, DeviceMaterialStock, DeviceConsumableStock, DeviceConfig, DeviceTemperature, DeviceBarrel, DeviceSoftConf, DeviceCupSize


# ── 状态颜色映射 ──────────────────────────────────────────
DEVICE_STATUS_BADGE = {
    'online':  ('#10b981', '#ecfdf5', '🟢 在线'),
    'offline': ('#6b7280', '#f9fafb', '⚫ 离线'),
    'fault':   ('#ef4444', '#fef2f2', '🔴 故障'),
    'idle':    ('#f59e0b', '#fffbeb', '🟡 空闲'),
}

COMMAND_STATUS_BADGE = {
    'pending':   ('#f59e0b', '#fffbeb', '⏳ 待下发'),
    'sent':      ('#3b82f6', '#eff6ff', '📤 已下发'),
    'confirmed': ('#10b981', '#ecfdf5', '✅ 已确认'),
    'failed':    ('#ef4444', '#fef2f2', '❌ 失败'),
    'timeout':   ('#f97316', '#fff7ed', '⏰ 超时'),
}

ALARM_RESOLVED_BADGE = {
    True:  ('#10b981', '#ecfdf5', '✅ 已处理'),
    False: ('#ef4444', '#fef2f2', '🚨 未处理'),
}


def _badge(color, bg, label):
    return format_html(
        '<span style="display:inline-block;padding:3px 10px;border-radius:20px;'
        'font-size:12px;font-weight:600;color:{};background:{};white-space:nowrap;">'
        '{}</span>',
        color, bg, label
    )

class ReadOnlyStoreScopedDeviceAdmin(ModelAdmin):
    """
    设备相关数据的只读、门店过滤后台管理基类
    """
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            user_stores = request.user.stores.all()
            if user_stores.exists():
                if hasattr(self.model, 'store'):
                    return qs.filter(store__in=user_stores)
                elif hasattr(self.model, 'device'):
                    return qs.filter(device__store__in=user_stores)
            return qs.none()
        return qs

    def has_view_permission(self, request, obj=None):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            if obj is not None:
                user_store_ids = list(request.user.stores.values_list('id', flat=True))
                if hasattr(obj, 'store') and obj.store_id:
                    if obj.store_id not in user_store_ids:
                        return False
                elif hasattr(obj, 'device') and obj.device_id and obj.device.store_id:
                    if obj.device.store_id not in user_store_ids:
                        return False
            return True
        return super().has_view_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            return False
        return super().has_change_permission(request, obj)

    def has_add_permission(self, request):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            return False
        return super().has_delete_permission(request, obj)

    def has_module_permission(self, request):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            return True
        return super().has_module_permission(request)


@admin.register(Device)
class DeviceAdmin(ReadOnlyStoreScopedDeviceAdmin):
    list_display = (
        'device_sn', 'device_name', 'store', 'device_model',
        'status_badge', 'firmware_version', 'last_heartbeat_at'
    )
    search_fields = ('device_sn', 'device_name', 'key_code')
    list_filter = ('status', 'store', 'device_model')
    readonly_fields = ('last_heartbeat_at', 'created_at', 'updated_at')

    @admin.display(description='在线状态')
    def status_badge(self, obj):
        color, bg, label = DEVICE_STATUS_BADGE.get(
            obj.status, ('#6b7280', '#f9fafb', obj.status)
        )
        return _badge(color, bg, label)

    # 使用 fieldsets 分组呈现，更具友好性
    fieldsets = (
        ('设备基本属性', {
            'fields': ('device_sn', 'device_name', 'device_model', 'store', 'status', 'key_code')
        }),
        ('固件与通信配置', {
            'fields': ('firmware_version', 'resource_version', 'mqtt_topic_prefix', 'extra_config')
        }),
        ('状态更新时间', {
            'fields': ('last_heartbeat_at', 'created_at', 'updated_at')
        }),
    )


@admin.register(DeviceCommand)
class DeviceCommandAdmin(ReadOnlyStoreScopedDeviceAdmin):
    list_display = ('id', 'device', 'command_type', 'status_badge', 'sent_at', 'confirmed_at')
    search_fields = ('device__device_sn', 'command_type')
    list_filter = ('command_type', 'status')
    readonly_fields = ('device', 'order', 'command_type', 'payload', 'status', 'sent_at', 'confirmed_at', 'created_at')

    @admin.display(description='指令状态')
    def status_badge(self, obj):
        color, bg, label = COMMAND_STATUS_BADGE.get(
            obj.status, ('#6b7280', '#f9fafb', obj.status)
        )
        return _badge(color, bg, label)


@admin.register(DeviceStatusLog)
class DeviceStatusLogAdmin(ReadOnlyStoreScopedDeviceAdmin):
    list_display = ('id', 'device', 'status', 'remark', 'created_at')
    search_fields = ('device__device_sn', 'status', 'remark')
    list_filter = ('status',)
    readonly_fields = ('device', 'status', 'remark', 'raw_payload', 'created_at')


@admin.register(DeviceAlarm)
class DeviceAlarmAdmin(ReadOnlyStoreScopedDeviceAdmin):
    list_display = ('id', 'device', 'alarm_type', 'resolved_badge', 'resolved_at', 'created_at')
    search_fields = ('device__device_sn', 'alarm_type', 'detail')
    list_filter = ('alarm_type', 'is_resolved')
    readonly_fields = ('device', 'alarm_type', 'detail', 'created_at', 'resolved_at')

    @admin.display(description='处理状态')
    def resolved_badge(self, obj):
        color, bg, label = ALARM_RESOLVED_BADGE.get(
            obj.is_resolved, ('#6b7280', '#f9fafb', str(obj.is_resolved))
        )
        return _badge(color, bg, label)


@admin.register(DeviceMaterialStock)
class DeviceMaterialStockAdmin(ModelAdmin):
    list_display = ('id', 'device', 'name', 'code', 'unit', 'initHight', 'warn_level', 'warn_level_1', 'warn_level_2', 'warn_level_3', 'current_remaining_height', 'updated_at')
    search_fields = ('device__device_sn', 'name__name', 'code')
    list_filter = ('device', 'code')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            user_stores = request.user.stores.all()
            if user_stores.exists():
                return qs.filter(device__store__in=user_stores)
            return qs.none()
        return qs

    def has_view_permission(self, request, obj=None):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            if obj is not None:
                user_store_ids = list(request.user.stores.values_list('id', flat=True))
                if obj.device_id and obj.device.store_id:
                    if obj.device.store_id not in user_store_ids:
                        return False
            return True
        return super().has_view_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            if obj is not None:
                user_store_ids = list(request.user.stores.values_list('id', flat=True))
                if obj.device_id and obj.device.store_id:
                    if obj.device.store_id not in user_store_ids:
                        return False
            return True
        return super().has_change_permission(request, obj)

    def has_add_permission(self, request):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            return True
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            if obj is not None:
                user_store_ids = list(request.user.stores.values_list('id', flat=True))
                if obj.device_id and obj.device.store_id:
                    if obj.device.store_id not in user_store_ids:
                        return False
            return True
        return super().has_delete_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ('device', 'name', 'code', 'unit', 'created_at', 'updated_at')
        return ('created_at', 'updated_at')

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "device" and request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            user_stores = request.user.stores.all()
            if user_stores.exists():
                kwargs["queryset"] = Device.objects.filter(store__in=user_stores)
            else:
                kwargs["queryset"] = Device.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(DeviceConsumableStock)
class DeviceConsumableStockAdmin(ModelAdmin):
    list_display = ('id', 'device', 'code', 'unit', 'init_quantity', 'quantity', 'warn_level', 'updated_at')
    search_fields = ('device__device_sn', 'code__name', 'code__code')
    list_filter = ('device', 'code')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            user_stores = request.user.stores.all()
            if user_stores.exists():
                return qs.filter(device__store__in=user_stores)
            return qs.none()
        return qs

    def has_view_permission(self, request, obj=None):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            if obj is not None:
                user_store_ids = list(request.user.stores.values_list('id', flat=True))
                if obj.device_id and obj.device.store_id:
                    if obj.device.store_id not in user_store_ids:
                        return False
            return True
        return super().has_view_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            if obj is not None:
                user_store_ids = list(request.user.stores.values_list('id', flat=True))
                if obj.device_id and obj.device.store_id:
                    if obj.device.store_id not in user_store_ids:
                        return False
            return True
        return super().has_change_permission(request, obj)

    def has_add_permission(self, request):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            return True
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            if obj is not None:
                user_store_ids = list(request.user.stores.values_list('id', flat=True))
                if obj.device_id and obj.device.store_id:
                    if obj.device.store_id not in user_store_ids:
                        return False
            return True
        return super().has_delete_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ('device', 'code', 'unit', 'created_at', 'updated_at')
        return ('created_at', 'updated_at')

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "device" and request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            user_stores = request.user.stores.all()
            if user_stores.exists():
                kwargs["queryset"] = Device.objects.filter(store__in=user_stores)
            else:
                kwargs["queryset"] = Device.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

class DeviceTemperatureInline(TabularInline):
    model = DeviceTemperature
    extra = 1
    fields = ('key', 'value')

class DeviceBarrelInline(TabularInline):
    model = DeviceBarrel
    extra = 1
    fields = ('barrel_id', 'pump_type', 'pump_coeff', 'max_v', 'base_area')

@admin.register(DeviceConfig)
class DeviceConfigAdmin(ModelAdmin):
    list_display = ('id', 'device')
    search_fields = ('device__device_sn',)
    list_filter = ('device',)
    inlines = [DeviceTemperatureInline, DeviceBarrelInline]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            user_stores = request.user.stores.all()
            if user_stores.exists():
                return qs.filter(device__store__in=user_stores)
            return qs.none()
        return qs

    def has_view_permission(self, request, obj=None):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            if obj is not None:
                user_store_ids = list(request.user.stores.values_list('id', flat=True))
                if obj.device_id and obj.device.store_id:
                    if obj.device.store_id not in user_store_ids:
                        return False
            return True
        return super().has_view_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            if obj is not None:
                user_store_ids = list(request.user.stores.values_list('id', flat=True))
                if obj.device_id and obj.device.store_id:
                    if obj.device.store_id not in user_store_ids:
                        return False
            return True
        return super().has_change_permission(request, obj)

    def has_add_permission(self, request):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            return True
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            if obj is not None:
                user_store_ids = list(request.user.stores.values_list('id', flat=True))
                if obj.device_id and obj.device.store_id:
                    if obj.device.store_id not in user_store_ids:
                        return False
            return True
        return super().has_delete_permission(request, obj)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "device" and request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            user_stores = request.user.stores.all()
            if user_stores.exists():
                kwargs["queryset"] = Device.objects.filter(store__in=user_stores)
            else:
                kwargs["queryset"] = Device.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

class DeviceCupSizeInline(TabularInline):
    model = DeviceCupSize
    extra = 1
    fields = ('key', 'capacity')

@admin.register(DeviceSoftConf)
class DeviceSoftConfAdmin(ModelAdmin):
    list_display = ('id', 'device', 'max_vacancies', 'sep_chunk', 'ice_size')
    search_fields = ('device__device_sn',)
    list_filter = ('device',)
    inlines = [DeviceCupSizeInline]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            user_stores = request.user.stores.all()
            if user_stores.exists():
                return qs.filter(device__store__in=user_stores)
            return qs.none()
        return qs

    def has_view_permission(self, request, obj=None):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            if obj is not None:
                user_store_ids = list(request.user.stores.values_list('id', flat=True))
                if obj.device_id and obj.device.store_id:
                    if obj.device.store_id not in user_store_ids:
                        return False
            return True
        return super().has_view_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            if obj is not None:
                user_store_ids = list(request.user.stores.values_list('id', flat=True))
                if obj.device_id and obj.device.store_id:
                    if obj.device.store_id not in user_store_ids:
                        return False
            return True
        return super().has_change_permission(request, obj)

    def has_add_permission(self, request):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            return True
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            if obj is not None:
                user_store_ids = list(request.user.stores.values_list('id', flat=True))
                if obj.device_id and obj.device.store_id:
                    if obj.device.store_id not in user_store_ids:
                        return False
            return True
        return super().has_delete_permission(request, obj)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "device" and request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            user_stores = request.user.stores.all()
            if user_stores.exists():
                kwargs["queryset"] = Device.objects.filter(store__in=user_stores)
            else:
                kwargs["queryset"] = Device.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
