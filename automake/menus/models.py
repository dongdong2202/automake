"""
菜单模型模块

门店菜单表结构：
- MenuItem 作为关联表，存储各门店所拥有的商品及其基础价格微调（ base_price ），仅允许在全局价格的 ±20% 范围内微调。
- MenuSku 作为关联表，存储各门店所拥有的商品规格，映射到 GlobalMenuSku，且最终售价（ MenuItem.base_price + MenuSku.price_delta ）同样必须在全局最终售价的 ±20% 范围内。
- 门店菜单不能手动增加，只能通过设备类型同步，但可以删减（删除或设置 is_active = False）。
"""

from django.db import models
from django.core.exceptions import ValidationError


class MenuItem(models.Model):
    """
    门店菜单商品表
    用于关联特定门店、其物理设备类型与全局菜单商品，并允许在指定范围内调整价格。
    """
    store = models.ForeignKey(
        'stores.Store', on_delete=models.CASCADE,
        related_name='menu_items', verbose_name='门店'
    )
    device_type = models.ForeignKey(
        'global_config.DeviceType', on_delete=models.CASCADE,
        related_name='local_items', verbose_name='设备类型'
    )
    global_item = models.ForeignKey(
        'global_config.GlobalMenuItem', on_delete=models.CASCADE,
        related_name='local_items', verbose_name='全局商品'
    )
    # 基础价格（单位：分，允许在全局价格基础上上下浮动20%）
    base_price = models.IntegerField(verbose_name='基础价格（分）')
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
        return f"{self.store.name} - {self.global_item.name}"

    @property
    def name(self):
        """返回关联全局商品的名称"""
        return self.global_item.name

    @classmethod
    def sync_store_menu(cls, store):
        """
        自动根据门店所拥有的物理设备类型同步全局菜单及规格 (SKU)。
        保留门店已经做出的价格微调与激活状态修改。
        """
        from devices.models import Device
        from global_config.models import GlobalMenuCategory, GlobalMenuItem
        
        # 获取门店目前拥有的所有已注册设备的物理设备类型
        store_device_types = list(
            Device.objects.filter(store=store, device_type__isnull=False)
            .values_list('device_type_id', flat=True)
            .distinct()
        )
        if not store_device_types:
            return

        # 1. 依据设备类型获取对应的全局分类
        global_categories = GlobalMenuCategory.objects.filter(
            is_active=True,
            device_type_id__in=store_device_types
        )

        # 2. 继承商品
        global_items = GlobalMenuItem.objects.filter(category__in=global_categories, is_active=True)

        for g_item in global_items:
            menu_item, created = cls.objects.get_or_create(
                store=store,
                device_type=g_item.category.device_type,
                global_item=g_item,
                defaults={
                    'base_price': g_item.base_price,
                    'is_active': g_item.is_active,
                    'sort_order': g_item.sort_order,
                }
            )
            
            # 同步对应的规格 (SKU)
            for g_sku in g_item.skus.filter(is_active=True):
                MenuSku.objects.get_or_create(
                    item=menu_item,
                    global_sku=g_sku,
                    defaults={
                        'price_delta': g_sku.price_delta,
                        'is_active': g_sku.is_active,
                        'sort_order': g_sku.sort_order,
                    }
                )


    def clean(self):
        """
        验证逻辑：
        1. 验证 base_price 是否在全局 base_price 的 80% 到 120% 之间（上下浮动20%）。
        2. 验证 MenuItem 的 device_type 是否与对应全局商品的分类下的 device_type 一致。
        """
        super().clean()
        if self.global_item:
            # 价格区间验证（上下浮动20%）
            min_price = int(self.global_item.base_price * 0.8)
            max_price = int(self.global_item.base_price * 1.2)
            if self.base_price < min_price or self.base_price > max_price:
                raise ValidationError({
                    'base_price': f'价格必须在全局价格（{self.global_item.base_price}分）的上下20%范围内（即 {min_price}分 ~ {max_price}分 之间）'
                })
            
            # 设备类型一致性验证
            if self.device_type and self.global_item.category.device_type != self.device_type:
                raise ValidationError({
                    'device_type': f'设备类型与全局商品分类关联的设备类型（{self.global_item.category.device_type.name}）不匹配'
                })


class MenuSku(models.Model):
    """
    门店商品规格 / SKU 表
    与 GlobalMenuSku 对应，只允许修改价格增量（price_delta）和启用状态（is_active）。
    """
    item = models.ForeignKey(
        MenuItem, on_delete=models.CASCADE,
        related_name='skus', verbose_name='商品'
    )
    global_sku = models.ForeignKey(
        'global_config.GlobalMenuSku', on_delete=models.CASCADE,
        related_name='local_skus', verbose_name='继承的全局SKU'
    )
    price_delta = models.IntegerField(default=0, verbose_name='价格增量（分）')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    sort_order = models.IntegerField(default=0, verbose_name='排序权重')

    class Meta:
        db_table = 'menu_sku'
        verbose_name = '商品规格'
        verbose_name_plural = '商品规格列表'
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f"{self.item.global_item.name} - {self.global_sku.name}"

    def clean(self):
        """
        验证逻辑：
        1. 验证对应的 global_sku 属于 MenuItem.global_item。
        2. 验证最终售价（base_price + price_delta）是否在全局最终售价（global_item.base_price + global_sku.price_delta）的 ±20% 范围内。
        """
        super().clean()
        if self.item and self.global_sku:
            if self.global_sku.item != self.item.global_item:
                raise ValidationError({
                    'global_sku': f'规格所属的全局商品（{self.global_sku.item.name}）与本地商品的全局商品（{self.item.global_item.name}）不匹配'
                })
            
            global_final = self.item.global_item.base_price + self.global_sku.price_delta
            local_final = self.item.base_price + self.price_delta
            min_final = int(global_final * 0.8)
            max_final = int(global_final * 1.2)
            if local_final < min_final or local_final > max_final:
                raise ValidationError({
                    'price_delta': f'规格最终售价（{local_final}分）必须在全局售价（{global_final}分）的上下20%范围内（即 {min_final}分 ~ {max_final}分 之间）'
                })
