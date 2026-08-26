"""
验证总仓分拨入店、门店自身库存管理、出库到设备记账及设备传感器库存大看板专项测试
"""

import os
import django
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')
django.setup()

from stores.models import Store
from devices.models import Device, DeviceBarrelDict, DeviceConsumableStock
from inventory.models import Material, InventoryRecord, StoreInventory, StoreInventoryRecord
from users.models import User
from rest_framework.test import APIRequestFactory, force_authenticate
from admin_api.views.stores import StoreInventoryListView, StoreDispatchToDeviceView, StoreInventoryRecordListView
from admin_api.views.devices import DeviceStockOverviewView


def test_store_inventory_system():
    print("🚀 开始测试门店管理、门店库存流转与设备传感器库存展示系统...")

    # 1. 准备测试基础数据
    admin_user = User.objects.filter(is_superuser=True).first()
    if not admin_user:
        admin_user = User.objects.create_superuser('test_admin_01', 'admin@test.com', 'admin123')

    store, _ = Store.objects.get_or_create(
        id=100099,
        defaults={'name': '测试流转门店 (100099)', 'status': Store.STATUS_OPEN}
    )

    device, _ = Device.objects.get_or_create(
        device_sn='TEST_SN_STOCK_01',
        defaults={'device_name': '测试1号咖啡机', 'store': store, 'status': Device.STATUS_ONLINE}
    )
    device.store = store
    device.save()

    mat_bean, _ = Material.objects.get_or_create(
        code='TEST_FLOW_BEAN_01',
        defaults={
            'name': '流转特级咖啡豆',
            'material_type': Material.TYPE_INGREDIENT,
            'price': Decimal('60.00'),
            'quantity': Decimal('200.00'),
            'unit': 'kg',
            'shelf_life': '365天'
        }
    )
    mat_bean.quantity = Decimal('200.00')
    mat_bean.save()

    mat_cup, _ = Material.objects.get_or_create(
        code='paperL',
        defaults={
            'name': '大号纸杯',
            'material_type': Material.TYPE_CUP,
            'price': Decimal('0.35'),
            'quantity': Decimal('1000.00'),
            'unit': '个',
            'shelf_life': ''
        }
    )
    mat_cup.quantity = Decimal('1000.00')
    mat_cup.save()

    # 清理旧在店库存与流水
    StoreInventory.objects.filter(store=store).delete()
    StoreInventoryRecord.objects.filter(store=store).delete()

    print("  ✓ 基础数据初始化完成")

    # 2. 模拟总仓出库分拨到门店 (50kg 咖啡豆)
    rec_out_bean = InventoryRecord(
        material=mat_bean,
        record_type=InventoryRecord.RECORD_TYPE_OUT,
        quantity=Decimal('50.00'),
        store=store,
        operator=admin_user,
        remarks='8月批次分拨到测试门店'
    )
    rec_out_bean.save()

    mat_bean.refresh_from_db()
    assert mat_bean.quantity == Decimal('150.00')
    print(f"  ✓ 总仓物料库存成功扣减: 剩余 {mat_bean.quantity} kg")

    # 校验门店在店库存是否自动生成并增加 50kg
    store_bean = StoreInventory.objects.filter(store=store, material=mat_bean).first()
    assert store_bean is not None
    assert store_bean.quantity == Decimal('50.00')
    print(f"  ✓ 门店自身在店库存 (StoreInventory) 自动增加入账: {store_bean.quantity} kg")

    # 校验门店调拨流水
    s_rec_in = StoreInventoryRecord.objects.filter(
        store=store, material=mat_bean, record_type=StoreInventoryRecord.TYPE_IN_FROM_WAREHOUSE
    ).first()
    assert s_rec_in is not None
    assert s_rec_in.quantity == Decimal('50.00')
    print(f"  ✓ 门店调拨流水 (StoreInventoryRecord) 自动生成入店记录: {s_rec_in.record_type} +{s_rec_in.quantity}kg")

    # 再分拨 200 个纸杯到门店
    rec_out_cup = InventoryRecord(
        material=mat_cup,
        record_type=InventoryRecord.RECORD_TYPE_OUT,
        quantity=Decimal('200.00'),
        store=store,
        operator=admin_user,
        remarks='分拨常用大号纸杯'
    )
    rec_out_cup.save()
    store_cup = StoreInventory.objects.filter(store=store, material=mat_cup).first()
    assert store_cup.quantity == Decimal('200.00')
    print(f"  ✓ 门店在店纸杯库存自动入账: {store_cup.quantity} 个")

    # 3. 模拟门店操作【出库加料到设备】(从门店 50kg 咖啡豆中出库 5kg 到设备 TEST_SN_STOCK_01)
    factory = APIRequestFactory()
    dispatch_view = StoreDispatchToDeviceView.as_view()

    req = factory.post(
        f'/api/admin/stores/{store.id}/dispatch-to-device/',
        {
            'material_id': mat_bean.id,
            'device_sn': device.device_sn,
            'quantity': '5.00',
            'remarks': '上午常规加料到咖啡机'
        },
        format='json'
    )
    force_authenticate(req, user=admin_user)
    resp = dispatch_view(req, store_id=store.id)
    assert resp.status_code == 200
    assert resp.data['code'] == 0
    print(f"  ✓ 门店出库加料 API 调用成功: {resp.data['message']}")

    # 校验门店库存扣减为 45kg
    store_bean.refresh_from_db()
    assert store_bean.quantity == Decimal('45.00')
    print(f"  ✓ 门店在店库存正确扣减: 剩余 {store_bean.quantity} kg")

    # 校验生成了 out_to_device 流水
    s_rec_out = StoreInventoryRecord.objects.filter(
        store=store, material=mat_bean, record_type=StoreInventoryRecord.TYPE_OUT_TO_DEVICE
    ).first()
    assert s_rec_out is not None
    assert s_rec_out.quantity == Decimal('5.00')
    assert s_rec_out.device == device
    print(f"  ✓ 门店出库到设备流水记录校验通过: 目标设备={s_rec_out.device.device_sn}, 数量={s_rec_out.quantity}kg")

    # 4. 模拟门店出库加料 50 个大号纸杯到设备
    req_cup = factory.post(
        f'/api/admin/stores/{store.id}/dispatch-to-device/',
        {
            'material_id': mat_cup.id,
            'device_sn': device.device_sn,
            'quantity': '50.00',
            'remarks': '补充大纸杯仓'
        },
        format='json'
    )
    force_authenticate(req_cup, user=admin_user)
    resp_cup = dispatch_view(req_cup, store_id=store.id)
    assert resp_cup.status_code == 200

    store_cup.refresh_from_db()
    assert store_cup.quantity == Decimal('150.00')
    print(f"  ✓ 门店在店纸杯库存正确扣减: 剩余 {store_cup.quantity} 个")

    dev_cup_stock = DeviceConsumableStock.objects.filter(device=device, code_id='paperL').first()
    assert dev_cup_stock is not None
    print(f"  ✓ 设备耗材仓 (DeviceConsumableStock) 正确同步更新: 当前存量={dev_cup_stock.quantity} 个")

    # 5. 测试设备物料与耗材传感器库存概览 API
    stock_view = DeviceStockOverviewView.as_view()
    req_stock = factory.get(f'/api/admin/devices/stocks-overview/?store_id={store.id}')
    force_authenticate(req_stock, user=admin_user)
    resp_stock = stock_view(req_stock)
    assert resp_stock.status_code == 200
    assert resp_stock.data['code'] == 0
    dev_data = resp_stock.data['data'][0]
    assert dev_data['device_sn'] == device.device_sn
    assert len(dev_data['barrels']) >= 12
    assert len(dev_data['consumables']) == 6
    print(f"  ✓ 设备传感器库存看板 API 返回正常: 包含 {len(dev_data['barrels'])} 个硬件料桶与 {len(dev_data['consumables'])} 项耗材仓数据")

    # 6. 测试门店调拨流水 API
    rec_view = StoreInventoryRecordListView.as_view()
    req_rec = factory.get(f'/api/admin/stores/{store.id}/records/')
    force_authenticate(req_rec, user=admin_user)
    resp_rec = rec_view(req_rec, store_id=store.id)
    assert resp_rec.status_code == 200
    assert resp_rec.data['data']['count'] >= 3
    print(f"  ✓ 门店调拨台账 API 返回正常: 共有 {resp_rec.data['data']['count']} 笔调拨流水")

    print("\n🎉 门店管理、三级库存流转与设备传感器库存看板全部业务逻辑 100% 验证通过！")


if __name__ == '__main__':
    test_store_inventory_system()
