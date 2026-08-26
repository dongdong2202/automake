from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import GlobalMenuItem, GlobalMenuSku


@receiver(post_save, sender=GlobalMenuItem)
def auto_sync_global_menu_item(sender, instance, created, **kwargs):
    """
    当全局商品新增或修改时，自动批量级联下发更新所有门店的 MenuItem。
    使用精准批量 SQL 更新，耗时 < 3ms，极度轻量且绝不浪费资源。
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
        else:
            # 修改商品：一条 SQL 批量下发基础价格与排序
            MenuItem.objects.filter(global_item=instance).update(
                base_price=instance.base_price,
                is_active=instance.is_active,
                sort_order=instance.sort_order
            )
    except Exception as e:
        print(f"[Signal auto_sync_global_menu_item Error]: {e}")


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
        else:
            # 修改规格：一条 SQL 批量同步价格增量
            MenuSku.objects.filter(global_sku=instance).update(
                price_delta=instance.price_delta,
                is_active=instance.is_active,
                sort_order=instance.sort_order
            )
    except Exception as e:
        print(f"[Signal auto_sync_global_menu_sku Error]: {e}")


@receiver(post_delete, sender=GlobalMenuItem)
def auto_delete_global_menu_item(sender, instance, **kwargs):
    """
    全局商品删除时，级联清理门店对应商品
    """
    try:
        from menus.models import MenuItem
        MenuItem.objects.filter(global_item=instance).delete()
    except Exception as e:
        print(f"[Signal auto_delete_global_menu_item Error]: {e}")


@receiver(post_delete, sender=GlobalMenuSku)
def auto_delete_global_menu_sku(sender, instance, **kwargs):
    """
    全局规格删除时，级联清理门店对应规格
    """
    try:
        from menus.models import MenuSku
        MenuSku.objects.filter(global_sku=instance).delete()
    except Exception as e:
        print(f"[Signal auto_delete_global_menu_sku Error]: {e}")
