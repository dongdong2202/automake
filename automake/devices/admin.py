from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from unfold.admin import ModelAdmin, TabularInline
from unfold.widgets import UnfoldAdminFileFieldWidget
from django.db import models
from .models import Device, DeviceCommand, DeviceStatusLog, DeviceAlarm, DeviceMaterialStock, DeviceConsumableStock, DeviceConfig, DeviceTemperature, DeviceBarrel, DeviceSoftConf, DeviceCupSize, DeviceBarrelDict, DevicePoster, DeviceConf1


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
        'province', 'city',
        'status_badge', 'firmware_version', 'last_heartbeat_at'
    )
    search_fields = ('device_sn', 'device_name', 'key_code', 'province', 'city', 'address')
    list_filter = ('province', 'city', 'status', 'store', 'device_model')
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
            'fields': ('device_sn', 'device_name', 'device_model', 'store', 'status', 'key_code', 'province', 'city', 'address', 'gps_coordinate')
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
    list_display = ('id', 'device', 'code', 'unit', 'init_quantity', 'quantity', 'warn_level', 'stop_sale_level', 'updated_at')
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


@admin.register(DeviceBarrelDict)
class DeviceBarrelDictAdmin(ModelAdmin):
    """
    料桶字典后台管理
    """
    list_display = ('device', 'barrel_code', 'material', 'alarm_threshold_1', 'alarm_threshold_2', 'created_by', 'created_at')
    search_fields = ('device__device_sn', 'device__device_name', 'barrel_code', 'material__code', 'material__name')
    list_filter = ('device', 'created_at')
    readonly_fields = ('created_at', 'created_by')

    fieldsets = (
        ('基础映射与阈值', {
            'fields': ('device', 'barrel_code', 'material', 'alarm_threshold_1', 'alarm_threshold_2')
        }),
        ('审计信息', {
            'fields': ('created_by', 'created_at')
        }),
    )

    def save_model(self, request, obj, form, change):
        if not obj.pk and not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(DevicePoster)
class DevicePosterAdmin(ModelAdmin):
    """
    设备海报后台管理 (支持Web上传横屏/竖屏/Banner 3个图片，以及多选适用门店与设备)
    """
    formfield_overrides = {
        models.ImageField: {'widget': UnfoldAdminFileFieldWidget},
    }
    list_display = ('title', 'version', 'preview_images', 'store_scope', 'device_scope', 'remarks', 'sort_order', 'is_active', 'created_at')
    search_fields = ('title', 'version', 'remarks', 'stores__name', 'devices__device_sn')
    list_filter = ('is_active', 'created_at')
    filter_horizontal = ('stores', 'devices')
    readonly_fields = ('horizontal_preview', 'vertical_preview', 'banner_preview', 'created_at', 'updated_at')

    fieldsets = (
        ('基本配置', {
            'fields': ('title', 'version', 'remarks', 'sort_order', 'is_active')
        }),
        ('海报图片上传 (3个独立上传项)', {
            'fields': (
                ('horizontal_image', 'horizontal_preview'),
                ('vertical_image', 'vertical_preview'),
                ('banner_image', 'banner_preview')
            )
        }),
        ('适用范围 (门店与设备多选)', {
            'fields': ('stores', 'devices'),
            'description': '留空则表示对全系统所有门店与设备全局生效。'
        }),
        ('审计信息', {
            'fields': ('created_at', 'updated_at')
        }),
    )

    def _safe_image_url(self, image_field):
        try:
            if image_field and hasattr(image_field, 'url') and image_field.name:
                return image_field.url
        except Exception:
            return None
        return None

    @admin.display(description='图片缩略图 (横/竖/Banner)')
    def preview_images(self, obj):
        if not obj:
            return "未上传"
        htmls = []
        h_url = self._safe_image_url(getattr(obj, 'horizontal_image', None))
        if h_url:
            htmls.append(format_html('<a href="{0}" target="_blank"><img src="{0}" title="横屏海报" style="height:38px;width:56px;object-fit:cover;border-radius:4px;margin-right:6px;border:1px solid #e5e7eb;vertical-align:middle;" /></a>', h_url))
        v_url = self._safe_image_url(getattr(obj, 'vertical_image', None))
        if v_url:
            htmls.append(format_html('<a href="{0}" target="_blank"><img src="{0}" title="竖屏海报" style="height:38px;width:26px;object-fit:cover;border-radius:4px;margin-right:6px;border:1px solid #e5e7eb;vertical-align:middle;" /></a>', v_url))
        b_url = self._safe_image_url(getattr(obj, 'banner_image', None))
        if b_url:
            htmls.append(format_html('<a href="{0}" target="_blank"><img src="{0}" title="Banner横幅" style="height:38px;width:70px;object-fit:cover;border-radius:4px;border:1px solid #e5e7eb;vertical-align:middle;" /></a>', b_url))
        if not htmls:
            return mark_safe('<span style="color:#9ca3af; font-size:12px;">未上传图片</span>')
        return mark_safe("".join(htmls))

    @admin.display(description='横屏预览')
    def horizontal_preview(self, obj):
        if not obj:
            return mark_safe('<span style="color:#9ca3af; font-size:12px;">暂无图片</span>')
        url = self._safe_image_url(getattr(obj, 'horizontal_image', None))
        if url:
            return format_html(
                '<a href="{0}" target="_blank"><img src="{0}" style="max-height: 100px; max-width: 180px; border-radius: 6px; object-fit: contain; border: 1px solid #d1d5db; padding: 2px; background: #fff;" /></a>',
                url
            )
        return mark_safe('<span style="color:#9ca3af; font-size:12px;">暂无图片</span>')

    @admin.display(description='竖屏预览')
    def vertical_preview(self, obj):
        if not obj:
            return mark_safe('<span style="color:#9ca3af; font-size:12px;">暂无图片</span>')
        url = self._safe_image_url(getattr(obj, 'vertical_image', None))
        if url:
            return format_html(
                '<a href="{0}" target="_blank"><img src="{0}" style="max-height: 100px; max-width: 100px; border-radius: 6px; object-fit: contain; border: 1px solid #d1d5db; padding: 2px; background: #fff;" /></a>',
                url
            )
        return mark_safe('<span style="color:#9ca3af; font-size:12px;">暂无图片</span>')

    @admin.display(description='Banner预览')
    def banner_preview(self, obj):
        if not obj:
            return mark_safe('<span style="color:#9ca3af; font-size:12px;">暂无图片</span>')
        url = self._safe_image_url(getattr(obj, 'banner_image', None))
        if url:
            return format_html(
                '<a href="{0}" target="_blank"><img src="{0}" style="max-height: 100px; max-width: 220px; border-radius: 6px; object-fit: contain; border: 1px solid #d1d5db; padding: 2px; background: #fff;" /></a>',
                url
            )
        return mark_safe('<span style="color:#9ca3af; font-size:12px;">暂无图片</span>')

    @admin.display(description='适用门店')
    def store_scope(self, obj):
        if not obj.pk:
            return "-"
        names = list(obj.stores.values_list('name', flat=True)[:3])
        count = obj.stores.count()
        if count == 0:
            return format_html('<span style="color:#10b981;">{}</span>', '全部门店 (全局)')
        label = "、".join(names)
        if count > 3:
            label += f" 等 {count} 家"
        return label

    @admin.display(description='适用设备')
    def device_scope(self, obj):
        if not obj.pk:
            return "-"
        sns = list(obj.devices.values_list('device_sn', flat=True)[:3])
        count = obj.devices.count()
        if count == 0:
            return format_html('<span style="color:#6b7280;">{}</span>', '全部设备 (通用)')
        label = "、".join(sns)
        if count > 3:
            label += f" 等 {count} 台"
        return label


@admin.register(DeviceConf1)
class DeviceConf1Admin(ModelAdmin):
    list_display = ('id', 'device_sn', 'version', 'config_summary', 'created_at', 'updated_at')
    search_fields = ('device_sn', 'version')
    list_filter = ('version', 'created_at')
    readonly_fields = ('created_at', 'updated_at')

    @admin.display(description='配置内容摘要')
    def config_summary(self, obj):
        import json
        text = json.dumps(obj.config, ensure_ascii=False)
        return (text[:80] + '...') if len(text) > 80 else text

