from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline
from .models import (
    DeviceType, GlobalMaterial, GlobalMenuCategory, GlobalMenuItem,
    GlobalMenuSku, GlobalSkuIngredient, GlobalConsumable
)


class GlobalSkuIngredientInline(TabularInline):
    """
    全局规格配料内联管理
    """
    model = GlobalSkuIngredient
    extra = 1


class GlobalMenuSkuInline(TabularInline):
    """
    全局商品规格内联管理
    """
    model = GlobalMenuSku
    extra = 1
    show_change_link = True


class GlobalConfigAdmin(ModelAdmin):
    """
    全局配置基类，禁止门店管理员查看
    """
    def has_module_permission(self, request):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            return False
        return super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            return False
        return super().has_view_permission(request, obj)


@admin.register(DeviceType)
class DeviceTypeAdmin(GlobalConfigAdmin):
    """
    设备类型后台管理
    """
    list_display = ('id', 'name', 'code', 'description', 'created_at')
    search_fields = ('name', 'code')
    ordering = ('id',)

    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'code', 'description')
        }),
    )


@admin.register(GlobalMaterial)
class GlobalMaterialAdmin(GlobalConfigAdmin):
    """
    全局物料定义后台管理
    """
    list_display = ('id', 'name', 'code', 'unit', 'initHight', 'deviceVersion', 'deviceSN', 'description', 'created_at')
    search_fields = ('name', 'code', 'deviceSN')
    ordering = ('id',)

    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'code', 'unit', 'initHight', 'deviceVersion', 'deviceSN', 'description')
        }),
    )


@admin.register(GlobalConsumable)
class GlobalConsumableAdmin(GlobalConfigAdmin):
    """
    全局包装耗材后台管理
    """
    list_display = ('id', 'name', 'code', 'initQuantity', 'deviceSN', 'description', 'created_at')
    search_fields = ('name', 'code', 'deviceSN')
    ordering = ('id',)

    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'code', 'initQuantity', 'deviceSN', 'description')
        }),
    )


@admin.register(GlobalMenuCategory)
class GlobalMenuCategoryAdmin(GlobalConfigAdmin):
    """
    全局菜单分类后台管理
    """
    list_display = ('id', 'name', 'device_type', 'sort_order', 'is_active', 'created_at')
    list_filter = ('is_active', 'device_type')
    search_fields = ('name',)
    ordering = ('sort_order', 'id')

    fieldsets = (
        ('基本信息', {
            'fields': ('device_type', 'name', 'icon_url')
        }),
        ('状态与排序', {
            'fields': ('is_active', 'sort_order')
        }),
    )


@admin.register(GlobalMenuItem)
class GlobalMenuItemAdmin(GlobalConfigAdmin):
    """
    全局菜单商品后台管理
    """
    list_display = ('id', 'name', 'category', 'base_price', 'main_ingredients', 'is_active', 'sort_order')
    list_filter = ('is_active', 'category')
    search_fields = ('name', 'description', 'main_ingredients')
    ordering = ('category', 'sort_order', 'id')
    inlines = [GlobalMenuSkuInline]

    fieldsets = (
        ('基本信息', {
            'fields': ('category', 'name', 'description', 'image_url')
        }),
        ('详情展示与配置', {
            'fields': ('main_ingredients', 'price_description', 'detail_page')
        }),
        ('价格信息', {
            'fields': ('base_price',)
        }),
        ('状态与排序', {
            'fields': ('is_active', 'sort_order')
        }),
    )


@admin.register(GlobalMenuSku)
class GlobalMenuSkuAdmin(GlobalConfigAdmin):
    """
    全局商品规格后台管理
    """
    list_display = ('id', 'name', 'category', 'item', 'price_delta', 'is_active', 'sort_order')
    list_filter = ('is_active', 'category', 'item__category')
    search_fields = ('name', 'category', 'item__name')
    ordering = ('item', 'sort_order', 'id')
    inlines = [GlobalSkuIngredientInline]

    fieldsets = (
        ('基本属性', {
            'fields': ('item', 'name', 'category')
        }),
        ('价格与状态', {
            'fields': ('price_delta', 'is_active', 'sort_order')
        }),
    )
