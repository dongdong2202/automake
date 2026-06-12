from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline
from .models import MenuItem, MenuSku


class MenuSkuInline(TabularInline):
    """
    门店 SKU 内联管理
    """
    model = MenuSku
    extra = 0
    readonly_fields = ('global_sku',)
    fields = ('global_sku', 'price_delta', 'is_active', 'sort_order')

    def has_add_permission(self, request, obj=None):
        """禁止在此处手动添加 SKU，SKU 必须自全局菜单规格同步"""
        return False

    def has_delete_permission(self, request, obj=None):
        """禁止在此处手动删除 SKU"""
        return False


@admin.register(MenuItem)
class MenuItemAdmin(ModelAdmin):
    """
    门店菜单商品后台管理
    仅允许对已通过设备类型同步继承的商品执行修改（如价格微调、上下架状态）或删减，禁止手动新增。
    """
    list_display = ('id', 'store', 'device_type', 'global_item', 'base_price', 'is_active', 'sort_order')
    list_filter = ('is_active', 'store', 'device_type')
    search_fields = ('global_item__name',)
    ordering = ('store', 'sort_order', 'id')
    readonly_fields = ('store', 'device_type', 'global_item')
    inlines = [MenuSkuInline]

    fieldsets = (
        ('商品绑定与匹配', {
            'fields': ('store', 'device_type', 'global_item')
        }),
        ('价格与上架状态', {
            'fields': ('base_price', 'is_active', 'sort_order')
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            if request.user.store:
                return qs.filter(store=request.user.store)
            return qs.none()
        return qs

    def has_add_permission(self, request):
        """禁止手动新增，必须从全局继承同步"""
        return False

    def has_view_permission(self, request, obj=None):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            if obj is not None and obj.store != request.user.store:
                return False
            return True
        return super().has_view_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            if obj is not None and obj.store != request.user.store:
                return False
            return True
        return super().has_change_permission(request, obj)

    def has_module_permission(self, request):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            return True
        return super().has_module_permission(request)

    def changelist_view(self, request, extra_context=None):
        # 门店管理员打开商品列表时，自动基于该店物理设备类型拉取/更新菜单和规格
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            if request.user.store:
                self.model.sync_store_menu(request.user.store)
        return super().changelist_view(request, extra_context)


@admin.register(MenuSku)
class MenuSkuAdmin(ModelAdmin):
    """
    门店规格/SKU 后台管理
    """
    list_display = ('id', 'item', 'global_sku', 'price_delta', 'is_active', 'sort_order')
    list_filter = ('is_active', 'item__store')
    search_fields = ('global_sku__name', 'item__global_item__name')
    readonly_fields = ('item', 'global_sku')
    fields = ('item', 'global_sku', 'price_delta', 'is_active', 'sort_order')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            if request.user.store:
                return qs.filter(item__store=request.user.store)
            return qs.none()
        return qs

    def has_add_permission(self, request):
        """禁止手动新增，必须从全局继承同步"""
        return False

    def has_delete_permission(self, request, obj=None):
        """禁止手动删除"""
        return False

    def has_view_permission(self, request, obj=None):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            if obj is not None and obj.item.store != request.user.store:
                return False
            return True
        return super().has_view_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            if obj is not None and obj.item.store != request.user.store:
                return False
            return True
        return super().has_change_permission(request, obj)

    def has_module_permission(self, request):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            return True
        return super().has_module_permission(request)
