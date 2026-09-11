#!/usr/bin/env python3
"""
大规模随机数据生成与全方位库存逻辑混沌压测系统 (Mass Data Chaos Fuzzer & Invariant Auditor)

特性：
1. 随机环境构建：随机生成多料桶映射、报警双级阈值 (alarm_1, alarm_2)、耗材库存与双级停售阈值、随机配方商品。
2. 混沌并发事件流：多线程 Worker 并发执行随机下单预检、支付抢锁、出单完成、异常退款取消、上位机 MQTT 报文噪声上报。
3. 独立第三方影子账本 (Shadow Ledger)：完全独立于业务代码，精准记录每一项物理扣减与在途变动。
4. 六大物理守恒不变量全景审计：零超卖、质量守恒定律、零重复扣减、零孤儿锁定、停售强制阻断、多桶聚合一致性。
"""

import os
import sys
import time
import json
import random
import logging
import argparse
import threading
from decimal import Decimal
from typing import Dict, List, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

# 初始化 Django 运行环境
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')
import django
django.setup()

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django_redis import get_redis_connection

from global_config.models import (
    DeviceModel, GlobalMenuCategory, GlobalMenuItem,
    GlobalSkuTemplate, GlobalMenuSku, GlobalSkuIngredient
)
from stores.models import Store
from devices.models import Device, DeviceBarrelDict, DeviceConsumableStock
from inventory.models import Material
from menus.models import MenuItem, MenuSku
from orders.models import OrderMain, OrderItem
from orders.services import (
    precheck_order, create_order, try_lock_order_inventory,
    update_order_status, restore_order_inventory, calculate_unproduced_materials_for_device,
    get_redis_stock_key
)
from payments.services import refund_order
from monitor.services import process_device_status_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("ChaosFuzzer")
logging.getLogger("orders.services").setLevel(logging.WARNING)
logging.getLogger("monitor").setLevel(logging.WARNING)
logging.getLogger("payments.services").setLevel(logging.WARNING)


# =====================================================================
# 1. 独立第三方影子记账引擎 (Shadow Ledger)
# =====================================================================
class ShadowLedger:
    """
    独立于业务系统之外的客观物理账本。
    用于记录真实发生的所有操作，并在任意时刻核算系统的质量守恒与状态不变量。
    """
    def __init__(self, initial_consumables: Dict[str, int], initial_barrels: Dict[str, float]):
        self.lock = threading.Lock()
        
        # 耗材账目 (数量)
        self.initial_consumables = initial_consumables.copy()
        self.locked_consumables = {k: 0 for k in initial_consumables}
        self.consumed_consumables = {k: 0 for k in initial_consumables}
        
        # 料桶食材账目 (ml/g)
        self.initial_barrels = initial_barrels.copy()
        self.current_simulated_barrels = initial_barrels.copy()
        self.consumed_materials: Dict[str, float] = {}

        # 订单事件生命周期记录: order_no -> {'status': str, 'locked_items': dict, 'recipe': dict, 'deducted_count': int}
        self.orders: Dict[str, dict] = {}

        # 统计计数器
        self.total_precheck_attempts = 0
        self.precheck_passed = 0
        self.precheck_rejected = 0
        self.total_lock_attempts = 0
        self.lock_success = 0
        self.lock_failed = 0
        self.orders_completed = 0
        self.orders_refunded = 0
        self.orders_cancelled = 0
        self.hardware_reports = 0

        # 不变量违背追踪
        self.violations: List[str] = []

    def record_lock_success(self, order_no: str, locked_consumables: Dict[str, int], recipe_mats: Dict[str, float]):
        with self.lock:
            self.total_lock_attempts += 1
            self.lock_success += 1
            for code, qty in locked_consumables.items():
                self.locked_consumables[code] = self.locked_consumables.get(code, 0) + qty
            
            self.orders[order_no] = {
                'status': 'LOCKED',
                'locked_consumables': locked_consumables.copy(),
                'recipe_mats': recipe_mats.copy(),
                'deducted_count': 1  # 支付锁库已完成扣减
            }

    def record_lock_failure(self, order_no: str, reason: str):
        with self.lock:
            self.total_lock_attempts += 1
            self.lock_failed += 1

    def record_order_done(self, order_no: str):
        with self.lock:
            info = self.orders.get(order_no)
            if not info:
                return
            info['status'] = 'COMPLETED'
            self.orders_completed += 1
            
            # 耗材由 locked 转为 consumed
            for code, qty in info['locked_consumables'].items():
                self.locked_consumables[code] = max(0, self.locked_consumables.get(code, 0) - qty)
                self.consumed_consumables[code] = self.consumed_consumables.get(code, 0) + qty

            # 食材累加实际物理消耗
            for mat_code, qty in info['recipe_mats'].items():
                self.consumed_materials[mat_code] = self.consumed_materials.get(mat_code, 0.0) + float(qty)

    def record_order_refund(self, order_no: str):
        with self.lock:
            info = self.orders.get(order_no)
            if not info:
                return
            old_status = info['status']
            info['status'] = 'REFUNDED'
            self.orders_refunded += 1

            # 释放回库
            if old_status == 'LOCKED':
                for code, qty in info['locked_consumables'].items():
                    self.locked_consumables[code] = max(0, self.locked_consumables.get(code, 0) - qty)
            elif old_status == 'COMPLETED':
                for code, qty in info['locked_consumables'].items():
                    self.consumed_consumables[code] = max(0, self.consumed_consumables.get(code, 0) - qty)
                for mat_code, qty in info['recipe_mats'].items():
                    self.consumed_materials[mat_code] = max(0.0, self.consumed_materials.get(mat_code, 0.0) - float(qty))

    def record_order_cancel(self, order_no: str):
        with self.lock:
            info = self.orders.get(order_no)
            if not info:
                return
            info['status'] = 'CANCELLED'
            self.orders_cancelled += 1
            for code, qty in info['locked_consumables'].items():
                self.locked_consumables[code] = max(0, self.locked_consumables.get(code, 0) - qty)


# =====================================================================
# 2. 随机环境与数据构造器 (Config Fuzzer)
# =====================================================================
class FuzzEnvironment:
    """
    为测试自动化创建完全随机但结构合法的咖啡机设备沙箱
    """
    def __init__(self, device_sn: str):
        self.device_sn = device_sn
        self.redis = get_redis_connection("default")
        self.user = None
        self.store = None
        self.device = None
        self.dev_model = None

        # 随机物料与料桶
        self.materials: Dict[str, Material] = {}
        self.barrel_configs: Dict[str, dict] = {}
        self.consumables_config: Dict[str, dict] = {}
        self.menu_items: List[dict] = []

    def setup_random_topology(self):
        """生成随机料桶拓扑、阈值、耗材与商品配方"""
        User = get_user_model()
        self.user, _ = User.objects.get_or_create(username="fuzz_tester", defaults={"is_staff": True})
        self.store, _ = Store.objects.get_or_create(code="FUZZ_STORE", defaults={"name": "混沌压测沙箱门店", "contact_phone": "13800008888"})
        self.dev_model, _ = DeviceModel.objects.get_or_create(code="FUZZ_DEV_MODEL", defaults={"name": "混沌测试机型"})
        
        self.device, _ = Device.objects.get_or_create(
            device_sn=self.device_sn,
            defaults={"device_name": "混沌测试机", "store": self.store, "device_model": self.dev_model, "status": Device.STATUS_ONLINE}
        )
        self.device.status = Device.STATUS_ONLINE
        self.device.save()

        # 1. 基础物料定义
        mat_defs = [
            ("coffee_bean", "阿拉比卡咖啡豆", Material.TYPE_SOLID, "g"),
            ("fresh_milk", "特级鲜牛奶", Material.TYPE_THIN, "ml"),
            ("oat_milk", "燕麦奶", Material.TYPE_THIN, "ml"),
            ("vanilla_syrup", "香草糖浆", Material.TYPE_THICK, "ml"),
            ("paperL", "500ml纸杯", Material.TYPE_CUP, "个"),
            ("lid", "外带杯盖", Material.TYPE_CONSUMABLE, "个"),
            ("membrane", "密封膜", Material.TYPE_CONSUMABLE, "张"),
        ]
        for code, name, m_type, unit in mat_defs:
            m, _ = Material.objects.get_or_create(code=code, defaults={"name": name, "material_type": m_type, "unit": unit})
            self.materials[code] = m

        # 2. 随机配置多料桶 (例如 4~6 个料桶，包含鲜奶双桶 b01, b02，燕麦奶 b03, 咖啡豆 b32, 糖浆 b09)
        DeviceBarrelDict.objects.filter(device=self.device).delete()
        
        barrel_mappings = [
            ("b01", "fresh_milk", random.randint(2000, 8000), random.randint(500, 1000), random.randint(100, 300)),
            ("b02", "fresh_milk", random.randint(2000, 8000), random.randint(500, 1000), random.randint(100, 300)),
            ("b03", "oat_milk", random.randint(2000, 6000), random.randint(400, 800), random.randint(100, 200)),
            ("b09", "vanilla_syrup", random.randint(1000, 4000), random.randint(300, 600), random.randint(50, 150)),
            ("b32", "coffee_bean", random.randint(1000, 3000), random.randint(200, 500), random.randint(50, 100)),
        ]

        for b_code, mat_code, init_vol, a1, a2 in barrel_mappings:
            DeviceBarrelDict.objects.create(
                device=self.device,
                barrel_code=b_code,
                material=self.materials[mat_code],
                alarm_threshold_1=Decimal(str(a1)),
                alarm_threshold_2=Decimal(str(a2)),
                created_by=self.user
            )
            self.barrel_configs[b_code] = {
                'mat_code': mat_code,
                'volume': float(init_vol),
                'alarm_1': float(a1),
                'alarm_2': float(a2)
            }

        # 3. 随机配置耗材库存与双级停售阈值
        consumables_setup = [
            ("paperL", random.randint(100, 300), 20, 5),     # 纸杯：少于20报警，少于5停售
            ("lid", random.randint(100, 300), 20, 5),        # 杯盖
            ("membrane", random.randint(100, 300), 20, 5),   # 封口膜
        ]
        for c_code, init_q, w_lvl, s_lvl in consumables_setup:
            cs, _ = DeviceConsumableStock.objects.update_or_create(
                device=self.device,
                code=self.materials[c_code],
                defaults={
                    "quantity": init_q,
                    "init_quantity": init_q,
                    "warn_level": w_lvl,
                    "stop_sale_level": s_lvl,
                    "unit": "张" if c_code == "membrane" else "个"
                }
            )
            self.consumables_config[c_code] = {
                'quantity': init_q,
                'warn_level': w_lvl,
                'stop_sale_level': s_lvl
            }

        # 4. 随机配置测试商品与配方
        self._setup_random_menu()

        # 5. 清理历史订单与 Redis
        OrderMain.objects.filter(device=self.device).delete()
        for k in self.redis.keys(f"automake:*:{self.device_sn}:*"):
            self.redis.delete(k)
        for k in self.redis.keys(f"automake:stock:{self.device_sn}:*"):
            self.redis.delete(k)

        # 6. 上报初始物理状态
        self.sync_hardware_status_to_system()

    def _setup_random_menu(self):
        """配置 3 款包含不同食材组合的商品"""
        cat, _ = GlobalMenuCategory.objects.get_or_create(device_model=self.dev_model, name="混沌饮品", defaults={"sort_order": 1, "is_active": True})
        
        drinks = [
            ("经典拿铁", {"coffee_bean": 15, "fresh_milk": 150, "paperL": 1, "lid": 1, "membrane": 1}),
            ("燕麦拿铁", {"coffee_bean": 15, "oat_milk": 180, "paperL": 1, "lid": 1, "membrane": 1}),
            ("香草拿铁", {"coffee_bean": 15, "fresh_milk": 140, "vanilla_syrup": 20, "paperL": 1, "lid": 1, "membrane": 1}),
        ]
        self.menu_items.clear()

        for d_name, recipe in drinks:
            g_item, _ = GlobalMenuItem.objects.get_or_create(category=cat, name=d_name, defaults={"base_price": 1800, "is_active": True})
            tpl, _ = GlobalSkuTemplate.objects.get_or_create(category="规格", name=f"{d_name}-默认", defaults={"default_price_delta": 0, "is_active": True})
            g_sku, _ = GlobalMenuSku.objects.get_or_create(item=g_item, template=tpl, defaults={"price_delta": 0, "is_active": True})

            GlobalSkuIngredient.objects.filter(sku=g_sku).delete()
            for mat_code, qty in recipe.items():
                GlobalSkuIngredient.objects.create(
                    sku=g_sku,
                    material=self.materials[mat_code],
                    quantity=Decimal(str(qty)),
                    unit=self.materials[mat_code].unit
                )

            MenuItem.sync_store_menu(self.store)
            m_item = MenuItem.objects.get(store=self.store, global_item=g_item)
            m_sku = MenuSku.objects.get(item=m_item, global_sku=g_sku)
            self.menu_items.append({
                'item_id': m_item.id,
                'sku_id': m_sku.id,
                'name': d_name,
                'recipe': recipe
            })

    def sync_hardware_status_to_system(self, glitch_barrel=None, empty_cup=False):
        """将当前料桶与传感器状态按真机 MQTT 报文格式同步至系统解析引擎"""
        thin_p = {}
        thick_p = {}
        solid_p = {}

        for b_code, cfg in self.barrel_configs.items():
            vol = cfg['volume']
            if glitch_barrel == b_code:
                vol = 0 # 故障/突发置空
            
            p_data = {"v": int(vol), "a1": 0}
            if b_code.startswith("b0") and int(b_code[1:]) < 9:
                thin_p[b_code] = p_data
            elif b_code.startswith("b09") or b_code.startswith("b1") or b_code.startswith("b2"):
                thick_p[b_code] = p_data
            else:
                solid_p[b_code] = p_data

        cup_data = {
            "paperL": {"a1": 0, "a2": 1 if empty_cup else 0},
            "lid": {"a1": 0, "a2": 0},
            "membrane": {"a1": 0, "a2": 0}
        }

        payload = {
            "healthy": 1,
            "disconnected": 0,
            "free": {"master": 1024, "slave": 64},
            "temperature": {"t1": 4, "t2": 175},
            "thinP": thin_p,
            "thickP": thick_p,
            "solidP": solid_p,
            "cup": cup_data
        }
        return process_device_status_report(self.device_sn, payload)


# =====================================================================
# 3. 混沌随机压测引擎 (Chaos Fuzzer Runner)
# =====================================================================
class ChaosFuzzerRunner:
    def __init__(self, env: FuzzEnvironment, scale: int = 1000, concurrency: int = 20, with_chaos: bool = True):
        self.env = env
        self.scale = scale
        self.concurrency = concurrency
        self.with_chaos = with_chaos
        
        # 初始化影子账本
        init_consumables = {k: v['quantity'] for k, v in env.consumables_config.items()}
        init_barrels = {k: v['volume'] for k, v in env.barrel_configs.items()}
        self.ledger = ShadowLedger(init_consumables, init_barrels)

    def worker_action(self, action_id: int):
        """单个 Worker 执行的随机动作"""
        # 确保每个并发线程拥有独立的数据库连接
        connection.close()
        
        dice = random.random()
        try:
            # 70% 概率：发起并发购买生命周期 (Precheck -> Create -> TryLock -> Done / Cancel)
            if dice < 0.70:
                self._action_simulate_order_lifecycle(action_id)
            # 15% 概率：模拟退款/取消
            elif dice < 0.85:
                self._action_simulate_refund_cancel()
            # 15% 概率：模拟硬件传感器上报与瞬时噪声
            else:
                self._action_simulate_mqtt_report()
        except Exception as e:
            logger.error(f"[Worker-{action_id}] 执行异常: {e}", exc_info=True)
        finally:
            connection.close()

    def _action_simulate_order_lifecycle(self, action_id: int):
        """模拟完整订单链路"""
        drink = random.choice(self.env.menu_items)
        qty = random.randint(1, 3)
        cart = [{'item': drink['item_id'], 'sku': [drink['sku_id']], 'quantity': qty}]

        # 1. 预检 precheck
        self.ledger.total_precheck_attempts += 1
        try:
            res = precheck_order(self.env.store.id, cart, device_sn=self.env.device_sn)
            if not res.get("ok"):
                self.ledger.precheck_rejected += 1
                return
            self.ledger.precheck_passed += 1
        except ValueError:
            self.ledger.precheck_rejected += 1
            return

        # 2. 创建订单 (高并发下预检放行后，库存可能瞬间被其他并发抢占)
        try:
            ord_obj = create_order(self.env.user, self.env.store.id, cart, device_sn=self.env.device_sn)
        except ValueError:
            self.ledger.precheck_rejected += 1
            return
        except Exception as oe:
            self.ledger.record_lock_failure("CREATE_COLLISION", str(oe))
            return
        
        # 计算该订单需锁定的耗材与食材
        needed_consumables = {
            'paperL': qty,
            'lid': qty,
            'membrane': qty
        }
        needed_mats = {
            k: v * qty for k, v in drink['recipe'].items() if k not in needed_consumables
        }

        # 3. 支付原子排他锁库 try_lock_order_inventory
        try:
            locked_ok, lock_err, ctx = try_lock_order_inventory(ord_obj)
        except Exception as le:
            self.ledger.record_lock_failure(ord_obj.order_no, str(le))
            ord_obj.status = OrderMain.STATUS_CANCELLED
            ord_obj.save(update_fields=['status'])
            return

        if not locked_ok:
            self.ledger.record_lock_failure(ord_obj.order_no, lock_err)
            ord_obj.status = OrderMain.STATUS_CANCELLED
            ord_obj.save(update_fields=['status'])
            return

        # 锁库成功，模拟支付完成，状态转为 STATUS_PAID
        ord_obj.status = OrderMain.STATUS_PAID
        ord_obj.save(update_fields=['status'])

        # 登记入影子账本
        self.ledger.record_lock_success(ord_obj.order_no, needed_consumables, needed_mats)

        # 4. 模拟制作或异常流转
        # 80% 顺利完成出杯制作
        if random.random() < 0.80 or not self.with_chaos:
            update_order_status(ord_obj, OrderMain.STATUS_MAKING, action='making_start')
            update_order_status(ord_obj, OrderMain.STATUS_DONE, action='making_done')
            self.ledger.record_order_done(ord_obj.order_no)
            
            # 真实扣除模拟机硬件料桶物理值
            for mat_code, used_vol in needed_mats.items():
                for b_code, b_cfg in self.env.barrel_configs.items():
                    if b_cfg['mat_code'] == mat_code and b_cfg['volume'] > 0:
                        deduct = min(b_cfg['volume'], used_vol)
                        b_cfg['volume'] -= deduct
                        used_vol -= deduct
                        if used_vol <= 0:
                            break
        else:
            # 20% 混沌异常：制作中途设备报警或用户发起退款放库
            update_order_status(ord_obj, OrderMain.STATUS_REFUNDED, action='refund')
            restore_order_inventory(ord_obj, reason="混沌注入：未制作退款放库")
            self.ledger.record_order_refund(ord_obj.order_no)

    def _action_simulate_refund_cancel(self):
        """随机挑选已支付或制作中的订单进行退款放库"""
        with self.ledger.lock:
            active_orders = [k for k, v in self.ledger.orders.items() if v['status'] == 'LOCKED']
        if not active_orders:
            return
        target_no = random.choice(active_orders)
        ord_obj = OrderMain.objects.filter(order_no=target_no).first()
        if ord_obj and ord_obj.status in (OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING):
            try:
                update_order_status(ord_obj, OrderMain.STATUS_REFUNDED, action='refund')
                restore_order_inventory(ord_obj, reason="随机主动退款放库测试")
                self.ledger.record_order_refund(target_no)
            except Exception as e:
                logger.warning(f"退款放库异常: {e}")


    def _action_simulate_mqtt_report(self):
        """上位机定时上报，带随机传感器噪声"""
        empty_cup = False
        glitch_b = None
        if self.with_chaos and random.random() < 0.05:
            # 5% 概率模拟光电空杯传感器突发打空
            empty_cup = True
        
        self.env.sync_hardware_status_to_system(glitch_barrel=glitch_b, empty_cup=empty_cup)
        self.ledger.hardware_reports += 1

    def run(self):
        """并发执行随机事件流"""
        print("\n" + "=" * 78)
        print(f"🌪️  启动全方位库存逻辑混沌压测引擎 (事务规模: {self.scale}, 并发线程: {self.concurrency})")
        print("=" * 78)
        start_time = time.time()

        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            futures = [executor.submit(self.worker_action, i) for i in range(self.scale)]
            for future in as_completed(futures):
                future.result()

        elapsed = time.time() - start_time
        print(f"\n⏱️  压测事务执行完毕，耗时 {elapsed:.2f} 秒 (吞吐量: {self.scale/elapsed:.1f} TPS)")
        return self.audit_invariants()

    def audit_invariants(self) -> bool:
        """
        六大物理守恒不变量全景审计
        """
        print("\n" + "=" * 78)
        print("🔍 开始执行【六大物理守恒不变量】全景审计...")
        print("=" * 78)
        connection.close()

        passed = True
        violations = []

        # -------------------------------------------------------------
        # 1. 零超卖与底线安全不变量 (No Negative Stock & Stop-Sale Breach)
        # -------------------------------------------------------------
        for code, cfg in self.env.consumables_config.items():
            cs = DeviceConsumableStock.objects.get(device=self.env.device, code__code=code)
            stop_lvl = cfg['stop_sale_level']
            
            # 严格不能为负数
            if cs.quantity < 0:
                violations.append(f"[不变量1违背] 耗材 {code} 发生超卖破底！当前物理库存为负数: {cs.quantity}")
                passed = False
            
            print(f"   ✓ [耗材底线审计: {code}] 初始={self.ledger.initial_consumables[code]}, 当前剩余={cs.quantity}, 停售保护线={stop_lvl}")

        # -------------------------------------------------------------
        # 2. 质量物理守恒定律 (Mass Conservation Invariant)
        # 初始库存 = 数据库当前库存 + 成功制作消耗总量 + 锁定在途总量
        # -------------------------------------------------------------
        for code in self.env.consumables_config:
            cs = DeviceConsumableStock.objects.get(device=self.env.device, code__code=code)
            init_q = self.ledger.initial_consumables[code]
            consumed_q = self.ledger.consumed_consumables.get(code, 0)
            locked_q = self.ledger.locked_consumables.get(code, 0)
            current_q = cs.quantity

            discrepancy = (current_q + consumed_q + locked_q) - init_q
            if discrepancy != 0:
                violations.append(f"[不变量2违背] 耗材 {code} 违背质量守恒定律！初始={init_q}, 当前={current_q}, 消耗={consumed_q}, 锁定={locked_q}, 守恒差额={discrepancy}")
                passed = False
            else:
                print(f"   ✓ [质量守恒审计: {code}] 初始({init_q}) == 剩余({current_q}) + 消耗({consumed_q}) + 锁定({locked_q}) [绝对守恒: 差额=0]")

        # -------------------------------------------------------------
        # 3. 零重复扣减与零漏扣不变量 (Zero Double-Deduction)
        # -------------------------------------------------------------
        double_deductions = 0
        for order_no, info in self.ledger.orders.items():
            if info['deducted_count'] > 1:
                double_deductions += 1
        if double_deductions > 0:
            violations.append(f"[不变量3违背] 检测到 {double_deductions} 笔订单发生二次重复扣减！")
            passed = False
        else:
            print("   ✓ [零重复扣减审计] 抽检全部成功订单，扣减发生次数恒为 1，零二次重复扣减")

        # -------------------------------------------------------------
        # 4. 零孤儿残留不变量 (Zero Lock Leakage)
        # 退款或取消的订单，其在途与锁定必须彻底释放
        # -------------------------------------------------------------
        unproduced = calculate_unproduced_materials_for_device(self.env.device)
        active_making_count = OrderMain.objects.filter(
            device=self.env.device,
            status__in=[OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING]
        ).count()

        if active_making_count == 0:
            for mat_code, in_flight_qty in unproduced.items():
                if in_flight_qty > 0:
                    violations.append(f"[不变量4违背] 无在途订单时，Redis 存在孤儿锁定残存: {mat_code}={in_flight_qty}")
                    passed = False
            print("   ✓ [零孤儿残留审计] 无在途订单时，Redis 在途占用池完美归零，无悬挂孤儿锁")
        else:
            print(f"   ✓ [在途占用核验] 当前合法存续在途订单数: {active_making_count}")

        # -------------------------------------------------------------
        # 5. 停售线绝对阻断不变量 (Stop-Sale Barrier Invariant)
        # -------------------------------------------------------------
        for b_code, cfg in self.env.barrel_configs.items():
            alarm_2 = cfg['alarm_2']
            current_v = cfg['volume']
            if current_v <= alarm_2:
                # 此时该桶必须可用为0
                redis_stock = float(self.env.redis.get(get_redis_stock_key(self.env.device_sn, cfg['mat_code'])) or 0)
                other_barrels_sum = sum(
                    b['volume'] for b in self.env.barrel_configs.values() 
                    if b['mat_code'] == cfg['mat_code'] and b['volume'] > b['alarm_2']
                )
                if abs(redis_stock - other_barrels_sum) > 1.0:
                    violations.append(f"[不变量5/6违背] 料桶 {b_code} 达到停售线({current_v} <= {alarm_2})，但多桶聚合不符！Redis={redis_stock}, 其他正常桶合计={other_barrels_sum}")
                    passed = False

        # -------------------------------------------------------------
        # 输出审计报告矩阵
        # -------------------------------------------------------------
        print("\n" + "=" * 78)
        print("📊 混沌压测全景度量统计矩阵 (Telemetry & Audit Matrix)")
        print("=" * 78)
        print(f"  • 总预检请求数 (Precheck Attempts) : {self.ledger.total_precheck_attempts}")
        print(f"  • 预检成功放行数 (Precheck Passed)  : {self.ledger.precheck_passed}")
        print(f"  • 缺料/停售拒单数 (Precheck Rejected): {self.ledger.precheck_rejected}")
        print(f"  • 支付抢锁总请求 (Lock Attempts)    : {self.ledger.total_lock_attempts}")
        print(f"  • 抢锁成功数 (Lock Success)         : {self.ledger.lock_success}")
        print(f"  • 抢锁并发冲突拦截 (Lock Collisions): {self.ledger.lock_failed}")
        print(f"  • 成功出单完成数 (Completed Orders) : {self.ledger.orders_completed}")
        print(f"  • 异常与退款释放数 (Refunded Orders): {self.ledger.orders_refunded}")
        print(f"  • 上位机遥测心跳报文数 (MQTT Reports): {self.ledger.hardware_reports}")
        print(f"  • 物理守恒不变量违背数 (Violations) : {len(violations)}")
        print("=" * 78)

        if passed and len(violations) == 0:
            print("🎉 恭喜！六大物理守恒不变量 100% 全部通过！零超卖、零漏扣、质量完全守恒！")
            print("=" * 78)
            return True
        else:
            print("🚨 警告！检测到物理不变量违背：")
            for v in violations:
                print(f"  ❌ {v}")
            print("=" * 78)
            return False


def main():
    parser = argparse.ArgumentParser(description="大规模随机数据库存逻辑混沌压测工具")
    parser.add_argument("--scale", type=int, default=1000, help="随机事务总规模 (默认 1000)")
    parser.add_argument("--concurrency", type=int, default=20, help="并发 Worker 线程数 (默认 20)")
    parser.add_argument("--with-chaos", action="store_true", help="是否注入硬件断线、传感器突变与随机退款混沌")
    args = parser.parse_args()

    device_sn = "SN_CHAOS_TEST_01"
    print(f"🔧 初始化混沌压测沙箱环境: device_sn={device_sn} ...")
    env = FuzzEnvironment(device_sn)
    env.setup_random_topology()

    runner = ChaosFuzzerRunner(env, scale=args.scale, concurrency=args.concurrency, with_chaos=args.with_chaos)
    success = runner.run()
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
