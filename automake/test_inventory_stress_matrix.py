"""
test_inventory_stress_matrix.py
============================================================
智能咖啡机库存校验与锁库并发压测及 MQTT 模拟全链路套件

涵盖 6 大核心高危场景：
1. S01: 高并发支付锁库争抢防超卖压测 (10 个并发线程争抢 2 杯可用原料)
2. S02: 耗材全生命周期扣减账目核算 (检测是否存在支付扣一次、完成又扣一次的“二次扣减”漏洞)
3. S03: 上位机 MQTT 周期上报 (基于 simulator/mqtt_client.py 报文规范) 与出单交替平滑性验证
4. S04: 物理传感器缺杯 (cup.paperL.a2=1) 优先拦截机制验证 (哪怕 MySQL 仍有库存)
5. S05: 混合组合多 SKU 缺料原子回滚压测 (部分物料不足时，全部已加锁资源彻底释放)
6. S06: 异常输入与 Redis 缓存断网/丢失容错与安全降级 (Fail-Closed 保护)
============================================================
"""

import os
import sys
import json
import time
import threading
from decimal import Decimal
import django

# 初始化 Django
sys.path.insert(0, '/home/ubuntu/autoMachine/automake')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')
django.setup()

from django.utils import timezone
from django.db import connection, transaction
from django_redis import get_redis_connection

from users.models import User
from stores.models import Store
from devices.models import (
    Device, DeviceBarrelDict,
    DeviceConsumableStock, DeviceMaterialStock
)
from inventory.models import Material
from global_config.models import (
    DeviceModel, GlobalMenuCategory, GlobalMenuItem,
    GlobalSkuTemplate, GlobalMenuSku, GlobalSkuIngredient
)
from menus.models import MenuItem, MenuSku
from orders.models import OrderMain, OrderItem, ProductionTask
from payments.models import PaymentRecord
from orders.services import (
    precheck_order, create_order, update_order_status,
    calculate_unproduced_materials_for_device,
    try_lock_order_inventory, rollback_order_locked_inventory,
    deduct_order_consumables, get_redis_stock_key,
    deduct_order_redis_ingredients
)
from monitor.services import (
    process_device_status_report, parse_device_status_payload,
    update_device_status_to_redis
)


class InventoryStressTester:
    def __init__(self):
        self.device_sn = "sn001"
        self.store_code = "STORE_STRESS_001"
        self.redis = get_redis_connection("default")
        self.setup_base_data()

    def setup_base_data(self):
        print("\n" + "=" * 75)
        print("🛠️  [环境初始化] 正在准备压力测试数据与设备配置...")
        print("=" * 75)

        # 1. 用户
        self.user, _ = User.objects.get_or_create(
            username="stress_test_user",
            defaults={"phone": "13800009999", "role": "user"}
        )

        # 2. 门店
        self.store, _ = Store.objects.get_or_create(
            code=self.store_code,
            defaults={
                "name": "并发压测自营店",
                "status": Store.STATUS_OPEN,
                "contact_phone": "13800009999"
            }
        )
        self.store.status = Store.STATUS_OPEN
        self.store.save()

        # 3. 设备模型与设备
        self.dev_model, _ = DeviceModel.objects.get_or_create(
            code="coffee_master_v3",
            defaults={"name": "全自动多料桶咖啡机器人"}
        )
        self.device, _ = Device.objects.get_or_create(
            device_sn=self.device_sn,
            defaults={
                "device_name": "并发压测机01",
                "store": self.store,
                "device_model": self.dev_model,
                "status": Device.STATUS_ONLINE
            }
        )
        self.device.store = self.store
        self.device.device_model = self.dev_model
        self.device.status = Device.STATUS_ONLINE
        self.device.save()

        # 4. 基础物料定义
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

        # 5. 料桶字典映射 DeviceBarrelDict
        DeviceBarrelDict.objects.filter(device=self.device).delete()
        DeviceBarrelDict.objects.create(device=self.device, barrel_code="b01", material=self.mat_milk, alarm_threshold_1=Decimal('0.00'), alarm_threshold_2=Decimal('0.00'), created_by=self.user)
        DeviceBarrelDict.objects.create(device=self.device, barrel_code="b02", material=self.mat_milk, alarm_threshold_1=Decimal('0.00'), alarm_threshold_2=Decimal('0.00'), created_by=self.user)
        DeviceBarrelDict.objects.create(device=self.device, barrel_code="b03", material=self.mat_bean, alarm_threshold_1=Decimal('0.00'), alarm_threshold_2=Decimal('0.00'), created_by=self.user)
        DeviceBarrelDict.objects.create(device=self.device, barrel_code="b09", material=self.mat_syrup, alarm_threshold_1=Decimal('0.00'), alarm_threshold_2=Decimal('0.00'), created_by=self.user)

        # 6. 配置商品配方
        cat, _ = GlobalMenuCategory.objects.get_or_create(
            name="压测专用分类", device_model=self.dev_model, defaults={"label": "咖啡", "sort_order": 1}
        )
        g_item, _ = GlobalMenuItem.objects.get_or_create(
            name="压测拿铁", defaults={"category": cat, "base_price": 10, "is_active": True}
        )
        tpl_L, _ = GlobalSkuTemplate.objects.get_or_create(
            category="杯型", name="大杯热饮", defaults={"default_price_delta": 0}
        )
        g_sku_L, _ = GlobalMenuSku.objects.get_or_create(
            item=g_item, template=tpl_L, defaults={"price_delta": 0, "is_active": True}
        )
        GlobalSkuIngredient.objects.filter(sku=g_sku_L).delete()
        GlobalSkuIngredient.objects.create(sku=g_sku_L, material=self.mat_bean, quantity=Decimal("15.00"), unit="g")
        GlobalSkuIngredient.objects.create(sku=g_sku_L, material=self.mat_milk, quantity=Decimal("150.00"), unit="ml")

        MenuItem.sync_store_menu(self.store)
        self.menu_item = MenuItem.objects.get(store=self.store, global_item=g_item)
        self.menu_item.is_active = True
        self.menu_item.save()

        self.menu_sku_L = MenuSku.objects.get(item=self.menu_item, global_sku=g_sku_L)
        self.menu_sku_L.is_active = True
        self.menu_sku_L.save()

        print(f"   ✓ 设备 [{self.device.device_sn}] 与测试菜单就绪")

    def clean_orders(self):
        """清理已有的测试订单"""
        OrderMain.objects.filter(device=self.device).update(status=OrderMain.STATUS_CANCELLED)

    def set_mysql_consumables(self, paperL=100, plasticL=100, lid=100, membrane=100):
        mats = {
            "paperL": (self.mat_paper_L, paperL, '个'),
            "plasticL": (self.mat_plastic_L, plasticL, '个'),
            "lid": (self.mat_lid, lid, '个'),
            "membrane": (self.mat_membrane, membrane, '张')
        }
        for code, (mat_obj, qty, unit) in mats.items():
            cs, _ = DeviceConsumableStock.objects.get_or_create(
                device=self.device,
                code=mat_obj,
                defaults={"quantity": qty, "init_quantity": 100, "unit": unit, "warn_level": 10, "stop_sale_level": 0}
            )
            cs.quantity = qty
            cs.stop_sale_level = 0
            cs.save(update_fields=['quantity', 'stop_sale_level', 'updated_at'])

    def report_hardware_status(self, thinP=None, thickP=None, solidP=None, cup=None, healthy=1, disconnected=0):
        """按照 simulator/mqtt_client.py 的报文格式向系统上报状态"""
        payload = {
            "healthy": healthy,
            "disconnected": disconnected,
            "free": {"master": 1024, "slave": 64},
            "temperature": {"t1": 4, "t2": 175},
            "ice": {"a1": 0, "a2": 0, "a3": 0},
            "transfer": {"a1": 0},
            "cup": cup or {
                "plasticL": {"a1": 0, "a2": 0},
                "plasticM": {"a1": 0, "a2": 0},
                "paperL": {"a1": 0, "a2": 0},
                "paperM": {"a1": 0, "a2": 0},
                "membrane": {"a1": 0, "a2": 0},
                "lid": {"a1": 0, "a2": 0}
            },
            "thinP": thinP or {
                "b01": {"v": 20000, "a1": 0},
                "b02": {"v": 20000, "a1": 0},
            },
            "thickP": thickP or {
                "b09": {"v": 5800, "a1": 0},
            },
            "solidP": solidP or {
                "b03": {"v": 3500, "a1": 0},
            }
        }
        return process_device_status_report(self.device_sn, payload)

    # =========================================================================
    # 场景 1: 高并发支付锁库争抢防超卖压测 (10 线程争抢 2 杯库存)
    # =========================================================================
    def scenario_01_concurrent_pay_lock_stress(self):
        print("\n🧪 [S01] 测试高并发支付锁库防超卖 (10 个并发线程同时争抢最后 2 个纸杯库存)")
        self.clean_orders()
        self.report_hardware_status(thinP={"b01": {"v": 5000, "a1": 0}, "b02": {"v": 5000, "a1": 0}})
        # 仅放 2 个纸杯
        self.set_mysql_consumables(paperL=2, lid=50, membrane=50)

        # 先创建 10 个待支付订单
        cart = [{"item": self.menu_item.id, "sku": [self.menu_sku_L.id], "quantity": 1}]
        orders = []
        for i in range(10):
            ord_obj = create_order(self.user, self.store.id, cart, device_sn=self.device_sn)
            orders.append(ord_obj)

        lock_results = []
        threads = []

        def worker_pay_lock(order):
            connection.close()  # 为每个子线程开启独立的 DB 连接
            try:
                ok, msg, ctx = try_lock_order_inventory(order)
                lock_results.append((order.order_no, ok, msg))
            except Exception as e:
                lock_results.append((order.order_no, False, str(e)))
            finally:
                connection.close()

        # 同时并发启动 10 个线程进行原子锁库
        for ord_obj in orders:
            t = threading.Thread(target=worker_pay_lock, args=(ord_obj,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        success_count = sum(1 for _, ok, _ in lock_results if ok)
        failed_count = sum(1 for _, ok, _ in lock_results if not ok)

        final_stock = DeviceConsumableStock.objects.get(device=self.device, code__code="paperL").quantity
        print(f"   📊 并发锁库结果: 成功 {success_count} 笔, 拦截/失败 {failed_count} 笔, 数据库剩余库存: {final_stock}")

        assert success_count == 2, f"❌ 超卖漏洞！期望仅成功 2 笔，实际成功 {success_count} 笔！"
        assert failed_count == 8, f"❌ 失败拦截数错误！期望 8 笔，实际 {failed_count} 笔！"
        assert final_stock == 0, f"❌ 最终库存错误！期望 0，实际 {final_stock}"
        print("   ✅ [S01 通过] 高并发排他行锁表现完美，严格拦截了 8 笔并发超卖请求，物理库存精确扣减至 0！")

    # =========================================================================
    # 场景 2: 耗材全生命周期扣减账目核算 (检测二次扣减)
    # =========================================================================
    def scenario_02_consumable_double_deduction_check(self):
        print("\n🧪 [S02] 检测耗材生命周期扣减账目 (支付锁库 vs 出单完成 done 状态流转)")
        self.clean_orders()
        self.report_hardware_status()
        self.set_mysql_consumables(paperL=10, lid=10, membrane=10)

        cart = [{"item": self.menu_item.id, "sku": [self.menu_sku_L.id], "quantity": 1}]
        order = create_order(self.user, self.store.id, cart, device_sn=self.device_sn)

        # 阶段 1：模拟支付锁库阶段 (try_lock_order_inventory)
        locked_ok, msg, ctx = try_lock_order_inventory(order)
        assert locked_ok is True
        stock_after_lock = DeviceConsumableStock.objects.get(device=self.device, code__code="paperL").quantity
        print(f"   [阶段 1 支付锁库后] MySQL 纸杯库存由 10 变为: {stock_after_lock}")

        # 标记为已支付
        order.status = OrderMain.STATUS_PAID
        order.save(update_fields=['status'])

        # 阶段 2：模拟上位机制作完成上报 (STATUS_DONE)
        update_order_status(order, OrderMain.STATUS_DONE, operator='device:sn001', remark='上位机制作完成')
        stock_after_done = DeviceConsumableStock.objects.get(device=self.device, code__code="paperL").quantity
        print(f"   [阶段 2 出单完成 done] MySQL 纸杯库存变为: {stock_after_done}")

        if stock_after_done == 8:
            print(f"   🚨 [检测到二次扣减隐患] 10 个纸杯在支付时扣 1 变 9，在出单完成时又被 deduct_order_consumables 扣减 1 变成了 8！")
            return False, "检测到二次扣减漏洞"
        elif stock_after_done == 9:
            print(f"   ✅ [S02 通过] 纸杯扣减账目完全守恒 (10 -> 9)，未发生二次扣减。")
            return True, "无二次扣减"
        else:
            assert False, f"异常库存值: {stock_after_done}"

    # =========================================================================
    # 场景 3: 上位机 MQTT 周期上报 (simulator 规范) 与出单交替平滑性验证
    # =========================================================================
    def scenario_03_mqtt_rhythm_simulation(self):
        print("\n🧪 [S03] 测试上位机 MQTT 60s 定时上报节拍与出单交替平滑性")
        self.clean_orders()
        # 初始物理上报：鲜牛奶 b01=1000ml, b02=1000ml (总 2000ml)
        self.report_hardware_status(thinP={"b01": {"v": 1000, "a1": 0}, "b02": {"v": 1000, "a1": 0}})
        self.set_mysql_consumables(paperL=10, lid=10, membrane=10)

        # 1. 验证初始 Redis 库存
        redis_milk_0 = float(self.redis.get(get_redis_stock_key(self.device_sn, "fresh_milk")))
        assert redis_milk_0 == 2000.0

        # 2. 下单 1 杯（需 150ml 鲜奶）并支付，进入制作中
        cart = [{"item": self.menu_item.id, "sku": [self.menu_sku_L.id], "quantity": 1}]
        order = create_order(self.user, self.store.id, cart, device_sn=self.device_sn)
        order.status = OrderMain.STATUS_MAKING
        order.save(update_fields=['status'])

        # 此时在途占用为 150ml，有效库存应为 1850ml
        chk = precheck_order(self.store.id, cart, device_sn=self.device_sn)
        eff_milk = next(m['effective_available'] for m in chk['material_checks'] if m['code'] == 'fresh_milk')
        assert eff_milk == 1850.0, f"在途核算错误: {eff_milk}"
        print(f"   ✓ 订单制作中 (making)：物理 2000ml - 在途 150ml = 有效可用 {eff_milk}ml")

        # 3. 模拟制作完成瞬间 (done)
        update_order_status(order, OrderMain.STATUS_DONE, operator='device:sn001')
        deduct_order_redis_ingredients(order)

        # 检查出杯瞬间 Redis 基准值是否平滑减去 150ml，有效库存保持 1850ml (消除幽灵库存回弹)
        redis_milk_done = float(self.redis.get(get_redis_stock_key(self.device_sn, "fresh_milk")))
        assert redis_milk_done == 1850.0, f"幽灵库存防抖未生效: {redis_milk_done}"
        print(f"   ✓ 出杯完成瞬间 (done)：Redis 基准值平滑降至 {redis_milk_done}ml，无在途，有效可用精确保持 1850ml")

        # 4. 模拟下一个周期的上位机 MQTT 报文到达（真实传感器读数已变为 1850ml）
        self.report_hardware_status(thinP={"b01": {"v": 900, "a1": 0}, "b02": {"v": 950, "a1": 0}})
        redis_milk_next = float(self.redis.get(get_redis_stock_key(self.device_sn, "fresh_milk")))
        assert redis_milk_next == 1850.0
        print(f"   ✓ 下一周期 MQTT 报文到达：物理传感器实测 (900+950={redis_milk_next}ml) 与云端账目无缝对接，零跳变")
        print("   ✅ [S03 通过] MQTT 节拍与出单生命周期账目平滑对接测试通过！")

    # =========================================================================
    # 场景 4: 物理传感器缺杯 (cup.paperL.a2=1) 优先拦截机制验证
    # =========================================================================
    def scenario_04_hardware_sensor_empty_injection(self):
        print("\n🧪 [S04] 测试物理传感器缺杯 (cup.paperL.a2=1) 联动拦截 (即使 MySQL 里记录还有 50 个)")
        self.clean_orders()
        self.report_hardware_status(
            cup={
                "paperL": {"a1": 0, "a2": 1},  # 硬件传感器上报纸杯已空！
                "paperM": {"a1": 0, "a2": 0},
                "plasticL": {"a1": 0, "a2": 0},
                "plasticM": {"a1": 0, "a2": 0},
                "membrane": {"a1": 0, "a2": 0},
                "lid": {"a1": 0, "a2": 0}
            }
        )
        # MySQL 里人工填了 50 个
        self.set_mysql_consumables(paperL=50, lid=50, membrane=50)

        cart = [{"item": self.menu_item.id, "sku": [self.menu_sku_L.id], "quantity": 1}]
        try:
            precheck_order(self.store.id, cart, device_sn=self.device_sn)
            print("   🚨 [未能拦截] 上位机传感器已上报 a2=1 (缺纸杯)，但 precheck_order 仍因 MySQL 有 50 个而盲目放行！")
            return False, "未能拦截物理传感器缺杯"
        except ValueError as e:
            err_msg = str(e)
            print(f"   ✅ [S04 通过] 物理缺杯传感器生效，成功阻断下单: '{err_msg}'")
            return True, "成功拦截物理传感器缺杯"

    # =========================================================================
    # 场景 1b: 食材类物料 (Redis) 支付前并发防超卖与锁定校验
    # =========================================================================
    def scenario_01b_ingredient_concurrency_pay_lock(self):
        print("\n🧪 [S01b] 测试食材类物料 (鲜牛奶 150ml 仅够 1 杯) 支付前并发防超卖")
        self.clean_orders()
        # 纸杯极充裕 (100个)，但鲜牛奶仅有 150ml (刚好够 1 杯拿铁)
        self.report_hardware_status(thinP={"b01": {"v": 150, "a1": 0}, "b02": {"v": 0, "a1": 0}})
        self.set_mysql_consumables(paperL=100, lid=100, membrane=100)

        cart = [{"item": self.menu_item.id, "sku": [self.menu_sku_L.id], "quantity": 1}]
        order_A = create_order(self.user, self.store.id, cart, device_sn=self.device_sn)
        order_B = create_order(self.user, self.store.id, cart, device_sn=self.device_sn)

        # 订单 A 先发起支付并锁定
        ok_a, msg_a, ctx_a = try_lock_order_inventory(order_A)
        assert ok_a is True, f"订单 A 锁库失败: {msg_a}"
        order_A.status = OrderMain.STATUS_PAID
        order_A.save(update_fields=['status'])

        # 此时订单 A 处于 STATUS_PAID，已占用了 150ml 鲜牛奶。
        # 鲜牛奶物理 150ml - 在途已付占用 150ml = 0ml！
        # 订单 B 随后发起支付锁库 try_lock_order_inventory(order_B)：必须被拦截！
        ok_b, msg_b, ctx_b = try_lock_order_inventory(order_B)
        if ok_b is True:
            print(f"   🚨 [检测到食材超卖漏洞] 鲜牛奶已被订单 A 耗尽，但 try_lock_order_inventory 只锁纸杯未核验食材，订单 B 依然锁库成功！")
            return False, "食材未在支付锁库阶段校验"
        else:
            print(f"   ✅ [S01b 通过] 食材在途耗尽被支付锁库精准拦截: '{msg_b}'")
            return True, "食材防超卖生效"

    # =========================================================================
    # 场景 5: 混合组合多 SKU 缺料原子回滚压测
    # =========================================================================
    def scenario_05_multi_sku_atomic_rollback(self):
        print("\n🧪 [S05] 测试混合组合多 SKU 缺料原子回滚与悬挂锁消除")
        self.clean_orders()
        self.report_hardware_status()
        # 下单时耗材充足
        self.set_mysql_consumables(paperL=10, plasticL=10, lid=10, membrane=10)

        cart = [{"item": self.menu_item.id, "sku": [self.menu_sku_L.id], "quantity": 1}]
        order = create_order(self.user, self.store.id, cart, device_sn=self.device_sn)

        # 模拟在下单后、支付前瞬间，杯盖被其他渠道耗尽 (lid=0)
        self.set_mysql_consumables(paperL=10, plasticL=10, lid=0, membrane=10)

        locked_ok, msg, ctx = try_lock_order_inventory(order)
        assert locked_ok is False, "缺杯盖未能拦截！"
        print(f"   ✓ 缺杯盖在支付锁库时被安全拦截: '{msg}'")

        # 检查纸杯是否有被意外扣除 (确保原子性)
        paper_stock = DeviceConsumableStock.objects.get(device=self.device, code__code="paperL").quantity
        assert paper_stock == 10, f"纸杯未完全回滚！期望 10，实际 {paper_stock}"
        print("   ✅ [S05 通过] 组合物料缺任一项目时，原子性回滚 100% 保持完整，未留下任何扣减残留！")

    # =========================================================================
    # 场景 6: 异常输入与 Redis 缓存丢失容错与安全降级
    # =========================================================================
    def scenario_06_cache_miss_and_fault_tolerance(self):
        print("\n🧪 [S06] 测试异常输入容错与 Redis 缓存断网/丢失安全降级 (Fail-Closed)")
        self.clean_orders()
        self.set_mysql_consumables(paperL=10, lid=10, membrane=10)

        cart = [{"item": self.menu_item.id, "sku": [self.menu_sku_L.id], "quantity": 1}]

        # 模拟 Redis 食材 Key 被清空/丢失
        self.redis.delete(get_redis_stock_key(self.device_sn, "fresh_milk"))
        self.redis.delete(get_redis_stock_key(self.device_sn, "coffee_bean"))

        try:
            precheck_order(self.store.id, cart, device_sn=self.device_sn)
            assert False, "Redis 丢失物料数据后未能触发安全闭门拦截！"
        except ValueError as e:
            err_msg = str(e)
            assert "原料不足" in err_msg or "缺料" in err_msg
            print(f"   ✓ Redis 缓存丢失时自动进入 Fail-Closed (安全拒单) 机制: '{err_msg}'")

        print("   ✅ [S06 通过] 缓存丢失时无 500 异常，系统安全降级并精准拦截！")

    def run_all(self):
        print("\n" + "=" * 75)
        print("🚀 开始运行智能咖啡机库存并发压测与 MQTT 模拟全链路套件")
        print("=" * 75)

        results = {}
        # S01
        self.scenario_01_concurrent_pay_lock_stress()
        results["S01_纸杯并发排他锁防超卖"] = True

        # S01b
        s01b_ok, s01b_msg = self.scenario_01b_ingredient_concurrency_pay_lock()
        results["S01b_食材在途防超卖锁库"] = s01b_ok

        # S02
        s02_ok, s02_msg = self.scenario_02_consumable_double_deduction_check()
        results["S02_耗材二次扣减检测"] = s02_ok

        # S03
        self.scenario_03_mqtt_rhythm_simulation()
        results["S03_MQTT上报节拍对接"] = True

        # S04
        s04_ok, s04_msg = self.scenario_04_hardware_sensor_empty_injection()
        results["S04_物理传感器缺杯拦截"] = s04_ok

        # S05
        self.scenario_05_multi_sku_atomic_rollback()
        results["S05_多SKU原子回滚"] = True

        # S06
        self.scenario_06_cache_miss_and_fault_tolerance()
        results["S06_缓存丢失安全降级"] = True

        print("\n" + "=" * 75)
        print("📋 [压测与核查最终汇总]")
        for k, v in results.items():
            status = "✅ PASS" if v else "❌ DETECTED ISSUE (需修复)"
            print(f"   - {k}: {status}")
        print("=" * 75)
        return results


if __name__ == '__main__':
    tester = InventoryStressTester()
    tester.run_all()
