import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')
django.setup()

from stores.models import Store
from devices.models import Device
from menus.models import MenuCategory, MenuItem, MenuSku, MaterialStock
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
            'status': Store.STATUS_OPEN
        }
    )
    if created:
        print(f"创建门店: {store.name}")
    else:
        print(f"已存在门店: {store.name}")

    # 3. 创建或关联设备 SN001 到该门店
    device, created = Device.objects.get_or_create(
        device_sn='SN001',
        defaults={
            'device_name': '智能咖啡机 SN001',
            'device_model': 'AutoMake-CupV1',
            'firmware_version': 'v2.1.0',
            'status': Device.STATUS_ONLINE,
            'store': store,
            'last_heartbeat_at': timezone.now(),
            'mqtt_topic_prefix': 'automake/device/SN001',
            'extra_config': {'device_address': '北京市海淀区西二旗软件园'}
        }
    )
    if created:
        print(f"创建设备: {device.device_sn}")
    else:
        # 确保关联到该门店且是在线状态
        device.store = store
        device.status = Device.STATUS_ONLINE
        device.last_heartbeat_at = timezone.now()
        device.save()
        print(f"已存在设备: {device.device_sn}，更新关联门店与状态为在线")

    # 4. 初始化物料库存
    materials_data = [
        {'code': 'coffee_bean', 'name': '咖啡豆', 'quantity': 1000.0, 'unit': 'g', 'threshold': 100.0},
        {'code': 'fresh_milk', 'name': '鲜牛奶', 'quantity': 5000.0, 'unit': 'ml', 'threshold': 500.0},
    ]
    for mat in materials_data:
        stock, mat_created = MaterialStock.objects.get_or_create(
            device=device,
            material_code=mat['code'],
            defaults={
                'material_name': mat['name'],
                'current_quantity': mat['quantity'],
                'unit': mat['unit'],
                'alert_threshold': mat['threshold'],
                'last_reported_at': timezone.now()
            }
        )
        if mat_created:
            print(f"初始化物料库存: {mat['name']} -> {mat['quantity']}{mat['unit']}")
        else:
            # 重置为满库存方便测试
            stock.current_quantity = mat['quantity']
            stock.locked_quantity = 0.0
            stock.save()
            print(f"重置物料库存: {mat['name']} -> {mat['quantity']}{mat['unit']}")

    # 5. 创建菜单分类
    category, created = MenuCategory.objects.get_or_create(
        store=store,
        name='经典咖啡',
        defaults={
            'sort_order': 1,
            'is_active': True
        }
    )
    if created:
        print(f"创建分类: {category.name}")

    # 6. 创建商品和 SKU
    # 美式咖啡
    item_americano, created = MenuItem.objects.get_or_create(
        store=store,
        category=category,
        name='美式咖啡',
        defaults={
            'description': '经典浓缩与水的完美融合',
            'base_price': 1500, # 15元
            'stock_type': MenuItem.STOCK_DEVICE,
            'is_active': True
        }
    )
    if created:
        print(f"创建商品: {item_americano.name}")

    sku_americano, created = MenuSku.objects.get_or_create(
        item=item_americano,
        name='标准美式',
        defaults={
            'price_delta': 0,
            'is_active': True
        }
    )
    if created:
        print(f"创建SKU: {sku_americano.name}")

    # 拿铁咖啡
    item_latte, created = MenuItem.objects.get_or_create(
        store=store,
        category=category,
        name='拿铁咖啡',
        defaults={
            'description': '香浓浓缩咖啡配上细腻鲜牛奶',
            'base_price': 1800, # 18元
            'stock_type': MenuItem.STOCK_DEVICE,
            'is_active': True
        }
    )
    if created:
        print(f"创建商品: {item_latte.name}")

    sku_latte, created = MenuSku.objects.get_or_create(
        item=item_latte,
        name='标准拿铁',
        defaults={
            'price_delta': 0,
            'is_active': True
        }
    )
    if created:
        print(f"创建SKU: {sku_latte.name}")

    print("测试数据初始化完毕！")

if __name__ == '__main__':
    seed_db()
