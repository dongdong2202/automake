"""
菜单模型模块

菜单体系分为三层：
  分类（MenuCategory）→ 商品（MenuItem）→ 规格/SKU（MenuSku）

价格规则（MenuPriceRule）支持按时段/门店的差异化定价（预留扩展）。
"""

from django.db import models


class MenuCategory(models.Model):
    """
    菜单分类表

    如：热饮、冷饮、小食等顶层分类。
    一个分类属于一个门店，不同门店可有同名分类。
    """
    store = models.ForeignKey(
        'stores.Store', on_delete=models.CASCADE,
        related_name='categories', verbose_name='门店'
    )
    name = models.CharField(max_length=64, verbose_name='分类名称')
    icon_url = models.URLField(max_length=512, blank=True, verbose_name='分类图标')
    sort_order = models.IntegerField(default=0, verbose_name='排序权重')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'menu_category'
        verbose_name = '菜单分类'
        verbose_name_plural = '菜单分类列表'
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f'{self.store.name} - {self.name}'


class MenuItem(models.Model):
    """
    菜单商品表（主表）

    每个商品属于一个分类，可有多个规格（MenuSku）。
    stock_type 控制库存管理方式：
      - 'device'：设备自动管理库存（物料上报决定）
      - 'manual'：手动管理库存
      - 'unlimited'：不限库存
    """

    STOCK_DEVICE = 'device'
    STOCK_MANUAL = 'manual'
    STOCK_UNLIMITED = 'unlimited'

    STOCK_TYPE_CHOICES = [
        (STOCK_DEVICE, '设备管理'),
        (STOCK_MANUAL, '手动管理'),
        (STOCK_UNLIMITED, '不限库存'),
    ]

    category = models.ForeignKey(
        MenuCategory, on_delete=models.CASCADE,
        related_name='items', verbose_name='分类'
    )
    # 冗余存储门店，方便直接按门店查询商品
    store = models.ForeignKey(
        'stores.Store', on_delete=models.CASCADE,
        related_name='menu_items', verbose_name='门店'
    )
    name = models.CharField(max_length=128, verbose_name='商品名称')
    description = models.TextField(blank=True, verbose_name='商品描述')
    image_url = models.URLField(max_length=512, blank=True, verbose_name='商品图片')
    # 基础价格（单位：分，整数存储避免浮点误差）
    base_price = models.IntegerField(default=0, verbose_name='基础价格（分）')
    stock_type = models.CharField(
        max_length=20, choices=STOCK_TYPE_CHOICES,
        default=STOCK_DEVICE, verbose_name='库存类型'
    )
    # 当 stock_type 为 manual 时使用
    manual_stock = models.IntegerField(default=0, verbose_name='手动库存数量')
    is_active = models.BooleanField(default=True, db_index=True, verbose_name='是否上架')
    sort_order = models.IntegerField(default=0, verbose_name='排序权重')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'menu_item'
        verbose_name = '菜单商品'
        verbose_name_plural = '菜单商品列表'
        ordering = ['sort_order', 'id']

    def __str__(self):
        return self.name


class MenuSku(models.Model):
    """
    商品规格/SKU 表

    一个商品可以有多个 SKU，例如：大杯/中杯、热/冷。
    每个 SKU 有独立的价格增量（price_delta）和库存。
    """
    item = models.ForeignKey(
        MenuItem, on_delete=models.CASCADE,
        related_name='skus', verbose_name='商品'
    )
    name = models.CharField(max_length=64, verbose_name='规格名称')  # 如：大杯、加糖
    # 规格属性，JSON 格式。示例：{"size": "大杯", "temperature": "热"}
    attributes = models.JSONField(default=dict, blank=True, verbose_name='规格属性')
    # 价格增量（分），相对于 base_price 的差值（可为负）
    price_delta = models.IntegerField(default=0, verbose_name='价格增量（分）')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    sort_order = models.IntegerField(default=0, verbose_name='排序权重')

    class Meta:
        db_table = 'menu_sku'
        verbose_name = '商品规格'
        verbose_name_plural = '商品规格列表'
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f'{self.item.name} - {self.name}'

    @property
    def final_price(self):
        """最终价格 = 商品基础价格 + 规格增量（单位：分）"""
        return self.item.base_price + self.price_delta


class MaterialStock(models.Model):
    """
    物料库存表

    记录每台设备上各物料的当前库存量，由上位机定期上报更新。
    当库存低于 alert_threshold 时触发告警。
    """
    device = models.ForeignKey(
        'devices.Device', on_delete=models.CASCADE,
        related_name='material_stocks', verbose_name='设备'
    )
    # 物料名称（如：牛奶、糖浆-香草、咖啡豆）
    material_name = models.CharField(max_length=64, verbose_name='物料名称')
    material_code = models.CharField(max_length=64, db_index=True, verbose_name='物料编码')
    # 当前库存量（设备上报的原始单位，如 ml 或 g）
    current_quantity = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name='当前库存量'
    )
    # 锁定库存量（由上位机发起锁定，用于防止超卖）
    locked_quantity = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name='锁定库存量'
    )
    unit = models.CharField(max_length=16, default='ml', verbose_name='单位')
    # 库存告警阈值
    alert_threshold = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name='告警阈值'
    )
    last_reported_at = models.DateTimeField(null=True, blank=True, verbose_name='最后上报时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'material_stock'
        verbose_name = '物料库存'
        verbose_name_plural = '物料库存列表'
        unique_together = [('device', 'material_code')]

    def __str__(self):
        return f'{self.device} - {self.material_name}'

    @property
    def is_low(self):
        """判断库存是否低于告警阈值"""
        return self.current_quantity <= self.alert_threshold
