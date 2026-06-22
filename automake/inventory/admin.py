"""
物料库房与进销存管理后台配置
"""

from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline
from .models import Material, InventoryRecord


class InventoryRecordInline(TabularInline):
    """
    在物料详情页展示该物料近期的进出库动态变化（内联表格）
    """
    model = InventoryRecord
    extra = 1  # 默认提供一个空白行供快速录入
    fields = ('record_type', 'quantity', 'store', 'expiration_date', 'remarks', 'created_at', 'operator')
    readonly_fields = ('created_at', 'operator')
    ordering = ('-created_at',)
    
    # 限制内联表格只能查看和添加，不能修改历史记录以保证账目真实性
    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Material)
class MaterialAdmin(ModelAdmin):
    """
    物料信息管理后台
    """
    list_display = (
        'code', 
        'name', 
        'quantity', 
        'unit', 
        'shelf_life', 
        'storage_conditions', 
        'retrieve_count', 
        'updated_at'
    )
    search_fields = ('code', 'name', 'storage_conditions')
    list_filter = ('storage_conditions',)
    
    # 防止管理员在主表中直接手动修改数量和出库次数（必须通过进出库账单记录生成动态变更）
    readonly_fields = ('quantity', 'retrieve_count', 'created_at', 'updated_at')
    
    # 在物料详情底端直接以列表方式反映出该物料的动态变更历史
    inlines = [InventoryRecordInline]

    fieldsets = (
        ('基本信息', {
            'fields': ('code', 'name', 'unit', 'shelf_life')
        }),
        ('储存与属性', {
            'fields': ('storage_conditions', 'precautions', 'remarks')
        }),
        ('统计与账面 (只读，根据变动自动计算)', {
            'fields': ('quantity', 'retrieve_count', 'created_at', 'updated_at')
        }),
    )

    def save_formset(self, request, form, formset, change):
        """
        在保存内联表单时，自动将当前登录的管理员账户关联为操作员
        """
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for instance in instances:
            if isinstance(instance, InventoryRecord) and not instance.pk:
                instance.operator = request.user
            instance.save()
        formset.save_m2m()


@admin.register(InventoryRecord)
class InventoryRecordAdmin(ModelAdmin):
    """
    进销存账目流水管理后台
    """
    list_display = (
        'created_at', 
        'material', 
        'record_type', 
        'quantity', 
        'store', 
        'operator', 
        'expiration_date'
    )
    search_fields = ('material__name', 'material__code', 'store__name', 'remarks')
    list_filter = ('record_type', 'store', 'created_at')
    
    # 限制操作员字段为只读，统一在 save_model 中自动填充，防止人工伪造操作员
    readonly_fields = ('operator', 'created_at')

    fieldsets = (
        ('流向与类型', {
            'fields': ('material', 'record_type', 'quantity')
        }),
        ('出入库信息', {
            'fields': ('store', 'expiration_date', 'remarks', 'operator', 'created_at')
        }),
    )

    def save_model(self, request, obj, form, change):
        """
        新增进出库记录时，自动标记当前操作员为登录用户
        """
        if not obj.pk:
            obj.operator = request.user
        super().save_model(request, obj, form, change)
