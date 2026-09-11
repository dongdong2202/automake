#!/usr/bin/env python3
"""
真实 MQTT 回环高频上报与并发下单对撞压测 (Real MQTT Broker Loopback & Order Concurrency Stress)

测试链路：
1. 独立的上位机模拟线程通过 paho-mqtt 连接 127.0.0.1:1883，每隔 0.5~1.0 秒高频上报实时传感器状态。
2. 多个并发用户线程同时发起下单、预检、支付锁库、出杯完成和退款。
3. 检验在真实 MQTT 协议网络消息与高频业务流双向交替冲撞下，Redis 料桶基准值与 MySQL 耗材账目的守恒性与可靠性。
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
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')
import django
django.setup()

import paho.mqtt.client as mqtt
from django.contrib.auth import get_user_model
from django.db import connection
from django_redis import get_redis_connection

from global_config.models import DeviceModel, GlobalMenuCategory, GlobalMenuItem, GlobalSkuTemplate, GlobalMenuSku, GlobalSkuIngredient
from stores.models import Store
from devices.models import Device, DeviceBarrelDict, DeviceConsumableStock
from inventory.models import Material
from menus.models import MenuItem, MenuSku
from orders.models import OrderMain
from orders.services import precheck_order, create_order, try_lock_order_inventory, update_order_status, restore_order_inventory, get_redis_stock_key

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("MqttLoopbackStress")
logging.getLogger("orders.services").setLevel(logging.WARNING)
logging.getLogger("monitor").setLevel(logging.WARNING)
logging.getLogger("payments.services").setLevel(logging.WARNING)
logging.getLogger("mqtt").setLevel(logging.WARNING)


class MqttStressHarness:
    def __init__(self, device_sn="SN_MQTT_STRESS_01", duration_sec=20, concurrency=10):
        self.device_sn = device_sn
        self.duration_sec = duration_sec
        self.concurrency = concurrency
        self.redis = get_redis_connection("default")
        self.stop_event = threading.Event()
        
        # 统计指标
        self.published_mqtt_count = 0
        self.orders_attempted = 0
        self.orders_locked = 0
        self.orders_completed = 0
        self.orders_refunded = 0
        self.shortage_rejected = 0

        # 硬件物理余量模拟
        self.hardware_milk = 5000  # ml
        self.hardware_beans = 2000  # g
        self.cup_empty_sensor = False
        self.lock = threading.Lock()

    def setup_environment(self):
        """准备测试设备、多料桶映射与耗材"""
        User = get_user_model()
        user, _ = User.objects.get_or_create(username="mqtt_stress_user", defaults={"is_staff": True})
        store, _ = Store.objects.get_or_create(code="MQTT_STORE", defaults={"name": "MQTT对撞测试自营店", "contact_phone": "13900009999"})
        dev_model, _ = DeviceModel.objects.get_or_create(code="MQTT_DEV_MODEL", defaults={"name": "MQTT对撞机型"})
        
        device, _ = Device.objects.get_or_create(
            device_sn=self.device_sn,
            defaults={"device_name": "MQTT对撞测试咖啡机", "store": store, "device_model": dev_model, "status": Device.STATUS_ONLINE}
        )
        device.status = Device.STATUS_ONLINE
        device.save()

        # 物料
        mat_milk, _ = Material.objects.get_or_create(code="fresh_milk", defaults={"name": "鲜牛奶", "unit": "ml"})
        mat_bean, _ = Material.objects.get_or_create(code="coffee_bean", defaults={"name": "咖啡豆", "unit": "g"})
        mat_cup, _ = Material.objects.get_or_create(code="paperL", defaults={"name": "纸杯", "unit": "个", "material_type": "cup"})
        mat_lid, _ = Material.objects.get_or_create(code="lid", defaults={"name": "杯盖", "unit": "个", "material_type": "consumable"})
        mat_membrane, _ = Material.objects.get_or_create(code="membrane", defaults={"name": "封口膜", "unit": "张", "material_type": "consumable"})

        # 料桶字典
        DeviceBarrelDict.objects.filter(device=device).delete()
        DeviceBarrelDict.objects.create(device=device, barrel_code="b01", material=mat_milk, alarm_threshold_1=Decimal('1000.00'), alarm_threshold_2=Decimal('200.00'), created_by=user)
        DeviceBarrelDict.objects.create(device=device, barrel_code="b02", material=mat_milk, alarm_threshold_1=Decimal('1000.00'), alarm_threshold_2=Decimal('200.00'), created_by=user)
        DeviceBarrelDict.objects.create(device=device, barrel_code="b32", material=mat_bean, alarm_threshold_1=Decimal('500.00'), alarm_threshold_2=Decimal('100.00'), created_by=user)

        # 耗材库存: 100 纸杯，停售线 5
        self.init_cups = 100
        for m, q in [(mat_cup, self.init_cups), (mat_lid, self.init_cups), (mat_membrane, self.init_cups)]:
            DeviceConsumableStock.objects.update_or_create(
                device=device, code=m,
                defaults={"quantity": q, "init_quantity": q, "warn_level": 20, "stop_sale_level": 5}
            )

        # 商品菜单
        cat, _ = GlobalMenuCategory.objects.get_or_create(device_model=dev_model, name="MQTT咖啡", defaults={"sort_order": 1, "is_active": True})
        g_item, _ = GlobalMenuItem.objects.get_or_create(category=cat, name="对撞拿铁", defaults={"base_price": 1500, "is_active": True})
        tpl, _ = GlobalSkuTemplate.objects.get_or_create(category="规格", name="标准", defaults={"default_price_delta": 0, "is_active": True})
        g_sku, _ = GlobalMenuSku.objects.get_or_create(item=g_item, template=tpl, defaults={"price_delta": 0, "is_active": True})

        GlobalSkuIngredient.objects.filter(sku=g_sku).delete()
        GlobalSkuIngredient.objects.create(sku=g_sku, material=mat_milk, quantity=Decimal("150.00"))
        GlobalSkuIngredient.objects.create(sku=g_sku, material=mat_bean, quantity=Decimal("15.00"))
        GlobalSkuIngredient.objects.create(sku=g_sku, material=mat_cup, quantity=Decimal("1.00"))

        MenuItem.sync_store_menu(store)
        self.menu_item = MenuItem.objects.get(store=store, global_item=g_item)
        self.menu_sku = MenuSku.objects.get(item=self.menu_item, global_sku=g_sku)
        self.user = user
        self.store = store
        self.device = device

        # 清理已有在途订单与 Redis
        OrderMain.objects.filter(device=device).delete()
        for k in self.redis.keys(f"automake:*:{self.device_sn}:*"):
            self.redis.delete(k)

    def hardware_publisher_loop(self):
        """上位机真实 MQTT 发布线程"""
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"sim_hw_{self.device_sn}_{int(time.time()*1000)}",
            transport="tcp"
        )
        from django.conf import settings
        if getattr(settings, 'MQTT_USERNAME', None):
            client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD)
        topic = f"c2s/shop/{self.device_sn}/state/selfPack"
        try:
            client.connect("127.0.0.1", 1883, keepalive=30)
            client.loop_start()
            
            while not self.stop_event.is_set():
                with self.lock:
                    b01_v = self.hardware_milk // 2
                    b02_v = self.hardware_milk - b01_v
                    b32_v = self.hardware_beans
                    empty_flag = self.cup_empty_sensor

                payload = {
                    "healthy": 1,
                    "disconnected": 0,
                    "free": {"master": 1024, "slave": 64},
                    "temperature": {"t1": 4, "t2": 175},
                    "thinP": {"b01": {"v": int(b01_v), "a1": 0}, "b02": {"v": int(b02_v), "a1": 0}},
                    "thickP": {},
                    "solidP": {"b32": {"v": int(b32_v), "a1": 0}},
                    "cup": {"paperL": {"a1": 0, "a2": 1 if empty_flag else 0}, "lid": {"a1": 0, "a2": 0}, "membrane": {"a1": 0, "a2": 0}}
                }
                client.publish(topic, json.dumps(payload), qos=1)
                self.published_mqtt_count += 1
                time.sleep(0.3)  # 每 300ms 上报一次，构成高频对撞
        except Exception as e:
            logger.error(f"MQTT Publisher 异常: {e}")
        finally:
            client.loop_stop()
            client.disconnect()

    def user_order_worker(self, worker_id: int):
        """并发下单工作线程"""
        cart = [{'item': self.menu_item.id, 'sku': [self.menu_sku.id], 'quantity': 1}]
        
        while not self.stop_event.is_set():
            connection.close()
            self.orders_attempted += 1
            
            # 1. 预检
            try:
                res = precheck_order(self.store.id, cart, device_sn=self.device_sn)
                if not res.get("ok"):
                    self.shortage_rejected += 1
                    time.sleep(0.05)
                    continue
            except ValueError:
                self.shortage_rejected += 1
                time.sleep(0.05)
                continue

            # 2. 创建订单
            try:
                ord_obj = create_order(self.user, self.store.id, cart, device_sn=self.device_sn)
            except Exception:
                self.shortage_rejected += 1
                continue

            # 3. 抢锁
            try:
                locked_ok, lock_err, ctx = try_lock_order_inventory(ord_obj)
            except Exception:
                ord_obj.status = OrderMain.STATUS_CANCELLED
                ord_obj.save(update_fields=['status'])
                continue

            if not locked_ok:
                ord_obj.status = OrderMain.STATUS_CANCELLED
                ord_obj.save(update_fields=['status'])
                continue

            self.orders_locked += 1
            ord_obj.status = OrderMain.STATUS_PAID
            ord_obj.save(update_fields=['status'])

            # 4. 模拟制作或中途退款
            time.sleep(random.uniform(0.05, 0.15))
            if random.random() < 0.85:
                update_order_status(ord_obj, OrderMain.STATUS_MAKING, action='making_start')
                update_order_status(ord_obj, OrderMain.STATUS_DONE, action='making_done')
                self.orders_completed += 1
                with self.lock:
                    self.hardware_milk = max(0, self.hardware_milk - 150)
                    self.hardware_beans = max(0, self.hardware_beans - 15)
            else:
                update_order_status(ord_obj, OrderMain.STATUS_REFUNDED, action='refund')
                restore_order_inventory(ord_obj, reason='MQTT对撞中途退款')
                self.orders_refunded += 1

    def run(self):
        print("\n" + "=" * 78)
        print(f"📡 启动真实本地 MQTT Broker 回环高频对撞压测 (持续时间: {self.duration_sec}s, 用户并发: {self.concurrency})")
        print("=" * 78)
        self.setup_environment()

        # 启动 MQTT 上报线程
        mqtt_thread = threading.Thread(target=self.hardware_publisher_loop, daemon=True)
        mqtt_thread.start()
        for _ in range(50):
            if self.redis.get(f"automake:stock:{self.device_sn}:fresh_milk"):
                break
            time.sleep(0.1)

        # 启动多线程用户池
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            user_futures = [executor.submit(self.user_order_worker, i) for i in range(self.concurrency)]
            
            # 运行指定时长
            time.sleep(self.duration_sec)
            self.stop_event.set()

        mqtt_thread.join(timeout=2.0)
        connection.close()

        # 验证物理不变量
        print("\n" + "=" * 78)
        print("🔍 验证真实 MQTT 对撞下的物理守恒与底线安全...")
        print("=" * 78)

        cs_cup = DeviceConsumableStock.objects.get(device=self.device, code__code="paperL")
        current_cups = cs_cup.quantity
        print(f"  • MQTT 高频报文发布总数: {self.published_mqtt_count}")
        print(f"  • 用户发起下单总尝试数: {self.orders_attempted}")
        print(f"  • 缺料/停售安全拦截数  : {self.shortage_rejected}")
        print(f"  • 锁库成功总订单数    : {self.orders_locked}")
        print(f"  • 制作出餐完成订单数  : {self.orders_completed}")
        print(f"  • 退款释放回库订单数  : {self.orders_refunded}")
        print(f"  • 纸杯初始库存        : {self.init_cups}")
        print(f"  • 纸杯当前物理剩余    : {current_cups}")

        # 核心断言
        assert current_cups >= 5, f"纸杯跌穿 5 个停售保护线！当前={current_cups}"
        expected_cups = self.init_cups - self.orders_completed
        assert current_cups == expected_cups, f"质量守恒违背！当前={current_cups}, 期望={expected_cups} (初始{self.init_cups} - 出餐{self.orders_completed})"
        
        print(f"   ✓ [质量守恒通过] 纸杯物理剩余({current_cups}) == 初始({self.init_cups}) - 成功制作({self.orders_completed}) [差额绝对为 0]")
        print(f"   ✓ [停售底线通过] 纸杯物理剩余({current_cups}) >= 5 (未击穿停售保护底线)")
        print("🎉 真实 MQTT Broker 回环高频对撞压测 100% 成功！账实绝对相符！\n" + "=" * 78)
        return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="MQTT Broker 回环高频对撞压测")
    parser.add_argument("--duration", type=int, default=15, help="持续测试秒数 (默认 15)")
    parser.add_argument("--concurrency", type=int, default=10, help="并发用户线程数 (默认 10)")
    args = parser.parse_args()

    harness = MqttStressHarness(duration_sec=args.duration, concurrency=args.concurrency)
    harness.run()
