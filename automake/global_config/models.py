from django.db import models


class DeviceType(models.Model):
    """
    设备类型定义
    不同类型的设备（如单头、双头咖啡机，是否支持制冰功能等）
    """
    name = models.CharField(max_length=128, verbose_name='设备类型名称')
    code = models.CharField(max_length=64, unique=True, verbose_name='类型编码')
    description = models.TextField(blank=True, verbose_name='类型描述')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'global_device_type'
        verbose_name = '全局设备类型'
        verbose_name_plural = '全局设备类型列表'

    def __str__(self):
        return f"{self.name} ({self.code})"


class GlobalMaterial(models.Model):
    """
    全局物料定义表
    限制在配方及库存管理中能选取的物料范围
    """
    name = models.CharField(max_length=64, verbose_name='物料名称')
    code = models.CharField(max_length=64, unique=True, verbose_name='物料编码')
    unit = models.CharField(max_length=16, default='ml', verbose_name='标准单位')
    description = models.TextField(blank=True, verbose_name='物料描述')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'global_material'
        verbose_name = '全局物料'
        verbose_name_plural = '全局物料列表'

    def __str__(self):
        return f"{self.name} ({self.code})"


class GlobalMenuCategory(models.Model):
    """
    全局菜单分类 (必须依赖设备类型)
    """
    device_type = models.ForeignKey(
        DeviceType, on_delete=models.PROTECT,
        related_name='categories', verbose_name='设备类型'
    )
    name = models.CharField(max_length=64, verbose_name='分类名称')
    icon_url = models.FileField(upload_to='global_category_icons/', max_length=512, blank=True, verbose_name='分类图标')
    sort_order = models.IntegerField(default=0, verbose_name='排序权重')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'global_menu_category'
        verbose_name = '全局菜单分类'
        verbose_name_plural = '全局菜单分类列表'
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f"{self.name} ({self.device_type.name})"


class GlobalMenuItem(models.Model):
    """
    全局菜单商品 (必须依赖设备类型)
    """
    category = models.ForeignKey(
        GlobalMenuCategory, on_delete=models.CASCADE,
        related_name='items', verbose_name='全局分类'
    )
    name = models.CharField(max_length=128, verbose_name='商品名称')
    description = models.TextField(blank=True, verbose_name='商品描述')
    image_url = models.URLField(max_length=512, blank=True, verbose_name='商品图片')
    base_price = models.IntegerField(default=0, verbose_name='基础价格（分）')
    is_active = models.BooleanField(default=True, db_index=True, verbose_name='是否启用')
    sort_order = models.IntegerField(default=0, verbose_name='排序权重')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'global_menu_item'
        verbose_name = '全局菜单商品'
        verbose_name_plural = '全局菜单商品列表'
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f"{self.name} ({self.category.name})"


class GlobalMenuSku(models.Model):
    """
    全局商品规格 / SKU (如杯型：大中小，温度：热/冷等)
    每个 SKU 都是独立的，拥有自己的价格增量和配方用量
    """
    item = models.ForeignKey(
        GlobalMenuItem, on_delete=models.CASCADE,
        related_name='skus', verbose_name='全局商品'
    )
    name = models.CharField(max_length=128, verbose_name='规格名称')
    category = models.CharField(max_length=64, blank=True, default='', verbose_name='分类')
    attributes = models.JSONField(default=dict, blank=True, verbose_name='规格属性')
    price_delta = models.IntegerField(default=0, verbose_name='价格增量（分）')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    sort_order = models.IntegerField(default=0, verbose_name='排序权重')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'global_menu_sku'
        verbose_name = '全局商品规格'
        verbose_name_plural = '全局商品规格列表'
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f"{self.item.name} - {self.name}"


class GlobalSkuIngredient(models.Model):
    """
    全局规格配料用量 (即配方详情)
    直接定义该 SKU 所需要的各种原料的具体用量
    """
    sku = models.ForeignKey(
        GlobalMenuSku, on_delete=models.CASCADE,
        related_name='ingredients', verbose_name='全局规格(SKU)'
    )
    material = models.ForeignKey(
        GlobalMaterial, on_delete=models.PROTECT,
        related_name='ingredients', verbose_name='物料'
    )
    quantity = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name='用量'
    )
    unit = models.CharField(max_length=16, blank=True, verbose_name='单位(留空使用物料默认单位)')

    class Meta:
        db_table = 'global_sku_ingredient'
        verbose_name = '全局规格配料'
        verbose_name_plural = '全局规格配料列表'

    def __str__(self):
        u = self.unit if self.unit else self.material.unit
        return f"{self.material.name} ({self.quantity}{u})"

    @property
    def material_name(self):
        return self.material.name

    @property
    def material_code(self):
        return self.material.code
