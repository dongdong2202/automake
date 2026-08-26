from django.db import models
from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import Store
from .widgets import BusinessHoursWidget

@admin.register(Store)
class StoreAdmin(ModelAdmin):
    list_display = ('id', 'name', 'code', 'status', 'created_at', 'updated_at')
    search_fields = ('name', 'code')
    list_filter = ('status',)
    actions = ['sync_global_menu']

    formfield_overrides = {
        models.JSONField: {'widget': BusinessHoursWidget},
    }

    # 字段分区（Fieldsets），使表单结构更加清晰易用
    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'code', 'description', 'status', 'cover_image')
        }),
        ('地理位置与联系方式', {
            'fields': ('address', 'lat', 'lng', 'contact_phone')
        }),
        ('营业时间与排序', {
            'fields': ('business_hours', 'sort_order'),
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            if request.user.store:
                return qs.filter(id=request.user.store.id)
            return qs.none()
        return qs

    def has_view_permission(self, request, obj=None):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            if obj is not None and obj.id != request.user.store.id:
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

    @admin.action(description='继承/同步全局菜单到所选门店')
    def sync_global_menu(self, request, queryset):
        from menus.models import MenuItem
        
        synced_stores = []
        for store in queryset:
            MenuItem.sync_store_menu(store)
            synced_stores.append(store.name)
        
        self.message_user(request, f"成功同步全局菜单到以下门店: {', '.join(synced_stores)}")
