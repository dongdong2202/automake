from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import Device, DeviceCommand, DeviceStatusLog, DeviceAlarm, DeviceMaterialStock, DeviceConsumableStock


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
    list_display = ('id', 'device_sn', 'device_name', 'store', 'device_model', 'status', 'firmware_version', 'key_code', 'last_heartbeat_at')
    search_fields = ('device_sn', 'device_name', 'key_code')
    list_filter = ('status', 'store', 'device_model')
    readonly_fields = ('last_heartbeat_at', 'created_at', 'updated_at')

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
    list_display = ('id', 'device', 'command_type', 'status', 'sent_at', 'confirmed_at')
    search_fields = ('device__device_sn', 'command_type')
    list_filter = ('command_type', 'status')
    readonly_fields = ('device', 'order', 'command_type', 'payload', 'status', 'sent_at', 'confirmed_at', 'created_at')


@admin.register(DeviceStatusLog)
class DeviceStatusLogAdmin(ReadOnlyStoreScopedDeviceAdmin):
    list_display = ('id', 'device', 'status', 'remark', 'created_at')
    search_fields = ('device__device_sn', 'status', 'remark')
    list_filter = ('status',)
    readonly_fields = ('device', 'status', 'remark', 'raw_payload', 'created_at')


@admin.register(DeviceAlarm)
class DeviceAlarmAdmin(ReadOnlyStoreScopedDeviceAdmin):
    list_display = ('id', 'device', 'alarm_type', 'is_resolved', 'resolved_at', 'created_at')
    search_fields = ('device__device_sn', 'alarm_type', 'detail')
    list_filter = ('alarm_type', 'is_resolved')
    readonly_fields = ('device', 'alarm_type', 'detail', 'created_at', 'resolved_at')


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


