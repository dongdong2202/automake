"""
设备编号 sn005 菜单用料、料桶编号与物料对应深度测试脚本
"""

import os
import sys
import json
from decimal import Decimal
import django

# 设置 Django 环境
sys.path.insert(0, '/home/ubuntu/autoMachine/automake')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')
django.setup()

from django.utils import timezone
from django_redis import get_redis_connection

from users.models import User
from stores.models import Store
from devices.models import Device, DeviceMaterialStock, DeviceConsumableStock, DeviceBarrelDict
from global_config.models import (
    DeviceModel, GlobalMenuCategory, GlobalMenuItem,
    GlobalSkuTemplate, GlobalMenuSku, GlobalSkuIngredient
)
from menus.models import MenuItem, MenuSku
from inventory.models import Material
from orders.models import OrderMain, OrderItem
from orders.services import precheck_order, create_order, get_redis_stock_key


def setup_sn005_test_environment():
    """
    初始化并配置 sn005 的物料、料桶编号对应及菜单配方数据
    """
    print("=" * 70)
    print("🔧 [步骤 1/4] 初始化设备 sn005、料桶映射与物料字典...")
    print("=" * 70)

    # 1. 基础用户与门店
    user, _ = User.objects.get_or_create(
        username="sn005_tester",
        defaults={"role": "user", "phone": "13800000005"}
    )
    store = Store.objects.filter(name="北京1店").first()
    if not store:
        store, _ = Store.objects.get_or_create(
            code="BJ_STORE_001",
            defaults={"name": "北京1店", "status": Store.STATUS_OPEN, "contact_phone": "13800000001"}
        )
    store.status = Store.STATUS_OPEN
    store.save()

    # 2. 设备 sn005
    device = Device.objects.filter(device_sn="sn005").first()
    if not device:
        dev_model, _ = DeviceModel.objects.get_or_create(
            code="coffee_maker",
            defaults={"name": "智能咖啡茶饮一体机"}
        )
        device, _ = Device.objects.get_or_create(
            device_sn="sn005",
            defaults={
                "device_name": "北京1店设备2",
                "store": store,
                "device_model": dev_model,
                "status": Device.STATUS_ONLINE
            }
        )
    else:
        dev_model = device.device_model
    device.store = store
    device.status = Device.STATUS_ONLINE
    device.save()

    # 3. 创建核心物料 (食材与耗材)
    materials_data = [
        {"name": "意式深烘咖啡豆", "code": "coffee_bean", "material_type": Material.TYPE_SOLID, "unit": "g", "price": Decimal("0.15")},
        {"name": "特级鲜牛奶", "code": "fresh_milk", "material_type": Material.TYPE_THIN, "unit": "ml", "price": Decimal("0.03")},
        {"name": "经典原味糖浆", "code": "syrup", "material_type": Material.TYPE_THICK, "unit": "ml", "price": Decimal("0.05")},
        {"name": "宇治特级抹茶粉", "code": "matcha", "material_type": Material.TYPE_SOLID, "unit": "g", "price": Decimal("0.25")},
        {"name": "高山乌龙茶汤", "code": "tea_oolong", "material_type": Material.TYPE_THIN, "unit": "ml", "price": Decimal("0.02")},
        {"name": "500ml大号纸杯", "code": "paperL", "material_type": Material.TYPE_CUP, "unit": "个", "price": Decimal("0.50")},
        {"name": "350ml中号纸杯", "code": "paperM", "material_type": Material.TYPE_CUP, "unit": "个", "price": Decimal("0.40")},
        {"name": "热饮防烫杯盖", "code": "lid", "material_type": Material.TYPE_CONSUMABLE, "unit": "个", "price": Decimal("0.20")},
        {"name": "食品级封口膜", "code": "membrane", "material_type": Material.TYPE_CONSUMABLE, "unit": "张", "price": Decimal("0.10")},
    ]

    mat_objs = {}
    for m in materials_data:
        obj, _ = Material.objects.get_or_create(
            code=m["code"],
            defaults={
                "name": m["name"],
                "material_type": m["material_type"],
                "unit": m["unit"],
                "price": m["price"]
            }
        )
        mat_objs[m["code"]] = obj

    # 4. 配置料桶字典映射 (DeviceBarrelDict: 料桶编号 <-> 物料编号 <-> 设备 sn005)
    barrel_mapping = [
        {"barrel_code": "b01", "material_code": "coffee_bean", "desc": "1号料桶 -> 意式深烘咖啡豆 (固体料)"},
        {"barrel_code": "b02", "material_code": "fresh_milk", "desc": "2号料桶 -> 特级鲜牛奶 (稀液料)"},
        {"barrel_code": "b03", "material_code": "syrup", "desc": "3号料桶 -> 经典原味糖浆 (稠液料)"},
        {"barrel_code": "b04", "material_code": "matcha", "desc": "4号料桶 -> 宇治特级抹茶粉 (固体料)"},
        {"barrel_code": "b05", "material_code": "tea_oolong", "desc": "5号料桶 -> 高山乌龙茶汤 (稀液料)"},
    ]

    print(f"\n📦 设备 [{device.device_sn}] 料桶编号与物料对应关系：")
    for bm in barrel_mapping:
        bd, _ = DeviceBarrelDict.objects.get_or_create(
            device=device,
            barrel_code=bm["barrel_code"],
            defaults={"material": mat_objs[bm["material_code"]], "created_by": user}
        )
        bd.material = mat_objs[bm["material_code"]]
        bd.save()
        print(f"   料桶编号 [{bd.barrel_code}] ===> 物料: {bd.material.name} ({bd.material.code}) | {bm['desc']}")

    # 5. 配置设备物料库存 (DeviceMaterialStock)
    for bm in barrel_mapping:
        code = bm["material_code"]
        ms, _ = DeviceMaterialStock.objects.get_or_create(
            device=device,
            code=code,
            defaults={
                "name": mat_objs[code],
                "initHight": 100,
                "current_remaining_height": Decimal("85.00"),
                "warn_level": Decimal("10.00"),
                "unit": mat_objs[code].unit
            }
        )
        ms.name = mat_objs[code]
        ms.current_remaining_height = Decimal("85.00")
        ms.save()

    # 6. 配置设备耗材库存 (DeviceConsumableStock)
    for c_code in ["paperL", "paperM", "lid", "membrane"]:
        cs, _ = DeviceConsumableStock.objects.get_or_create(
            device=device,
            code=mat_objs[c_code],
            defaults={
                "init_quantity": 100,
                "quantity": 100,
                "unit": "张" if c_code == "membrane" else "个",
                "warn_level": 15
            }
        )
        cs.quantity = 100
        cs.save()

    # 7. 配置商品与配料用料配方
    print("\n🍵 配置门店菜单商品与精确用料配方：")
    cat_coffee, _ = GlobalMenuCategory.objects.get_or_create(
        name="精品咖啡", defaults={"device_model": dev_model, "sort_order": 1, "is_active": True}
    )
    cat_coffee.device_model = dev_model
    cat_coffee.is_active = True
    cat_coffee.save()

    cat_tea, _ = GlobalMenuCategory.objects.get_or_create(
        name="特调茶饮", defaults={"device_model": dev_model, "sort_order": 2, "is_active": True}
    )
    cat_tea.device_model = dev_model
    cat_tea.is_active = True
    cat_tea.save()

    products_spec = [
        {
            "name": "大师拿铁",
            "category": cat_coffee,
            "base_price": 1800,  # 18.00元
            "sku_name": "大杯/热",
            "price_delta": 0,
            "recipe": [
                {"material": "coffee_bean", "quantity": Decimal("15.00"), "unit": "g"},
                {"material": "fresh_milk", "quantity": Decimal("180.00"), "unit": "ml"},
                {"material": "paperL", "quantity": Decimal("1.00"), "unit": "个"},
                {"material": "lid", "quantity": Decimal("1.00"), "unit": "个"},
            ]
        },
        {
            "name": "特级抹茶拿铁",
            "category": cat_tea,
            "base_price": 2200,  # 22.00元
            "sku_name": "标准/冰",
            "price_delta": 0,
            "recipe": [
                {"material": "matcha", "quantity": Decimal("12.00"), "unit": "g"},
                {"material": "fresh_milk", "quantity": Decimal("200.00"), "unit": "ml"},
                {"material": "syrup", "quantity": Decimal("15.00"), "unit": "ml"},
                {"material": "paperL", "quantity": Decimal("1.00"), "unit": "个"},
                {"material": "lid", "quantity": Decimal("1.00"), "unit": "个"},
            ]
        },
        {
            "name": "高山乌龙奶茶",
            "category": cat_tea,
            "base_price": 1600,  # 16.00元
            "sku_name": "中杯/热",
            "price_delta": 0,
            "recipe": [
                {"material": "tea_oolong", "quantity": Decimal("150.00"), "unit": "ml"},
                {"material": "fresh_milk", "quantity": Decimal("100.00"), "unit": "ml"},
                {"material": "syrup", "quantity": Decimal("10.00"), "unit": "ml"},
                {"material": "paperM", "quantity": Decimal("1.00"), "unit": "个"},
                {"material": "lid", "quantity": Decimal("1.00"), "unit": "个"},
            ]
        },
        {
            "name": "经典美式",
            "category": cat_coffee,
            "base_price": 1200,  # 12.00元
            "sku_name": "标准/热",
            "price_delta": 0,
            "recipe": [
                {"material": "coffee_bean", "quantity": Decimal("18.00"), "unit": "g"},
                {"material": "paperM", "quantity": Decimal("1.00"), "unit": "个"},
                {"material": "lid", "quantity": Decimal("1.00"), "unit": "个"},
            ]
        }
    ]

    configured_menu_items = {}
    for p in products_spec:
        g_item, _ = GlobalMenuItem.objects.get_or_create(
            name=p["name"],
            defaults={"category": p["category"], "base_price": p["base_price"], "is_active": True}
        )
        g_item.category = p["category"]
        g_item.is_active = True
        g_item.save()

        g_tpl, _ = GlobalSkuTemplate.objects.get_or_create(
            name=p["sku_name"],
            defaults={"category": "规格", "default_price_delta": p["price_delta"], "is_active": True}
        )
        g_tpl.is_active = True
        g_tpl.save()

        g_sku, _ = GlobalMenuSku.objects.get_or_create(
            item=g_item,
            template=g_tpl,
            defaults={"price_delta": p["price_delta"], "is_active": True}
        )
        g_sku.is_active = True
        g_sku.save()
        # 清除并重新绑定配料
        GlobalSkuIngredient.objects.filter(sku=g_sku).delete()
        for ing in p["recipe"]:
            GlobalSkuIngredient.objects.create(
                sku=g_sku,
                material=mat_objs[ing["material"]],
                quantity=ing["quantity"]
            )

        # 同步门店菜单
        MenuItem.sync_store_menu(store)
        m_item = MenuItem.objects.get(store=store, global_item=g_item)
        m_item.base_price = p["base_price"]
        m_item.is_active = True
        m_item.save()

        m_sku = MenuSku.objects.get(item=m_item, global_sku=g_sku)
        m_sku.price_delta = p["price_delta"]
        m_sku.is_active = True
        m_sku.save()

        recipe_desc = ", ".join([f"{mat_objs[i['material']].name}: {i['quantity']}{i['unit']}" for i in p["recipe"]])
        print(f"   - 商品: [{m_item.name}] (单价: ¥{m_item.base_price/100:.2f}) | 规格: [{m_sku.global_sku.name}]")
        print(f"     配方用料清单: {recipe_desc}")

        configured_menu_items[p["name"]] = {
            "menu_item": m_item,
            "menu_sku": m_sku,
            "recipe": p["recipe"]
        }

    return user, store, device, mat_objs, configured_menu_items


def set_sn005_redis_stock(stocks_dict):
    """设置 sn005 在 Redis 中的物理库存"""
    r = get_redis_connection("default")
    for mat_code, val in stocks_dict.items():
        key = get_redis_stock_key("sn005", mat_code)
        r.set(key, str(val))
    # 设置设备健康监控快照
    r.set("automake:monitor:snapshot:sn005", json.dumps({"healthy": True, "disconnected": False, "ts": timezone.now().isoformat()}))


def run_comprehensive_tests(user, store, device, mat_objs, items_map):
    """
    运行全方位 7 大场景测试
    """
    r = get_redis_connection("default")
    item_latte = items_map["大师拿铁"]
    item_matcha = items_map["特级抹茶拿铁"]
    item_oolong = items_map["高山乌龙奶茶"]
    item_americano = items_map["经典美式"]

    print("\n" + "=" * 70)
    print("🚀 [步骤 2/4] 开始执行 precheck_order 核心用例严苛测试...")
    print("=" * 70)

    # -------------------------------------------------------------
    # 测试场景 1：正常点单（多商品多规格用料累计与各料桶核算）
    # -------------------------------------------------------------
    print("\n🧪 [测试 1] 多商品组合点餐：2杯大师拿铁 + 3杯特级抹茶拿铁 + 1杯高山乌龙奶茶 (共6杯)")
    # 8. 热饮防烫杯盖: 2 + 3 + 1 = 6.00个
    # 9. 食品级封口膜: 2 + 3 + 1 = 6.00张
    set_sn005_redis_stock({
        "coffee_bean": 1000.0,
        "fresh_milk": 5000.0,
        "syrup": 1000.0,
        "matcha": 500.0,
        "tea_oolong": 3000.0,
        "paperL": 100.0,
        "paperM": 100.0,
        "lid": 200.0,
        "membrane": 200.0,
    })

    cart_items = [
        {"item": item_latte["menu_item"].id, "sku": [item_latte["menu_sku"].id], "quantity": 2},
        {"item": item_matcha["menu_item"].id, "sku": [item_matcha["menu_sku"].id], "quantity": 3},
        {"item": item_oolong["menu_item"].id, "sku": [item_oolong["menu_sku"].id], "quantity": 1},
    ]

    res = precheck_order(store.id, cart_items, device_sn="sn005")
    assert res["ok"] is True
    assert res["device"] == device
    # 价格校验：18.00*2 + 22.00*3 + 16.00*1 = 36 + 66 + 16 = 118.00元 = 11800分
    assert res["total_amount"] == 11800
    assert res["pay_amount"] == 11800
    # 用料清单精准比对
    req = res["required_materials"]
    assert req["coffee_bean"] == Decimal("30.00"), f"咖啡豆计算错误: {req['coffee_bean']}"
    assert req["fresh_milk"] == Decimal("1060.00"), f"鲜牛奶计算错误: {req['fresh_milk']}"
    assert req["syrup"] == Decimal("55.00"), f"糖浆计算错误: {req['syrup']}"
    assert req["matcha"] == Decimal("36.00"), f"抹茶粉计算错误: {req['matcha']}"
    assert req["tea_oolong"] == Decimal("150.00"), f"乌龙茶计算错误: {req['tea_oolong']}"
    assert req["paperL"] == Decimal("5.00"), f"大纸杯计算错误: {req['paperL']}"
    assert req["paperM"] == Decimal("1.00"), f"中纸杯计算错误: {req['paperM']}"
    assert req["lid"] == Decimal("6.00"), f"杯盖计算错误: {req['lid']}"
    assert req["membrane"] == Decimal("6.00"), f"封口膜计算错误: {req['membrane']}"

    # 单杯独立明细 (JSON 列表，不合并)
    per_cups = res["per_cup_materials"]
    assert len(per_cups) == 6, f"单杯列表长度错误: 期望 6，实际 {len(per_cups)}"
    assert per_cups[0]["item_name"] == "大师拿铁"
    assert per_cups[0]["materials"]["paperL"] == Decimal("1.00")
    assert per_cups[0]["materials"]["lid"] == Decimal("1.00")
    assert per_cups[0]["materials"]["membrane"] == Decimal("1.00")

    print("   ✅ [测试 1 通过] 预校验成功！总金额 ¥118.00，8种物料及单杯独立明细 (6杯JSON) 计算 100% 精确！")

    # -------------------------------------------------------------
    # 测试场景 2：4号料桶 (抹茶粉) 缺料精准拦截
    # -------------------------------------------------------------
    print("\n🧪 [测试 2] 4号料桶 (宇治特级抹茶粉) 缺料拦截测试 (需要 36.0g，Redis仅剩 20.0g)")
    set_sn005_redis_stock({
        "coffee_bean": 1000.0,
        "fresh_milk": 5000.0,
        "syrup": 1000.0,
        "matcha": 20.0,  # 缺料！
        "tea_oolong": 3000.0,
        "paperL": 100.0,
        "paperM": 100.0,
        "lid": 200.0,
        "membrane": 200.0,
    })
    try:
        precheck_order(store.id, cart_items, device_sn="sn005")
        raise AssertionError("测试失败：抹茶粉不足时未抛出异常！")
    except ValueError as e:
        err_msg = str(e)
        print(f"   捕获异常信息: {err_msg}")
        assert "宇治特级抹茶粉" in err_msg or "matcha" in err_msg
        assert "剩余可用 20.0" in err_msg
        assert "所需 36.0" in err_msg
        print("   ✅ [测试 2 通过] 成功拦截 4 号料桶缺料，报错信息包含物料中文名、剩余量与需求量！")

    # -------------------------------------------------------------
    # 测试场景 3：2号料桶 (鲜牛奶) 缺料精准拦截
    # -------------------------------------------------------------
    print("\n🧪 [测试 3] 2号料桶 (特级鲜牛奶) 缺料拦截测试 (需要 1060.0ml，Redis仅剩 800.0ml)")
    set_sn005_redis_stock({
        "coffee_bean": 1000.0,
        "fresh_milk": 800.0,  # 缺料！
        "syrup": 1000.0,
        "matcha": 500.0,
        "tea_oolong": 3000.0,
        "paperL": 100.0,
        "paperM": 100.0,
        "lid": 200.0,
        "membrane": 200.0,
    })
    try:
        precheck_order(store.id, cart_items, device_sn="sn005")
        raise AssertionError("测试失败：鲜牛奶不足时未抛出异常！")
    except ValueError as e:
        err_msg = str(e)
        print(f"   捕获异常信息: {err_msg}")
        assert "奶" in err_msg or "fresh_milk" in err_msg
        assert "剩余可用 800.0" in err_msg
        assert "所需 1060.0" in err_msg
        print("   ✅ [测试 3 通过] 成功拦截 2 号料桶鲜牛奶缺料！")

    # -------------------------------------------------------------
    # 测试场景 4：耗材纸杯 (500ml大号纸杯) 缺料精准拦截
    # -------------------------------------------------------------
    print("\n🧪 [测试 4] 耗材纸杯 (500ml大号纸杯) 缺料拦截测试 (需要 5.0个，Redis仅剩 2.0个)")
    set_sn005_redis_stock({
        "coffee_bean": 1000.0,
        "fresh_milk": 5000.0,
        "syrup": 1000.0,
        "matcha": 500.0,
        "tea_oolong": 3000.0,
        "paperL": 2.0,  # 缺料！
        "paperM": 100.0,
        "lid": 200.0,
        "membrane": 200.0,
    })
    try:
        precheck_order(store.id, cart_items, device_sn="sn005")
        raise AssertionError("测试失败：大纸杯不足时未抛出异常！")
    except ValueError as e:
        err_msg = str(e)
        print(f"   捕获异常信息: {err_msg}")
        assert "杯" in err_msg or "paperL" in err_msg
        assert "剩余可用 2.0" in err_msg
        assert "所需 5.0" in err_msg
        print("   ✅ [测试 4 通过] 成功拦截耗材大号纸杯不足！")

    # -------------------------------------------------------------
    # 测试场景 5：设备在途待制作订单 (In-flight Unproduced) 物料扣除测试
    # -------------------------------------------------------------
    print("\n🧪 [测试 5] 在途订单物料占用测试 (物理库存 1200ml 牛奶，在途占用 280ml，新订单需 1060ml)")
    # 物理库存: 1200ml
    set_sn005_redis_stock({
        "coffee_bean": 1000.0,
        "fresh_milk": 1200.0,
        "syrup": 1000.0,
        "matcha": 500.0,
        "tea_oolong": 3000.0,
        "paperL": 100.0,
        "paperM": 100.0,
        "lid": 200.0,
        "membrane": 200.0,
    })

    # 创建一个已支付待制作的在途订单，包含 1 杯拿铁 (180ml) 和 1 杯高山乌龙奶茶 (100ml) -> 共占用 280ml 牛奶
    in_flight_items = [
        {"item": item_latte["menu_item"].id, "sku": [item_latte["menu_sku"].id], "quantity": 1},
        {"item": item_oolong["menu_item"].id, "sku": [item_oolong["menu_sku"].id], "quantity": 1},
    ]
    in_flight_order = create_order(user, store.id, in_flight_items, device_sn="sn005")
    in_flight_order.status = OrderMain.STATUS_PAID  # pending_dispense 在途制作中
    in_flight_order.save()

    # 此时设备在途已占用牛奶 280ml，有效可用库存 = 1200 - 280 = 920ml。
    # 尝试下 6 杯组合单 (需要 1060ml 鲜牛奶 > 有效可用 920ml)：
    try:
        precheck_order(store.id, cart_items, device_sn="sn005")
        raise AssertionError("测试失败：未扣除在途订单物料占用！")
    except ValueError as e:
        err_msg = str(e)
        print(f"   捕获异常信息: {err_msg}")
        assert "奶" in err_msg or "fresh_milk" in err_msg
        assert "剩余可用 920.0" in err_msg
        assert "所需 1060.0" in err_msg
        print("   ✅ [测试 5.1 通过] 在途制作中订单成功扣除有效可用物料（1200 - 280 = 920ml）并准确拦截！")

    # 当在途订单制作完成出杯 (STATUS_DONE)
    in_flight_order.status = OrderMain.STATUS_DONE
    in_flight_order.save()

    # 此时在途释放，有效可用恢复为 1200ml，再次预校验 6 杯组合单应顺利通过
    res_after_done = precheck_order(store.id, cart_items, device_sn="sn005")
    assert res_after_done["ok"] is True
    print("   ✅ [测试 5.2 通过] 在途订单出杯完成后占用释放，预校验恢复正常通过！")

    # -------------------------------------------------------------
    # 测试场景 6：设备状态（离线 / 监控健康异常）防护测试
    # -------------------------------------------------------------
    print("\n🧪 [测试 6] 设备状态异常防护测试")
    # 1. 设备设为离线
    device.status = Device.STATUS_OFFLINE
    device.save()
    try:
        precheck_order(store.id, cart_items, device_sn="sn005")
        raise AssertionError("测试失败：设备离线时未拦截！")
    except ValueError as e:
        assert "离线状态" in str(e)
        print("   ✅ [测试 6.1 通过] 成功拦截离线设备点餐！")

    # 恢复在线，但模拟 Redis 监控快照异常
    device.status = Device.STATUS_ONLINE
    device.save()
    r.set("automake:monitor:snapshot:sn005", json.dumps({"healthy": False, "disconnected": True}))
    try:
        precheck_order(store.id, cart_items, device_sn="sn005")
        raise AssertionError("测试失败：设备健康快照异常时未拦截！")
    except ValueError as e:
        assert "状态异常" in str(e)
        print("   ✅ [测试 6.2 通过] 成功拦截健康快照异常设备点餐！")

    # 恢复健康快照
    r.set("automake:monitor:snapshot:sn005", json.dumps({"healthy": True, "disconnected": False}))

    # -------------------------------------------------------------
    # 测试场景 7：边界条件防护（缺失入参、门店不匹配、超额数量）
    # -------------------------------------------------------------
    print("\n🧪 [测试 7] 业务与入参边界条件防护测试")
    # 未传 device_sn
    try:
        precheck_order(store.id, cart_items, device_sn="")
        raise AssertionError("未传 device_sn 未拦截")
    except ValueError as e:
        assert "请传入点餐设备编号" in str(e)
        print("   ✅ [测试 7.1 通过] 成功拦截缺失 device_sn！")

    # 设备不存在
    try:
        precheck_order(store.id, cart_items, device_sn="sn_not_exist_999")
        raise AssertionError("不存在的 device_sn 未拦截")
    except ValueError as e:
        assert "不存在" in str(e)
        print("   ✅ [测试 7.2 通过] 成功拦截不存在的设备！")

    # 数量超限 (单笔 > 20)
    over_limit_items = [{"item": item_latte["menu_item"].id, "sku": [item_latte["menu_sku"].id], "quantity": 25}]
    try:
        precheck_order(store.id, over_limit_items, device_sn="sn005")
        raise AssertionError("数量 > 20 未拦截")
    except ValueError as e:
        assert "单笔订单数量不能大于 20" in str(e)
        print("   ✅ [测试 7.3 通过] 成功拦截单笔超过 20 杯！")

    # 数量小于等于 0
    zero_items = [{"item": item_latte["menu_item"].id, "sku": [item_latte["menu_sku"].id], "quantity": 0}]
    try:
        precheck_order(store.id, zero_items, device_sn="sn005")
        raise AssertionError("数量 <= 0 未拦截")
    except ValueError as e:
        assert "数量不能小于0" in str(e)
        print("   ✅ [测试 7.4 通过] 成功拦截数量为 0！")

    # -------------------------------------------------------------
    # 测试场景 8：热饮配置塑料杯自动纠正为纸杯、杯盖及封口膜自动补齐
    # -------------------------------------------------------------
    print("\n🧪 [测试 8] 耗材规则纠偏测试：热饮塑料杯纠正为纸杯 + 纸杯配杯盖 + 全杯型配封口膜")
    from global_config.models import GlobalMenuCategory, GlobalMenuItem, GlobalSkuTemplate, GlobalMenuSku, GlobalSkuIngredient
    cat_spec, _ = GlobalMenuCategory.objects.get_or_create(
        name="季节特调", defaults={"device_model": device.device_model, "sort_order": 3, "is_active": True}
    )
    cat_spec.device_model = device.device_model
    cat_spec.is_active = True
    cat_spec.save()

    item_hot_coco, _ = GlobalMenuItem.objects.get_or_create(
        name="热可可牛奶", defaults={"category": cat_spec, "base_price": 1800, "is_active": True}
    )
    item_hot_coco.category = cat_spec
    item_hot_coco.is_active = True
    item_hot_coco.save()

    tpl_hot_l, _ = GlobalSkuTemplate.objects.get_or_create(
        name="大杯/热", defaults={"category": "规格", "default_price_delta": 0, "is_active": True}
    )
    tpl_hot_l.is_active = True
    tpl_hot_l.save()

    sku_hot_coco, _ = GlobalMenuSku.objects.get_or_create(
        item=item_hot_coco, template=tpl_hot_l, defaults={"price_delta": 0, "is_active": True}
    )
    sku_hot_coco.is_active = True
    sku_hot_coco.save()

    # 故意在热饮中配置了 plasticL (塑料大杯)，且未配置 lid (杯盖) 与 membrane (封口膜)
    GlobalSkuIngredient.objects.filter(sku=sku_hot_coco).delete()
    GlobalSkuIngredient.objects.create(sku=sku_hot_coco, material=mat_objs["fresh_milk"], quantity=Decimal("250.00"))
    mat_plasticL, _ = Material.objects.get_or_create(code="plasticL", defaults={"name": "塑料大杯", "material_type": Material.TYPE_CUP, "unit": "个", "price": Decimal("0.50")})
    GlobalSkuIngredient.objects.create(sku=sku_hot_coco, material=mat_plasticL, quantity=Decimal("1.00"))

    MenuItem.sync_store_menu(store)
    m_coco_item = MenuItem.objects.get(store=store, global_item=item_hot_coco)
    m_coco_sku = MenuSku.objects.get(item=m_coco_item, global_sku=sku_hot_coco)

    # 购买 2 杯热可可牛奶
    coco_order_items = [{"item": m_coco_item.id, "sku": [m_coco_sku.id], "quantity": 2}]
    res_coco = precheck_order(store.id, coco_order_items, device_sn="sn005")
    assert res_coco["ok"] is True

    # 校验单杯独立明细 (JSON 列表)
    coco_cups = res_coco["per_cup_materials"]
    assert len(coco_cups) == 2, f"期望 2 杯独立明细，实际 {len(coco_cups)}"
    for cup in coco_cups:
        assert cup["item_name"] == "热可可牛奶"
        assert cup["is_hot"] is True
        c_mats = cup["materials"]
        assert "plasticL" not in c_mats, "热饮塑料杯未被纠正！"
        assert c_mats.get("paperL") == Decimal("1.00"), "热饮未自动转换为纸杯 paperL！"
        assert c_mats.get("lid") == Decimal("1.00"), "纸杯未自动配备杯盖 lid！"
        assert c_mats.get("membrane") == Decimal("1.00"), "未自动配备封口膜 membrane！"
        assert c_mats.get("fresh_milk") == Decimal("250.00")

    print("   ✅ [测试 8.1 通过] 热饮塑料杯成功自动纠正为纸杯 paperL！")
    print("   ✅ [测试 8.2 通过] 纸杯自动成套配备杯盖 lid！")
    print("   ✅ [测试 8.3 通过] 每杯饮品自动配备封口膜 membrane！")
    print("   ✅ [测试 8.4 通过] 2 杯饮品独立返回 2 个 JSON 元素，未合并物料！")

    print("\n" + "=" * 70)
    print("🎉 [步骤 3/4] 针对设备 sn005 的所有 8 大核心测试场景 100% 全部通过！")
    print("=" * 70)


if __name__ == "__main__":
    user, store, device, mat_objs, items_map = setup_sn005_test_environment()
    run_comprehensive_tests(user, store, device, mat_objs, items_map)
