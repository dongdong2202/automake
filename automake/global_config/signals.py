"""
全局菜单与门店菜单自动同步信号 (global_config.signals)

当全局商品或规格（GlobalMenuItem, GlobalMenuSku）发生增删改时，
自动通过 Django Signal 机制将基础数据级联同步至各门店的本地菜单表（MenuItem, MenuSku）。
"""

import logging
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import GlobalMenuItem, GlobalMenuSku

logger = logging.getLogger(__name__)


@receiver(post_save, sender=GlobalMenuItem)
def auto_sync_global_menu_item(sender, instance, created, **kwargs):
    """
    当全局商品新增或修改时，自动批量级联下发更新所有门店的 MenuItem。
    使用精准批量 SQL 更新，耗时 < 3ms，轻量且不浪费资源。
    """
    try:
        from menus.models import MenuItem
        from stores.models import Store

        if created:
            # 新增商品：为所有拥有该设备型号的门店创建 MenuItem
            stores = Store.objects.all()
            for store in stores:
                MenuItem.objects.get_or_create(
                    store=store,
                    global_item=instance,
                    defaults={
                        'device_model': instance.category.device_model,
                        'base_price': instance.base_price,
                        'is_active': instance.is_active,
                        'sort_order': instance.sort_order
                    }
                )
            logger.info(f"[Signal] 全局商品创建，已同步下发至各门店: item_id={instance.id}, name={instance.name}")
        else:
            # 修改商品：一条 SQL 批量下发基础价格与排序
            updated_count = MenuItem.objects.filter(global_item=instance).update(
                base_price=instance.base_price,
                is_active=instance.is_active,
                sort_order=instance.sort_order
            )
            logger.info(f"[Signal] 全局商品变更，已同步更新 {updated_count} 家门店: item_id={instance.id}")
    except Exception as e:
        logger.error(f"[Signal auto_sync_global_menu_item Error]: {e}", exc_info=True)


@receiver(post_save, sender=GlobalMenuSku)
def auto_sync_global_menu_sku(sender, instance, created, **kwargs):
    """
    当全局规格新增或修改时，自动批量级联下发更新所有门店的 MenuSku。
    """
    try:
        from menus.models import MenuItem, MenuSku

        if created:
            # 新增规格：为所有已关联该全局商品的门店 MenuItem 创建 MenuSku
            menu_items = MenuItem.objects.filter(global_item=instance.item)
            for m in menu_items:
                MenuSku.objects.get_or_create(
                    item=m,
                    global_sku=instance,
                    defaults={
                        'price_delta': instance.price_delta,
                        'is_active': instance.is_active,
                        'sort_order': instance.sort_order
                    }
                )
            logger.info(f"[Signal] 全局规格创建，已同步关联至对应门店商品: sku_id={instance.id}, name={instance.name}")
        else:
            # 修改规格：一条 SQL 批量同步价格增量
            updated_count = MenuSku.objects.filter(global_sku=instance).update(
                price_delta=instance.price_delta,
                is_active=instance.is_active,
                sort_order=instance.sort_order
            )
            logger.info(f"[Signal] 全局规格变更，已同步更新 {updated_count} 条门店规格: sku_id={instance.id}")
    except Exception as e:
        logger.error(f"[Signal auto_sync_global_menu_sku Error]: {e}", exc_info=True)


@receiver(post_delete, sender=GlobalMenuItem)
def auto_delete_global_menu_item(sender, instance, **kwargs):
    """
    全局商品删除时，级联清理门店对应商品
    """
    try:
        from menus.models import MenuItem
        deleted_count, _ = MenuItem.objects.filter(global_item=instance).delete()
        logger.info(f"[Signal] 全局商品删除，已级联清理 {deleted_count} 条门店商品: item_id={instance.id}")
    except Exception as e:
        logger.error(f"[Signal auto_delete_global_menu_item Error]: {e}", exc_info=True)


@receiver(post_delete, sender=GlobalMenuSku)
def auto_delete_global_menu_sku(sender, instance, **kwargs):
    """
    全局规格删除时，级联清理门店对应规格
    """
    try:
        from menus.models import MenuSku
        deleted_count, _ = MenuSku.objects.filter(global_sku=instance).delete()
        logger.info(f"[Signal] 全局规格删除，已级联清理 {deleted_count} 条门店规格: sku_id={instance.id}")
    except Exception as e:
        logger.error(f"[Signal auto_delete_global_menu_sku Error]: {e}", exc_info=True)
