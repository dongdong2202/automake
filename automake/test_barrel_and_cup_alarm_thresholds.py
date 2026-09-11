"""
test_barrel_and_cup_alarm_thresholds.py
=============================================================
专项测试套件：验证料桶物料字典双级报警与耗材停售保护
1. 料桶报警1 (alarm_threshold_1): 达到/低于此值时发短信并通知后台管理员
2. 料桶报警2 (alarm_threshold_2): 达到/低于此值时相当于物料=0 (停售)
3. 多料桶独立阈值聚合
4. 纸杯耗材报警1: 少于20个时报警并通知管理员
5. 纸杯耗材报警2: 少于5个时停止售卖 (precheck / lock / menus 拦截)
=============================================================
"""

import os
import sys
from decimal import Decimal
import django

sys.path.insert(0, '/home/ubuntu/autoMachine/automake')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')
django.setup()

from django.test import TestCase
from django_redis import get_redis_connection

from users.models import User
from stores.models import Store
from devices.models import Device, DeviceBarrelDict, DeviceConsumableStock, DeviceAlarm
from inventory.models import Material
from menus.models import MenuItem, MenuSku
from payments.models import PaymentRecord
from global_config.models import DeviceModel, GlobalMenuCategory, GlobalMenuItem, GlobalSkuTemplate, GlobalMenuSku, GlobalSkuIngredient
from orders.models import OrderMain, OrderItem
from orders.services import precheck_order, try_lock_order_inventory, deduct_order_consumables
from monitor.services import process_device_status_report
from notifications.models import NotifyEvent
from menus.services import calculate_device_sold_out_items


def run_tests():
    print("=" * 75)
    print("🚀 开始执行【料桶物料字典双级报警与耗材停售保护】专项测试")
    print("=" * 75)

    redis_conn = get_redis_connection("default")

    # 1. 基础环境清理与准备
    user = User.objects.filter(openid="test_alarm_user").first()
    if not user:
        user = User.objects.create_user(openid="test_alarm_user")
    store, _ = Store.objects.get_or_create(code="ALARM_STORE_01", defaults={"name": "报警测试门店", "contact_phone": "13800008888"})
    dev_model, _ = DeviceModel.objects.get_or_create(code="ALARM_DEV_MODEL", defaults={"name": "测试机型"})
    device, _ = Device.objects.get_or_create(
        device_sn="SN_ALARM_TEST_01",
        defaults={"device_name": "报警测试咖啡机", "store": store, "device_model": dev_model, "status": Device.STATUS_ONLINE}
    )
    device.status = Device.STATUS_ONLINE
    device.save()

    # 物料
    mat_milk, _ = Material.objects.get_or_create(code="fresh_milk", defaults={"name": "鲜牛奶", "unit": "ml"})
    mat_bean, _ = Material.objects.get_or_create(code="coffee_bean", defaults={"name": "咖啡豆", "unit": "g"})
    mat_cup, _ = Material.objects.get_or_create(code="paperL", defaults={"name": "纸大杯", "unit": "个", "material_type": "cup"})
    mat_lid, _ = Material.objects.get_or_create(code="lid", defaults={"name": "杯盖", "unit": "个", "material_type": "consumable"})
    mat_membrane, _ = Material.objects.get_or_create(code="membrane", defaults={"name": "封口膜", "unit": "张", "material_type": "consumable"})

    # 菜单
    cat, _ = GlobalMenuCategory.objects.get_or_create(device_model=dev_model, name="咖啡", defaults={"sort_order": 1, "is_active": True})
    g_item, _ = GlobalMenuItem.objects.get_or_create(category=cat, name="拿铁咖啡", defaults={"base_price": 1500, "is_active": True})
    tpl, _ = GlobalSkuTemplate.objects.get_or_create(name="大杯/热", defaults={"category": "默认", "default_price_delta": 300, "is_active": True})
    g_sku, _ = GlobalMenuSku.objects.get_or_create(item=g_item, template=tpl, defaults={"price_delta": 300, "is_active": True})

    GlobalSkuIngredient.objects.get_or_create(sku=g_sku, material=mat_milk, defaults={"quantity": 150})
    GlobalSkuIngredient.objects.get_or_create(sku=g_sku, material=mat_bean, defaults={"quantity": 15})
    GlobalSkuIngredient.objects.get_or_create(sku=g_sku, material=mat_cup, defaults={"quantity": 1})

    MenuItem.sync_store_menu(store)
    menu_item = MenuItem.objects.get(store=store, global_item=g_item)
    menu_sku = MenuSku.objects.get(item=menu_item, global_sku=g_sku)

    # 清理相关报警与通知表及防抖锁与测试订单
    DeviceAlarm.objects.filter(device=device).delete()
    NotifyEvent.objects.filter(device=device).delete()
    DeviceBarrelDict.objects.filter(device=device).delete()
    PaymentRecord.objects.filter(order__order_no__in=["TEST_CUP_ALARM_001", "TEST_CUP_LOCK_002"]).delete()
    OrderMain.objects.filter(order_no__in=["TEST_CUP_ALARM_001", "TEST_CUP_LOCK_002"]).delete()
    for k in redis_conn.keys(f"automake:sms_lock:{device.device_sn}:*"):
        redis_conn.delete(k)

    # -------------------------------------------------------------
    # 🧪 测试 1：料桶报警1 (alarm_threshold_1)
    # -------------------------------------------------------------
    print("\n🧪 [Case 1] 测试料桶报警1：达到报警1阈值时触发短信与后台通知")
    b01 = DeviceBarrelDict.objects.create(
        device=device,
        barrel_code="b01",
        material=mat_milk,
        alarm_threshold_1=Decimal('1000.00'),
        alarm_threshold_2=Decimal('200.00'),
        created_by=user
    )

    # 模拟硬件上报 b01 剩余 800ml (低于报警1 1000ml，但高于报警2 200ml)
    raw_payload_1 = {
        "healthy": 1,
        "disconnected": 0,
        "thinP": {"b01": {"v": 800, "a1": 0}},
        "thickP": {},
        "solidP": {},
        "cup": {"paperL": {"a1": 0, "a2": 0}}
    }
    parsed_1 = process_device_status_report(device.device_sn, raw_payload_1)

    # 验证异常已捕获
    assert "barrel.b01.low" in parsed_1["abnormalities"], "未记录 barrel.b01.low 告警！"
    print("   ✓ 已识别料桶余量低异常: ", parsed_1["abnormalities"]["barrel.b01.low"])

    # 验证产生 DeviceAlarm 和 NotifyEvent
    alarm_obj = DeviceAlarm.objects.filter(device=device, alarm_type=DeviceAlarm.ALARM_LOW_MATERIAL).first()
    assert alarm_obj is not None, "未生成 DeviceAlarm 记录！"
    notify_obj = NotifyEvent.objects.filter(device=device, event_type=NotifyEvent.EVENT_DEVICE_ALERT).first()
    assert notify_obj is not None, "未生成 NotifyEvent 后台通知！"
    print(f"   ✓ 成功创建数据库告警: {alarm_obj.detail}")
    print(f"   ✓ 成功创建后台管理员通知: {notify_obj.title} - {notify_obj.content}")

    # 验证由于未达到报警2，物料未停售，Redis 可用库存为 800
    stock_in_redis = int(redis_conn.get(f"automake:stock:{device.device_sn}:fresh_milk") or 0)
    assert stock_in_redis == 800, f"Redis 可用库存应为 800，实际为 {stock_in_redis}"
    print(f"   ✓ Redis 实时可用库存保持为 {stock_in_redis}ml，未停止售卖")
    print("   ✅ [Case 1 通过] 料桶报警1短信与通知机制生效！")

    # -------------------------------------------------------------
    # 🧪 测试 2：料桶报警2 (alarm_threshold_2) - 达到此值相当于物料=0
    # -------------------------------------------------------------
    print("\n🧪 [Case 2] 测试料桶报警2：达到报警2阈值时相当于物料=0，停止售卖")
    # 模拟硬件上报 b01 剩余 180ml (低于报警2 200ml)
    raw_payload_2 = {
        "healthy": 1,
        "disconnected": 0,
        "thinP": {"b01": {"v": 180, "a1": 0}},
        "thickP": {},
        "solidP": {},
        "cup": {"paperL": {"a1": 0, "a2": 0}}
    }
    parsed_2 = process_device_status_report(device.device_sn, raw_payload_2)

    assert "barrel.b01.empty" in parsed_2["abnormalities"], "未记录 barrel.b01.empty 停售告警！"
    print("   ✓ 已识别料桶停售告警: ", parsed_2["abnormalities"]["barrel.b01.empty"])

    # 验证 Redis 可用库存被强制置为 0
    stock_in_redis_2 = int(redis_conn.get(f"automake:stock:{device.device_sn}:fresh_milk") or 0)
    assert stock_in_redis_2 == 0, f"达到报警2阈值时可用库存应为 0，实际为 {stock_in_redis_2}"
    print(f"   ✓ Redis 实时可用库存精准归零 (当前为 {stock_in_redis_2}ml)")

    # 验证下单预检拦截
    cart = [{'item': menu_item.id, 'sku': [menu_sku.id], 'quantity': 1}]
    try:
        precheck_order(store.id, cart, device_sn=device.device_sn)
        assert False, "可用库存为 0 时预检未能拦截！"
    except ValueError as e:
        assert "鲜牛奶" in str(e) and "缺料" in str(e)
        print(f"   ✓ 下单预检成功阻断缺料商品: '{e}'")
    print("   ✅ [Case 2 通过] 料桶报警2停售与物料归零逻辑完全生效！")

    # -------------------------------------------------------------
    # 🧪 测试 3：多料桶独立报警2与可用容量聚合
    # -------------------------------------------------------------
    print("\n🧪 [Case 3] 测试多料桶独立报警2：一桶达到报警2归零，另一桶充足时系统正常放行")
    b02 = DeviceBarrelDict.objects.create(
        device=device,
        barrel_code="b02",
        material=mat_milk,
        alarm_threshold_1=Decimal('1000.00'),
        alarm_threshold_2=Decimal('200.00'),
        created_by=user
    )

    # b01 剩余 150ml (<= 200ml, 归零), b02 剩余 600ml (> 200ml, 可用 600ml)
    raw_payload_3 = {
        "healthy": 1,
        "disconnected": 0,
        "thinP": {
            "b01": {"v": 150, "a1": 0},
            "b02": {"v": 600, "a1": 0}
        },
        "thickP": {},
        "solidP": {},
        "cup": {"paperL": {"a1": 0, "a2": 0}}
    }
    parsed_3 = process_device_status_report(device.device_sn, raw_payload_3)

    stock_in_redis_3 = int(redis_conn.get(f"automake:stock:{device.device_sn}:fresh_milk") or 0)
    assert stock_in_redis_3 == 600, f"b01归零但b02可用时，总可用库存应为 600，实际为 {stock_in_redis_3}"
    print(f"   ✓ 聚合可用库存精准计算: b01(150<=200归零) + b02(600) = {stock_in_redis_3}ml")

    # 配置耗材充足
    DeviceConsumableStock.objects.update_or_create(device=device, code=mat_cup, defaults={"quantity": 50, "warn_level": 20, "stop_sale_level": 5})
    DeviceConsumableStock.objects.update_or_create(device=device, code=mat_lid, defaults={"quantity": 50, "warn_level": 20, "stop_sale_level": 5})
    DeviceConsumableStock.objects.update_or_create(device=device, code=mat_membrane, defaults={"quantity": 50, "warn_level": 20, "stop_sale_level": 5})
    redis_conn.set(f"automake:stock:{device.device_sn}:coffee_bean", "5000")

    # 验证此时允许下单
    res = precheck_order(store.id, cart, device_sn=device.device_sn)
    assert res["ok"] is True
    print("   ✓ 下单预检成功放行正常可售物料")
    print("   ✅ [Case 3 通过] 多料桶聚合与独立报警2阈值逻辑验证通过！")

    # -------------------------------------------------------------
    # 🧪 测试 4：纸杯耗材报警1 (少于20个时报警并通知管理员)
    # -------------------------------------------------------------
    print("\n🧪 [Case 4] 测试耗材报警1：纸杯扣减后少于20个触发报警与NotifyEvent")
    cs_cup, _ = DeviceConsumableStock.objects.update_or_create(
        device=device,
        code=mat_cup,
        defaults={"quantity": 25, "warn_level": 20, "stop_sale_level": 5}
    )
    cs_cup.quantity = 25
    cs_cup.warn_level = 20
    cs_cup.stop_sale_level = 5
    cs_cup.save()

    # 清空之前的 NotifyEvent
    NotifyEvent.objects.filter(device=device, title__contains="耗材").delete()
    redis_conn.delete(f"automake:sms_sent:{device.device_sn}:paperL")
    redis_conn.delete("automake:order_stock_deducted:TEST_CUP_ALARM_001")
    OrderMain.objects.filter(order_no="TEST_CUP_ALARM_001").delete()

    # 创建一个测试订单并模拟出杯扣减 6 个纸杯 (25 - 6 = 19 < 20)
    order_test = OrderMain.objects.create(
        order_no="TEST_CUP_ALARM_001",
        user=user,
        store=store,
        device=device,
        total_amount=1800,
        pay_amount=1800,
        status=OrderMain.STATUS_MAKING
    )
    item_1 = OrderItem.objects.create(
        order=order_test,
        item=menu_item,
        item_name="拿铁",
        unit_price=1800,
        subtotal=10800,
        quantity=6
    )
    item_1.skus.add(menu_sku)

    deduct_order_consumables(order_test)

    cs_cup.refresh_from_db()
    assert cs_cup.quantity == 19, f"扣减后数量应为 19，实际为 {cs_cup.quantity}"
    print(f"   ✓ 纸杯扣减后剩余 {cs_cup.quantity} 个 (< 预警阈值 20)")

    cup_notify = NotifyEvent.objects.filter(device=device, title__contains="耗材余量告警").first()
    assert cup_notify is not None, "纸杯少于 20 个时未产生 NotifyEvent 通知！"
    print(f"   ✓ 成功触发后台预警通知: {cup_notify.title} - {cup_notify.content}")
    order_test.delete()
    print("   ✅ [Case 4 通过] 纸杯少于 20 个报警逻辑验证通过！")

    # -------------------------------------------------------------
    # 🧪 测试 5：纸杯耗材报警2 (少于5个时停止售卖)
    # -------------------------------------------------------------
    print("\n🧪 [Case 5] 测试耗材停售2：纸杯少于5个时停止售卖 (无法下单、无法锁库、菜单售罄)")
    cs_cup.quantity = 4  # 少于 5 个
    cs_cup.save()

    # 5.1 菜单售罄检测
    sold_out_res = calculate_device_sold_out_items(device.device_sn)
    assert menu_item.id in sold_out_res["sold_out_item_ids"], "纸杯少于5个时，商品未在菜单中标记为售罄！"
    print(f"   ✓ 菜单售罄引擎精准将纸杯缺料商品标记为售罄 (sold_out_item_ids: {sold_out_res['sold_out_item_ids']})")

    # 5.2 下单预检拦截
    try:
        precheck_order(store.id, [{'item': menu_item.id, 'sku': [menu_sku.id], 'quantity': 1}], device_sn=device.device_sn)
        assert False, "纸杯少于5个时下单预检未能拦截！"
    except ValueError as e:
        assert "纸大杯" in str(e) and "停售" in str(e)
        print(f"   ✓ 下单预检成功拦截低于停售阈值(5个)的订单: '{e}'")

    # 5.3 支付锁库拦截
    cs_cup.quantity = 5  # 刚好 5 个，但若购买 1 个后将跌至 4 个 (< 5)
    cs_cup.save()

    OrderMain.objects.filter(order_no="TEST_CUP_LOCK_002").delete()
    order_lock = OrderMain.objects.create(
        order_no="TEST_CUP_LOCK_002",
        user=user,
        store=store,
        device=device,
        total_amount=1800,
        pay_amount=1800,
        status=OrderMain.STATUS_PENDING_PAY
    )
    item_2 = OrderItem.objects.create(
        order=order_lock,
        item=menu_item,
        item_name="拿铁",
        unit_price=1800,
        subtotal=1800,
        quantity=1
    )
    item_2.skus.add(menu_sku)

    locked_ok, lock_err, ctx = try_lock_order_inventory(order_lock)
    assert not locked_ok, "购买后余量跌穿5个时锁库应当失败！"
    assert "停售" in lock_err
    print(f"   ✓ 支付前锁库精准阻断扣减后低于5个的订单: '{lock_err}'")
    print("   ✅ [Case 5 通过] 纸杯少于 5 个停止售卖逻辑验证通过！")

    print("\n" + "=" * 75)
    print("🎉 恭喜！【料桶物料字典双级报警与耗材停售保护】全部 5 项测试 100% 通过！")
    print("=" * 75)

if __name__ == '__main__':
    run_tests()
