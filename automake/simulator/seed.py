import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')
django.setup()

from stores.models import Store
from devices.models import Device
from menus.models import MenuItem, MenuSku
from users.models import User
from django.utils import timezone

def seed_db():
    print("开始初始化测试数据...")

    # 1. 创建默认测试用户
    user, created = User.objects.get_or_create(
        openid='dev-test-openid',
        defaults={
            'username': 'dev_tester',
            'role': User.CUSTOMER,
            'is_active': True
        }
    )
    if created:
        print(f"创建测试用户: {user.username}")
    else:
        print(f"已存在测试用户: {user.username}")

    # 2. 创建测试门店
    store, created = Store.objects.get_or_create(
        name='西二旗智能咖啡店',
        defaults={
            'description': '提供高品质自助磨豆咖啡',
            'address': '北京市海淀区西二旗软件园',
            'lat': 40.056,
            'lng': 116.307,
            'contact_phone': '13812345678',
            'status': Store.STATUS_OPEN,
            'code': 'first1'
        }
    )
    if created:
        print(f"创建门店: {store.name}")
    else:
        # 确保 code 设置为 'first1'
        if store.code != 'first1':
            store.code = 'first1'
            store.save()
        print(f"已存在门店: {store.name}")
 
    from global_config.models import DeviceModel, GlobalMenuCategory, GlobalMenuItem, GlobalMenuSku
    
    # 2.5 创建默认设备类型
    dev_type, dev_type_created = DeviceModel.objects.get_or_create(
        code='coffee_maker',
        defaults={
            'name': '智能咖啡机',
            'description': '支持咖啡制作的设备类型'
        }
    )
    if dev_type_created:
        print(f"创建设备类型: {dev_type.name}")

    # 3. 创建或关联设备 SN001 到该门店
    device, created = Device.objects.get_or_create(
        device_sn='SN001',
        defaults={
            'device_name': '智能咖啡机 SN001',
            'device_model': dev_type,
            'firmware_version': 'v2.1.0',
            'status': Device.STATUS_ONLINE,
            'store': store,
            'key_code': 'first1',
            'last_heartbeat_at': timezone.now(),
            'mqtt_topic_prefix': 'automake/device/SN001',
            'extra_config': {'device_address': '北京市海淀区西二旗软件园'}
        }
    )
    if created:
        print(f"创建设备: {device.device_sn}")
    else:
        # 确保关联到该门店且是在线状态，且 key_code 与门店一致
        device.store = store
        device.status = Device.STATUS_ONLINE
        device.device_model = dev_type
        device.key_code = 'first1'
        device.last_heartbeat_at = timezone.now()
        device.save()
        print(f"已存在设备: {device.device_sn}，更新关联门店与状态为在线")

    # 3.5 创建全局物料
    from inventory.models import Material
    inv_bean, _ = Material.objects.get_or_create(
        name='咖啡豆',
        defaults={'code': 'coffee_bean', 'unit': 'g'}
    )
    inv_milk, _ = Material.objects.get_or_create(
        name='鲜牛奶',
        defaults={'code': 'fresh_milk', 'unit': 'ml'}
    )



    # 5. 创建全局菜单分类
    g_category, created = GlobalMenuCategory.objects.get_or_create(
        device_model=dev_type,
        name='经典咖啡',
        defaults={
            'sort_order': 1,
            'is_active': True
        }
    )

    # 6. 创建全局商品和 SKU
    g_item_americano, created = GlobalMenuItem.objects.get_or_create(
        category=g_category,
        name='美式咖啡',
        defaults={
            'description': '经典浓缩与水的完美融合',
            'base_price': 1500,
            'is_active': True
        }
    )

    g_sku_americano, created = GlobalMenuSku.objects.get_or_create(
        item=g_item_americano,
        name='标准美式',
        defaults={
            'price_delta': 0,
            'is_active': True
        }
    )

    g_item_latte, created = GlobalMenuItem.objects.get_or_create(
        category=g_category,
        name='拿铁咖啡',
        defaults={
            'description': '香浓浓缩咖啡配上细腻鲜牛奶',
            'base_price': 1800,
            'is_active': True
        }
    )

    g_sku_latte, created = GlobalMenuSku.objects.get_or_create(
        item=g_item_latte,
        name='标准拿铁',
        defaults={
            'price_delta': 0,
            'is_active': True
        }
    )

    # 8. 创建本地商品和 SKU
    # 美式咖啡
    item_americano, created = MenuItem.objects.get_or_create(
        store=store,
        device_model=dev_type,
        global_item=g_item_americano,
        defaults={
            'base_price': 1500, # 15元
            'is_active': True
        }
    )
    if created:
        print(f"创建商品: {item_americano.name}")

    sku_americano, created = MenuSku.objects.get_or_create(
        item=item_americano,
        global_sku=g_sku_americano,
        defaults={
            'price_delta': 0,
            'is_active': True
        }
    )
    if created:
        print(f"创建SKU: {sku_americano.global_sku.name}")

    # 拿铁咖啡
    item_latte, created = MenuItem.objects.get_or_create(
        store=store,
        device_model=dev_type,
        global_item=g_item_latte,
        defaults={
            'base_price': 1800, # 18元
            'is_active': True
        }
    )
    if created:
        print(f"创建商品: {item_latte.name}")

    sku_latte, created = MenuSku.objects.get_or_create(
        item=item_latte,
        global_sku=g_sku_latte,
        defaults={
            'price_delta': 0,
            'is_active': True
        }
    )
    if created:
        print(f"创建SKU: {sku_latte.global_sku.name}")

    print("测试数据初始化完毕！")

if __name__ == '__main__':
    seed_db()
