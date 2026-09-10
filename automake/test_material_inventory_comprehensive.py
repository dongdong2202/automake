"""
test_material_inventory_comprehensive.py
============================================================
物料检测有效性与多料桶聚合深度测试自动化套件

涵盖核心场景：
1. 多料桶同物料存储与上位机定时上报聚合
2. 跨料桶供给计算（单桶不足，合并充足）
3. 多料桶合并缺料精准拦截
4. 料桶物理损坏 (a1=1) 过滤与可用容积剔除
5. MySQL 杯型耗材独立管理与边界清零拦截
6. 耗材成套缺失（缺盖、缺膜）精准拦截
7. 冷热饮杯型自动纠偏与库存联动
8. 在途待制作订单动态占用与并发防超卖
9. 制作完成物理扣减与未制作退款放库生命周期闭环
10. 设备离线、整机异常、缓存丢失与非法输入鲁棒性
============================================================
"""

import os
import sys
import json
from decimal import Decimal
import django

# 设置 Django 运行环境
sys.path.insert(0, '/home/ubuntu/autoMachine/automake')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')
django.setup()

from django.utils import timezone
from django_redis import get_redis_connection

from users.models import User
from stores.models import Store
from devices.models import (
    Device, DeviceBarrelDict,
    DeviceConsumableStock, DeviceMaterialStock
)
from inventory.models import Material
from global_config.models import (
    DeviceModel,
    GlobalMenuCategory, GlobalMenuItem,
    GlobalSkuTemplate, GlobalMenuSku, GlobalSkuIngredient
)
from menus.models import MenuItem, MenuSku
from orders.models import OrderMain, OrderItem, ProductionTask
from orders.services import (
    precheck_order, create_order, update_order_status,
    calculate_unproduced_materials_for_device,
    restore_order_inventory, deduct_order_consumables,
    get_redis_stock_key
)
from monitor.services import (
    process_device_status_report, parse_device_status_payload,
    update_device_status_to_redis
)


class ComprehensiveMaterialTester:
    def __init__(self):
        self.device_sn = "SN_INV_TEST_001"
        self.store_code = "STORE_INV_TEST"
        self.redis = get_redis_connection("default")
        self.setup_environment()

    def setup_environment(self):
        print("\n" + "=" * 75)
        print("🔧 [初始化] 正在配置测试设备、多料桶字典、物料与菜单配方...")
        print("=" * 75)

        # 1. 创建测试用户
        self.user, _ = User.objects.get_or_create(
            username="inv_tester_user",
            defaults={"phone": "13900008888", "role": "user"}
        )

        # 2. 创建测试门店
        self.store, _ = Store.objects.get_or_create(
            code=self.store_code,
            defaults={
                "name": "物料测试自营店",
                "status": Store.STATUS_OPEN,
                "contact_phone": "13900008888"
            }
        )
        self.store.status = Store.STATUS_OPEN
        self.store.save()

        # 3. 创建测试设备
        self.dev_model, _ = DeviceModel.objects.get_or_create(
            code="coffee_master_v3",
            defaults={"name": "全自动多料桶咖啡机器人"}
        )
        self.device, _ = Device.objects.get_or_create(
            device_sn=self.device_sn,
            defaults={
                "device_name": "物料测试机01",
                "store": self.store,
                "device_model": self.dev_model,
                "status": Device.STATUS_ONLINE
            }
        )
        self.device.store = self.store
        self.device.device_model = self.dev_model
        self.device.status = Device.STATUS_ONLINE
        self.device.save()

        # 4. 创建基础物料
        self.mat_milk, _ = Material.objects.get_or_create(
            code="fresh_milk",
            defaults={"name": "特级鲜牛奶", "material_type": Material.TYPE_THIN, "unit": "ml", "price": Decimal("0.05")}
        )
        self.mat_bean, _ = Material.objects.get_or_create(
            code="coffee_bean",
            defaults={"name": "阿拉比卡咖啡豆", "material_type": Material.TYPE_SOLID, "unit": "g", "price": Decimal("0.20")}
        )
        self.mat_syrup, _ = Material.objects.get_or_create(
            code="vanilla_syrup",
            defaults={"name": "香草风味糖浆", "material_type": Material.TYPE_THICK, "unit": "ml", "price": Decimal("0.08")}
        )
        self.mat_paper_L, _ = Material.objects.get_or_create(
            code="paperL",
            defaults={"name": "500ml大号纸杯", "material_type": Material.TYPE_CUP, "unit": "个", "price": Decimal("0.50")}
        )
        self.mat_paper_M, _ = Material.objects.get_or_create(
            code="paperM",
            defaults={"name": "350ml中号纸杯", "material_type": Material.TYPE_CUP, "unit": "个", "price": Decimal("0.40")}
        )
        self.mat_plastic_L, _ = Material.objects.get_or_create(
            code="plasticL",
            defaults={"name": "500ml大号塑料冷饮杯", "material_type": Material.TYPE_CUP, "unit": "个", "price": Decimal("0.45")}
        )
        self.mat_lid, _ = Material.objects.get_or_create(
            code="lid",
            defaults={"name": "防烫密封杯盖", "material_type": Material.TYPE_CONSUMABLE, "unit": "个", "price": Decimal("0.20")}
        )
        self.mat_membrane, _ = Material.objects.get_or_create(
            code="membrane",
            defaults={"name": "食品级封口膜", "material_type": Material.TYPE_CONSUMABLE, "unit": "张", "price": Decimal("0.10")}
        )

        # 5. 配置关键多料桶字典 DeviceBarrelDict (b01 和 b02 均为鲜牛奶)
        DeviceBarrelDict.objects.filter(device=self.device).delete()
        self.barrel_b01 = DeviceBarrelDict.objects.create(
            device=self.device, barrel_code="b01", material=self.mat_milk, created_by=self.user
        )
        self.barrel_b02 = DeviceBarrelDict.objects.create(
            device=self.device, barrel_code="b02", material=self.mat_milk, created_by=self.user
        )
        self.barrel_b03 = DeviceBarrelDict.objects.create(
            device=self.device, barrel_code="b03", material=self.mat_bean, created_by=self.user
        )
        self.barrel_b09 = DeviceBarrelDict.objects.create(
            device=self.device, barrel_code="b09", material=self.mat_syrup, created_by=self.user
        )

        print(f"   ✓ 设备 [{self.device.device_sn}] 料桶映射已就绪：")
        print(f"     - [b01] -> 鲜牛奶 (fresh_milk) [多桶1]")
        print(f"     - [b02] -> 鲜牛奶 (fresh_milk) [多桶2]")
        print(f"     - [b03] -> 咖啡豆 (coffee_bean)")
        print(f"     - [b09] -> 香草糖浆 (vanilla_syrup)")

        # 6. 配置商品与配方
        category, _ = GlobalMenuCategory.objects.get_or_create(
            name="测试咖啡分类", device_model=self.dev_model, defaults={"label": "咖啡", "sort_order": 1}
        )
        g_item, _ = GlobalMenuItem.objects.get_or_create(
            name="经典测试拿铁",
            defaults={
                "category": category,
                "base_price": 10,
                "is_active": True
            }
        )
        tpl_L, _ = GlobalSkuTemplate.objects.get_or_create(
            category="杯型", name="大杯热饮",
            defaults={"default_price_delta": 0}
        )
        self.g_sku_L, _ = GlobalMenuSku.objects.get_or_create(
            item=g_item, template=tpl_L,
            defaults={"price_delta": 0, "is_active": True}
        )
        GlobalSkuIngredient.objects.filter(sku=self.g_sku_L).delete()
        # 配方：咖啡豆 15g, 鲜牛奶 150ml
        GlobalSkuIngredient.objects.create(sku=self.g_sku_L, material=self.mat_bean, quantity=Decimal("15.00"), unit="g")
        GlobalSkuIngredient.objects.create(sku=self.g_sku_L, material=self.mat_milk, quantity=Decimal("150.00"), unit="ml")

        # 同步门店商品
        MenuItem.sync_store_menu(self.store)
        self.menu_item = MenuItem.objects.get(store=self.store, global_item=g_item)
        self.menu_item.is_active = True
        self.menu_item.save()

        self.menu_sku_L = MenuSku.objects.get(item=self.menu_item, global_sku=self.g_sku_L)
        self.menu_sku_L.is_active = True
        self.menu_sku_L.save()

        print(f"   ✓ 菜单就绪：[{self.menu_item.name}] - 规格 [大杯热饮]")
        print(f"     配方用料：阿拉比卡咖啡豆 15g + 特级鲜牛奶 150ml (系统自动成套配备 500ml大纸杯 + 杯盖 + 封口膜)")

    def report_hardware_status(self, thinP_data=None, thickP_data=None, solidP_data=None, cups_data=None, healthy=1, disconnected=0):
        """模拟上位机向系统上报硬件状态报文"""
        payload = {
            "healthy": healthy,
            "disconnected": disconnected,
            "thinP": thinP_data or {
                "b01": {"v": 2000, "a1": 0},
                "b02": {"v": 2000, "a1": 0}
            },
            "thickP": thickP_data or {
                "b09": {"v": 1000, "a1": 0}
            },
            "solidP": solidP_data or {
                "b03": {"v": 1000, "a1": 0}
            },
            "cup": cups_data or {
                "paperL": {"a1": 0, "a2": 0},
                "paperM": {"a1": 0, "a2": 0},
                "lid": {"a1": 0, "a2": 0},
                "membrane": {"a1": 0, "a2": 0}
            }
        }
        return process_device_status_report(self.device_sn, payload)

    def set_mysql_consumables(self, paperL=100, paperM=100, plasticL=100, lid=100, membrane=100):
        """设置 MySQL 中的耗材库存 (DeviceConsumableStock)"""
        mats = {
            "paperL": (self.mat_paper_L, paperL, '个'),
            "paperM": (self.mat_paper_M, paperM, '个'),
            "plasticL": (self.mat_plastic_L, plasticL, '个'),
            "lid": (self.mat_lid, lid, '个'),
            "membrane": (self.mat_membrane, membrane, '张')
        }
        for code, (mat_obj, qty, unit) in mats.items():
            cs, _ = DeviceConsumableStock.objects.get_or_create(
                device=self.device,
                code=mat_obj,
                defaults={"quantity": qty, "init_quantity": 100, "unit": unit, "warn_level": 10}
            )
            cs.quantity = qty
            cs.save(update_fields=['quantity', 'updated_at'])

    def clean_unproduced_orders(self):
        """清理已有的在途待制作测试订单，避免测试间干扰"""
        OrderMain.objects.filter(
            device=self.device,
            status__in=[OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING]
        ).update(status=OrderMain.STATUS_CANCELLED)


    # =========================================================================
    # 测试用例执行函数集 (14 大场景)
    # =========================================================================

    def test_01_multi_barrel_normal_aggregation(self):
        """T01: 多料桶同物料正常聚合与供给（b01 300ml + b02 500ml = 800ml，点单需 150ml）"""
        print("\n🧪 [T01] 测试多料桶同物料正常聚合与供给")
        self.set_mysql_consumables(paperL=50, lid=50, membrane=50)
        self.clean_unproduced_orders()

        # 上位机上报：b01=300ml, b02=500ml 鲜牛奶
        self.report_hardware_status(thinP_data={
            "b01": {"v": 300, "a1": 0},
            "b02": {"v": 500, "a1": 0}
        })

        # 验证 Redis 聚合
        stock_milk = float(self.redis.get(get_redis_stock_key(self.device_sn, "fresh_milk")))
        assert stock_milk == 800.0, f"Redis 鲜奶聚合错误，期望 800.0，实际 {stock_milk}"

        # 点单 1 杯大杯拿铁（需 150ml 鲜奶）
        cart = [{"item": self.menu_item.id, "sku": [self.menu_sku_L.id], "quantity": 1}]
        res = precheck_order(self.store.id, cart, device_sn=self.device_sn)
        assert res["ok"] is True
        print(f"   ✅ [T01 通过] 多料桶聚合成功 (300+500={stock_milk}ml)，订单需 150ml 顺利放行")

    def test_02_cross_barrel_supply(self):
        """T02: 跨料桶供给测试（单桶均不足，但两桶合并充足）"""
        print("\n🧪 [T02] 测试跨料桶供给（单桶均不足，但两桶合并充足）")
        self.set_mysql_consumables(paperL=50, lid=50, membrane=50)
        self.clean_unproduced_orders()

        # 上位机上报：b01=100ml (<150), b02=100ml (<150)，合并 200ml (>150)
        self.report_hardware_status(thinP_data={
            "b01": {"v": 100, "a1": 0},
            "b02": {"v": 100, "a1": 0}
        })

        stock_milk = float(self.redis.get(get_redis_stock_key(self.device_sn, "fresh_milk")))
        assert stock_milk == 200.0

        cart = [{"item": self.menu_item.id, "sku": [self.menu_sku_L.id], "quantity": 1}]
        res = precheck_order(self.store.id, cart, device_sn=self.device_sn)
        assert res["ok"] is True
        print(f"   ✅ [T02 通过] 单桶 100ml 均不足，合并 200ml > 150ml 跨桶供给校验放行")

    def test_03_multi_barrel_shortage_interception(self):
        """T03: 多料桶合计缺料精准拦截（两桶合并后仍不足以制作）"""
        print("\n🧪 [T03] 测试多料桶合计缺料精准拦截")
        self.set_mysql_consumables(paperL=50, lid=50, membrane=50)
        self.clean_unproduced_orders()

        # 上位机上报：b01=60ml, b02=70ml，合并 130ml (<150ml，缺 20ml)
        self.report_hardware_status(thinP_data={
            "b01": {"v": 60, "a1": 0},
            "b02": {"v": 70, "a1": 0}
        })

        cart = [{"item": self.menu_item.id, "sku": [self.menu_sku_L.id], "quantity": 1}]
        try:
            precheck_order(self.store.id, cart, device_sn=self.device_sn)
            assert False, "未能拦截缺料异常！"
        except ValueError as e:
            err_msg = str(e)
            assert "缺料" in err_msg or "不足" in err_msg
            assert "130.0" in err_msg and "150.0" in err_msg
            print(f"   ✅ [T03 通过] 成功拦截多料桶合计缺料！报错提示: '{err_msg}'")

    def test_04_multi_barrel_one_empty_barrel(self):
        """T04: 部分料桶空桶 (0ml) 但其他料桶充足"""
        print("\n🧪 [T04] 测试部分料桶空桶 (0ml) 供给")
        self.set_mysql_consumables(paperL=50, lid=50, membrane=50)
        self.clean_unproduced_orders()

        # b01 空桶 0ml，b02 正常 600ml
        self.report_hardware_status(thinP_data={
            "b01": {"v": 0, "a1": 0},
            "b02": {"v": 600, "a1": 0}
        })

        cart = [{"item": self.menu_item.id, "sku": [self.menu_sku_L.id], "quantity": 1}]
        res = precheck_order(self.store.id, cart, device_sn=self.device_sn)
        assert res["ok"] is True
        print("   ✅ [T04 通过] 一桶为空 (0ml) 但另一桶充足时系统正常放行")

    def test_05_damaged_barrel_exclusion(self):
        """T05: 料桶物理损坏异常 (a1=1) 过滤与可用容积剔除拦截"""
        print("\n🧪 [T05] 测试料桶物理损坏异常 (a1=1) 过滤剔除与拦截")
        self.set_mysql_consumables(paperL=50, lid=50, membrane=50)
        self.clean_unproduced_orders()

        # b01 虽有 1000ml 但模块损坏 (a1=1)，b02 正常仅剩 50ml
        self.report_hardware_status(thinP_data={
            "b01": {"v": 1000, "a1": 1},
            "b02": {"v": 50, "a1": 0}
        })

        # 验证 Redis 可用库存剔除了损坏料桶 b01，仅计入 b02 的 50ml
        stock_milk = float(self.redis.get(get_redis_stock_key(self.device_sn, "fresh_milk")))
        assert stock_milk == 50.0, f"损坏料桶未被剔除！Redis 鲜奶库存为 {stock_milk}，期望 50.0"

        cart = [{"item": self.menu_item.id, "sku": [self.menu_sku_L.id], "quantity": 1}]

        # 防御层 1：料桶损坏导致整机健康快照标记为异常，直接在整机状态层被拦截
        try:
            precheck_order(self.store.id, cart, device_sn=self.device_sn)
            assert False, "Layer 1 未能拦截料桶损坏状态！"
        except ValueError as e:
            assert "状态异常" in str(e) or "故障" in str(e)
            print(f"   ✓ [Layer 1 硬件故障层生效] 料桶损坏拦截: '{e}'")

        # 防御层 2：即使设备快照标记为正常，由于损坏料桶容量被剔除，可用仅剩 50ml，仍在物料层精准拦截
        self.device.status = Device.STATUS_ONLINE
        self.device.save()
        snapshot_data = json.loads(self.redis.get(f"automake:monitor:snapshot:{self.device_sn}"))
        snapshot_data["healthy"] = True
        snapshot_data["disconnected"] = False
        self.redis.set(f"automake:monitor:snapshot:{self.device_sn}", json.dumps(snapshot_data))

        try:
            precheck_order(self.store.id, cart, device_sn=self.device_sn)
            assert False, "Layer 2 未能拦截可用余量不足！"
        except ValueError as e:
            err_msg = str(e)
            assert "50.0" in err_msg and "150.0" in err_msg
            print(f"   ✓ [Layer 2 物料余量层生效] 损坏料桶 (1000ml, a1=1) 容积剔除，可用仅 50ml，成功拦截！提示: '{err_msg}'")

        # 恢复健康快照
        self.report_hardware_status(healthy=1)
        print("   ✅ [T05 通过] 料桶损坏异常的双重安全防御（硬件状态层 + 物料可用层）全部验证生效！")

    def test_06_mysql_consumables_sufficient(self):
        """T06: MySQL 耗材（纸杯、杯盖、封口膜）充足正常放行"""
        print("\n🧪 [T06] 测试 MySQL 耗材（纸杯、杯盖、封口膜）充足正常放行")
        self.clean_unproduced_orders()
        self.report_hardware_status()  # 食材充足
        self.set_mysql_consumables(paperL=30, lid=30, membrane=30)

        cart = [{"item": self.menu_item.id, "sku": [self.menu_sku_L.id], "quantity": 2}]
        res = precheck_order(self.store.id, cart, device_sn=self.device_sn)
        assert res["ok"] is True
        assert res["required_materials"]["paperL"] == Decimal("2.00")
        assert res["required_materials"]["lid"] == Decimal("2.00")
        assert res["required_materials"]["membrane"] == Decimal("2.00")
        print("   ✅ [T06 通过] MySQL 耗材充足，成套纸杯、杯盖、封口膜校验均通过")

    def test_07_mysql_consumables_boundary_zero(self):
        """T07: MySQL 纸杯边界售罄（库存正好为 0 精准拦截）"""
        print("\n🧪 [T07] 测试 MySQL 纸杯边界售罄（库存为 0 精准拦截）")
        self.clean_unproduced_orders()
        self.report_hardware_status()
        self.set_mysql_consumables(paperL=0, lid=50, membrane=50)

        cart = [{"item": self.menu_item.id, "sku": [self.menu_sku_L.id], "quantity": 1}]
        try:
            precheck_order(self.store.id, cart, device_sn=self.device_sn)
            assert False, "纸杯为 0 未能拦截！"
        except ValueError as e:
            err_msg = str(e)
            assert ("纸" in err_msg and "杯" in err_msg) or "paperL" in err_msg
            assert "0.0个" in err_msg and "1.0个" in err_msg
            print(f"   ✅ [T07 通过] 纸杯为 0 精准拦截！提示: '{err_msg}'")

    def test_08_mysql_consumables_missing_lid(self):
        """T08: 成套耗材缺失测试（有纸杯有封口膜，但杯盖 lid=0）"""
        print("\n🧪 [T08] 测试成套耗材缺失（有纸杯有封口膜，但杯盖 lid=0）")
        self.clean_unproduced_orders()
        self.report_hardware_status()
        self.set_mysql_consumables(paperL=50, lid=0, membrane=50)

        cart = [{"item": self.menu_item.id, "sku": [self.menu_sku_L.id], "quantity": 1}]
        try:
            precheck_order(self.store.id, cart, device_sn=self.device_sn)
            assert False, "杯盖为 0 未能拦截！"
        except ValueError as e:
            err_msg = str(e)
            assert "杯盖" in err_msg or "lid" in err_msg
            print(f"   ✅ [T08 通过] 缺杯盖精准拦截！提示: '{err_msg}'")

    def test_09_mysql_consumables_missing_membrane(self):
        """T09: 成套耗材缺失测试（有纸杯有杯盖，但封口膜 membrane=0）"""
        print("\n🧪 [T09] 测试成套耗材缺失（有纸杯有杯盖，但封口膜 membrane=0）")
        self.clean_unproduced_orders()
        self.report_hardware_status()
        self.set_mysql_consumables(paperL=50, lid=50, membrane=0)

        cart = [{"item": self.menu_item.id, "sku": [self.menu_sku_L.id], "quantity": 1}]
        try:
            precheck_order(self.store.id, cart, device_sn=self.device_sn)
            assert False, "封口膜为 0 未能拦截！"
        except ValueError as e:
            err_msg = str(e)
            assert "封口膜" in err_msg or "membrane" in err_msg
            print(f"   ✅ [T09 通过] 缺封口膜精准拦截！提示: '{err_msg}'")

    def test_10_hot_cold_cup_correction_linkage(self):
        """T10: 冷热饮耗材纠偏与库存联动（热饮塑料杯纠偏为纸杯）"""
        print("\n🧪 [T10] 测试冷热饮耗材纠偏与库存联动")
        self.clean_unproduced_orders()
        self.report_hardware_status()
        
        # 塑料杯库存充裕 (50个)，但纸杯 paperL=0
        self.set_mysql_consumables(paperL=0, plasticL=50, lid=50, membrane=50)

        cart = [{"item": self.menu_item.id, "sku": [self.menu_sku_L.id], "quantity": 1}]
        try:
            precheck_order(self.store.id, cart, device_sn=self.device_sn)
            assert False, "热饮未能纠偏检测纸杯缺料！"
        except ValueError as e:
            err_msg = str(e)
            assert ("纸" in err_msg and "杯" in err_msg) or "paperL" in err_msg
            print(f"   ✅ [T10 通过] 热饮自动纠偏为纸杯并成功触发缺料拦截！提示: '{err_msg}'")

    def test_11_in_flight_committed_order_anti_overselling(self):
        """T11: 在途待制作订单动态占用与并发防超卖"""
        print("\n🧪 [T11] 测试在途待制作订单动态占用与并发防超卖")
        self.clean_unproduced_orders()
        self.report_hardware_status(thinP_data={"b01": {"v": 200, "a1": 0}, "b02": {"v": 200, "a1": 0}}) # 鲜奶 400ml
        self.set_mysql_consumables(paperL=2, lid=10, membrane=10) # 纸杯仅 2 个

        cart_1 = [{"item": self.menu_item.id, "sku": [self.menu_sku_L.id], "quantity": 1}]
        cart_2 = [{"item": self.menu_item.id, "sku": [self.menu_sku_L.id], "quantity": 2}]

        # 1. 模拟已支付订单 A（锁定 1 个纸杯 + 150ml 鲜奶）
        order_A = create_order(self.user, self.store.id, cart_1, device_sn=self.device_sn)
        order_A.status = OrderMain.STATUS_PAID
        order_A.save(update_fields=['status'])

        # 验证在途占用
        unproduced = calculate_unproduced_materials_for_device(self.device)
        assert unproduced.get("paperL") == Decimal("1.00"), f"在途纸杯计算错误: {unproduced.get('paperL')}"
        assert unproduced.get("fresh_milk") == Decimal("150.00"), f"在途鲜奶计算错误: {unproduced.get('fresh_milk')}"

        # 此时物理库存纸杯为 2，但在途占用了 1，有效可用仅剩 1！
        # 尝试新下单 2 杯（需 2 个纸杯）-> 必须被拦截！
        try:
            precheck_order(self.store.id, cart_2, device_sn=self.device_sn)
            assert False, "在途订单占用未能有效拦截超卖下单！"
        except ValueError as e:
            err_msg = str(e)
            assert "1.0个" in err_msg and "2.0个" in err_msg
            print(f"   ✓ 成功拦截超卖！有效可用仅 1.0 个，无法满足 2.0 个需求: '{err_msg}'")

        # 尝试新下单 1 杯（需 1 个纸杯）-> 应该刚好通过！
        res_pass = precheck_order(self.store.id, cart_1, device_sn=self.device_sn)
        assert res_pass["ok"] is True
        print("   ✅ [T11 通过] 在途占用动态核算精准生效，有效防止超卖！")

    def test_12_order_lifecycle_stock_reconciliation(self):
        """T12: 制作完成物理扣减与未制作退款放库生命周期闭环"""
        print("\n🧪 [T12] 测试制作完成物理扣减与未制作退款放库生命周期闭环")
        self.clean_unproduced_orders()
        self.report_hardware_status()
        self.set_mysql_consumables(paperL=10, lid=10, membrane=10)

        cart = [{"item": self.menu_item.id, "sku": [self.menu_sku_L.id], "quantity": 1}]

        # 阶段 1：订单已支付 (占用 1 纸杯，物理 10，有效 9)
        order = create_order(self.user, self.store.id, cart, device_sn=self.device_sn)
        order.status = OrderMain.STATUS_PAID
        order.save(update_fields=['status'])

        unp = calculate_unproduced_materials_for_device(self.device)
        assert unp.get("paperL") == Decimal("1.00")

        # 阶段 2：模拟出货制作完成 (STATUS_DONE)
        update_order_status(order, OrderMain.STATUS_DONE, operator='test')
        # 此时在途占用归零
        unp_done = calculate_unproduced_materials_for_device(self.device)
        assert unp_done.get("paperL", Decimal("0")) == Decimal("0")
        # 数据库物理库存减少 1 (10 -> 9)
        stock_db = DeviceConsumableStock.objects.get(device=self.device, code__code="paperL").quantity
        assert stock_db == 9, f"制作完成后物理库存未扣减！期望 9，实际 {stock_db}"
        print("   ✓ 出杯制作完成：在途占用平稳归零，MySQL 物理库存由 10 扣减至 9")

        # 阶段 3：新建订单并测试未制作退款放库
        order_refund = create_order(self.user, self.store.id, cart, device_sn=self.device_sn)
        order_refund.status = OrderMain.STATUS_PAID
        order_refund.save(update_fields=['status'])
        assert calculate_unproduced_materials_for_device(self.device).get("paperL") == Decimal("1.00")

        # 触发退款放库
        restore_res = restore_order_inventory(order_refund, operator='test', reason='未制作退款放库测试')
        assert len(restore_res.get("restored_materials", [])) > 0
        order_refund.status = OrderMain.STATUS_REFUNDED
        order_refund.save(update_fields=['status'])

        # 在途占用解除
        assert calculate_unproduced_materials_for_device(self.device).get("paperL", Decimal("0")) == Decimal("0")
        print("   ✅ [T12 通过] 制作出杯扣减与未制作退款放库全生命周期账目绝对守恒！")

    def test_13_device_offline_and_fault_interception(self):
        """T13: 设备离线与整机故障拦截测试"""
        print("\n🧪 [T13] 测试设备离线与整机故障拦截")
        self.clean_unproduced_orders()
        self.report_hardware_status()
        self.set_mysql_consumables(paperL=50, lid=50, membrane=50)

        cart = [{"item": self.menu_item.id, "sku": [self.menu_sku_L.id], "quantity": 1}]

        # 1. 设备状态置为离线
        self.device.status = Device.STATUS_OFFLINE
        self.device.save()
        try:
            precheck_order(self.store.id, cart, device_sn=self.device_sn)
            assert False, "离线设备未能拦截！"
        except ValueError as e:
            assert "离线" in str(e)
            print(f"   ✓ 成功拦截离线设备: '{e}'")

        # 恢复在线，但快照标记为整机异常
        self.device.status = Device.STATUS_ONLINE
        self.device.save()
        self.report_hardware_status(healthy=0)
        try:
            precheck_order(self.store.id, cart, device_sn=self.device_sn)
            assert False, "硬件异常快照未能拦截！"
        except ValueError as e:
            err_msg = str(e)
            assert "状态异常" in err_msg or "故障" in err_msg
            print(f"   ✓ 成功拦截硬件健康异常: '{err_msg}'")

        # 恢复健康快照
        self.report_hardware_status(healthy=1)
        print("   ✅ [T13 通过] 设备离线与整机故障异常均被有效阻断")

    def test_14_abnormal_input_and_cache_miss_robustness(self):
        """T14: 异常边界输入容错测试（负数上报、Redis 缓存丢失）"""
        print("\n🧪 [T14] 测试异常边界输入容错（负数上报、Redis 缓存丢失）")
        self.clean_unproduced_orders()
        self.set_mysql_consumables(paperL=50, lid=50, membrane=50)

        cart = [{"item": self.menu_item.id, "sku": [self.menu_sku_L.id], "quantity": 1}]

        # 1. 上位机故障上报负数体积 (v: -100) 与非法字符串
        self.report_hardware_status(thinP_data={
            "b01": {"v": -100, "a1": 0},
            "b02": {"v": "invalid_num", "a1": 0}
        })
        stock_milk = float(self.redis.get(get_redis_stock_key(self.device_sn, "fresh_milk")))
        assert stock_milk == 0.0, f"负数与非法值未被归零，实际为 {stock_milk}"
        try:
            precheck_order(self.store.id, cart, device_sn=self.device_sn)
            assert False, "归零后未能拦截缺料！"
        except ValueError as e:
            assert "0.0ml" in str(e)
            print(f"   ✓ 负数/非法值上报安全容错归零并拦截: '{e}'")

        # 2. Redis 缓存 key 意外丢失 (Cache Miss = None)
        self.redis.delete(get_redis_stock_key(self.device_sn, "fresh_milk"))
        try:
            precheck_order(self.store.id, cart, device_sn=self.device_sn)
            assert False, "Redis Key 丢失未被拦截！"
        except ValueError as e:
            assert "0.0ml" in str(e)
            print(f"   ✓ Redis 缓存穿透丢失安全容错拦截（未抛500）: '{e}'")

        print("   ✅ [T14 通过] 异常输入与缓存穿透丢失测试全部安全通过")

    def run_all(self):
        print("\n" + "=" * 75)
        print("🚀 开始执行物料检测有效性与多料桶聚合 14 项全场景深度测试")
        print("=" * 75)

        test_methods = [
            self.test_01_multi_barrel_normal_aggregation,
            self.test_02_cross_barrel_supply,
            self.test_03_multi_barrel_shortage_interception,
            self.test_04_multi_barrel_one_empty_barrel,
            self.test_05_damaged_barrel_exclusion,
            self.test_06_mysql_consumables_sufficient,
            self.test_07_mysql_consumables_boundary_zero,
            self.test_08_mysql_consumables_missing_lid,
            self.test_09_mysql_consumables_missing_membrane,
            self.test_10_hot_cold_cup_correction_linkage,
            self.test_11_in_flight_committed_order_anti_overselling,
            self.test_12_order_lifecycle_stock_reconciliation,
            self.test_13_device_offline_and_fault_interception,
            self.test_14_abnormal_input_and_cache_miss_robustness,
        ]

        passed = 0
        failed = 0
        for idx, m in enumerate(test_methods, 1):
            try:
                m()
                passed += 1
            except Exception as e:
                failed += 1
                print(f"\n❌ [测试 {idx} 失败]: {e}")
                import traceback
                traceback.print_exc()

        print("\n" + "=" * 75)
        print(f"📊 [测试汇总结果] 共运行 {len(test_methods)} 项测试: 全部通过 {passed} 项, 失败 {failed} 项")
        print("=" * 75)
        return failed == 0


if __name__ == '__main__':
    tester = ComprehensiveMaterialTester()
    success = tester.run_all()
    sys.exit(0 if success else 1)
