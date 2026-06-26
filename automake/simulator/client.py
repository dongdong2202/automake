"""
上位机与业务流程模拟器 (Upper Machine & Business Flow Simulator)

本模块实现了一个独立的模拟类 `UpperMachineSimulator`，并在其下配置了完整的端到端自动化业务测试。
本文件可以直接执行：
1. 启动 Django 的 WSGI 开发服务于后台线程中。
2. 自动化清空并初始化数据库中的门店、设备、物料配置、耗材以及初始库存。
3. 清除相关 Redis 缓存与分布式锁。
4. 模拟微信小程序点单端：拉取菜单、购物车选品、预结算、创建订单、获取支付参数、构造真实的微信支付成功回调。
5. 模拟上位机硬件端：长连接连接本地 MQTT 代理服务（1883端口），接收来自云端的制作（make）指令，自动调用 HTTP 库存锁定/扣除接口，并通过 MQTT 上报制作进度。
6. 自动验证数据库与 Redis 中的最终耗材数量扣减状态。
"""

import os
import sys
import time
import json
import random
import string
import base64
import logging
import threading
import requests
import paho.mqtt.client as mqtt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# 设置基本日志配置
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s [%(name)s:%(lineno)d] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("Simulator")

# 1. 将项目根目录添加到 sys.path 并初始化 Django 框架环境
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DEBUG', 'True')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')
import random
# 避免与其它运行的容器产生 Client ID 冲突
os.environ['MQTT_CLIENT_ID'] = f"django-server-test-{random.randint(1000, 9999)}"
import django
django.setup()

# 1.5 强力 Mock WechatPayV3 避免真实的微信 API 访问和证书缺失报错
from utils.wechat import WechatPayV3
from django.conf import settings

def mock_init(self):
    self.mch_id = getattr(settings, 'WECHAT_PAY_MCH_ID', 'mock_mch')
    self.api_v3_key = getattr(settings, 'WECHAT_PAY_API_V3_KEY', '')
    if not self.api_v3_key or len(self.api_v3_key) not in (16, 24, 32):
        self.api_v3_key = 'abcdefghijklmnopqrstuvwxyz123456'
    self.cert_serial = getattr(settings, 'WECHAT_PAY_CERT_SERIAL', 'mock_serial')
    self.notify_url = getattr(settings, 'WECHAT_PAY_NOTIFY_URL', 'http://127.0.0.1:8001/api/pay/callback')
    self._private_key = None

def mock_create_jsapi_order(self, out_trade_no: str, amount: int, openid: str, description: str) -> dict:
    import uuid
    logger.info(f"[MockWechatPay] Mocking JSAPI order creation for out_trade_no={out_trade_no}")
    return {"prepay_id": f"mock_prepay_{uuid.uuid4().hex}"}

def mock_build_pay_params(self, prepay_id: str) -> dict:
    return {
        "appId": "mock_appid",
        "timeStamp": str(int(time.time())),
        "nonceStr": "mock_nonce",
        "package": f"prepay_id={prepay_id}",
        "signType": "RSA",
        "paySign": "mock_sign"
    }

WechatPayV3.__init__ = mock_init
WechatPayV3.create_jsapi_order = mock_create_jsapi_order
WechatPayV3.build_pay_params = mock_build_pay_params

# 导入 Django 模型、服务以及视图逻辑
from django.utils import timezone
from users.models import User
from stores.models import Store
from devices.models import Device, DeviceMaterialStock, DeviceConsumableStock
from inventory.models import Material
from global_config.models import DeviceModel, GlobalMenuCategory, GlobalMenuItem, GlobalMenuSku, GlobalSkuIngredient
from menus.models import MenuItem, MenuSku
from orders.models import OrderMain


def timezone_iso_now() -> str:
    """获取当前时间 ISO 格式"""
    return timezone.now().isoformat()


def start_wsgi_server(host='127.0.0.1', port=8000):
    """
    在后台线程中启动 Django 的 WSGI 服务器
    
    使用此机制可以确保模拟器测试不需要手动在另一终端启动 runserver。
    如果 8000 端口已被占用（例如手动运行了 runserver），将安全跳过并复用现有服务。
    """
    from django.core.servers.basehttp import get_internal_wsgi_application, run
    
    def serve():
        try:
            logger.info(f"[WSGI服务器] 正在后台启动内嵌 Django Web 服务 {host}:{port}...")
            application = get_internal_wsgi_application()
            run(host, port, application, threading=True)
        except Exception as e:
            logger.warning(f"[WSGI服务器] 内嵌服务启动被忽略（可能是已有服务器在运行或端口被占用）: {e}")

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    time.sleep(1.5)  # 留出时间让服务器 socket 绑定监听


def clear_redis_keys(device_sn: str):
    """
    清理 Redis 中有关该设备的测试缓存、库存及短信防抖锁
    """
    from django_redis import get_redis_connection
    try:
        redis_conn = get_redis_connection("default")
        # 查找对应 SN 的所有缓存键并删除
        keys = redis_conn.keys(f"automake:stock:{device_sn}:*")
        keys.extend(redis_conn.keys(f"automake:sms_sent:{device_sn}:*"))
        if keys:
            redis_conn.delete(*keys)
            logger.info(f"[Redis清理] 成功清除该设备相关的 Redis 键: {keys}")
    except Exception as e:
        logger.warning(f"[Redis清理] 清除 Redis 缓存发生异常: {e}")


def prepare_db_data():
    """
    清除测试订单，并配置、同步所需的门店、设备、物料及全局商品配方数据
    """
    logger.info("[数据准备] 开始重置并预置数据库测试数据...")

    # 导入关联模型，防止 ProtectedError 并清理旧的订单与支付记录
    from payments.models import PaymentRecord
    from orders.models import ProductionTask, OrderStatusLog
    
    PaymentRecord.objects.all().delete()
    ProductionTask.objects.all().delete()
    OrderStatusLog.objects.all().delete()
    OrderMain.objects.all().delete()

    # 清除旧的设备及其关联的库存、日志和指令（避免 SN 大小写冲突或残留干扰）
    from devices.models import Device, DeviceCommand, DeviceStatusLog, DeviceAlarm, DeviceMaterialStock, DeviceConsumableStock
    DeviceCommand.objects.all().delete()
    DeviceStatusLog.objects.all().delete()
    DeviceAlarm.objects.all().delete()
    DeviceMaterialStock.objects.all().delete()
    DeviceConsumableStock.objects.all().delete()
    Device.objects.all().delete()

    # 1. 门店配置
    store, _ = Store.objects.update_or_create(
        id=100000,
        defaults={
            'name': '模拟智能自营店',
            'code': 'TEST-KEY-001',
            'status': Store.STATUS_OPEN,
            'contact_phone': '13800138000'
        }
    )
    store.status = Store.STATUS_OPEN
    store.save()

    # 2. 设备型号配置
    dev_model, _ = DeviceModel.objects.get_or_create(
        code='coffee_maker',
        defaults={'name': '智能自制咖啡机'}
    )

    # 3. 设备配置
    device, _ = Device.objects.update_or_create(
        device_sn='sn001',
        defaults={
            'store': store,
            'device_name': '模拟上位机001号机',
            'device_model': dev_model,
            'key_code': 'TEST-KEY-001',
            'status': Device.STATUS_ONLINE
        }
    )
    device.status = Device.STATUS_ONLINE
    device.save()

    # 4. 物料基础表配置 (食材与耗材)
    inv_bean, _ = Material.objects.update_or_create(
        code='coffee_bean',
        defaults={
            'name': '咖啡豆',
            'unit': 'g',
            'material_type': Material.TYPE_INGREDIENT,
            'shelf_life': '12个月',
            'storage_conditions': '常温干燥'
        }
    )
    inv_milk, _ = Material.objects.update_or_create(
        code='fresh_milk',
        defaults={
            'name': '鲜牛奶',
            'unit': 'ml',
            'material_type': Material.TYPE_INGREDIENT,
            'shelf_life': '3天',
            'storage_conditions': '冷藏(2-8℃)'
        }
    )
    
    # 耗材大纸杯
    m_cup, _ = Material.objects.update_or_create(
        code='paperL',
        defaults={
            'name': '大纸杯',
            'unit': '个',
            'material_type': Material.TYPE_CONSUMABLE,
            'shelf_life': '永久',
            'storage_conditions': '防潮'
        }
    )
    # 耗材杯盖
    m_lid, _ = Material.objects.update_or_create(
        code='lid',
        defaults={
            'name': '杯盖',
            'unit': '个',
            'material_type': Material.TYPE_CONSUMABLE,
            'shelf_life': '永久',
            'storage_conditions': '防潮'
        }
    )

    # 5. 上报/配置设备食材库存 (DeviceMaterialStock - 高度监控)
    DeviceMaterialStock.objects.update_or_create(
        device=device,
        code='coffee_bean',
        defaults={
            'name': inv_bean,
            'initHight': 100,
            'current_remaining_height': 85.0,
            'unit': 'cm',
            'warn_level': 10.0
        }
    )
    DeviceMaterialStock.objects.update_or_create(
        device=device,
        code='fresh_milk',
        defaults={
            'name': inv_milk,
            'initHight': 1000,
            'current_remaining_height': 500.0,
            'unit': 'cm',
            'warn_level': 100.0
        }
    )

    # 6. 配置设备耗材库存 (DeviceConsumableStock - 计数物理扣除)
    # 杯子设定为 90 个 (warn_level=20)
    DeviceConsumableStock.objects.update_or_create(
        device=device,
        code=m_cup,
        defaults={
            'init_quantity': 100,
            'quantity': 90,
            'unit': '个',
            'warn_level': 20
        }
    )
    # 杯盖设定为 21 个 (扣减2个后将触发预警)
    DeviceConsumableStock.objects.update_or_create(
        device=device,
        code=m_lid,
        defaults={
            'init_quantity': 100,
            'quantity': 21,
            'unit': '个',
            'warn_level': 20
        }
    )

    # 7. 全局菜单与规格配料配方设置
    category, _ = GlobalMenuCategory.objects.get_or_create(
        device_model=dev_model,
        name='热饮特调',
        defaults={'sort_order': 1, 'is_active': True}
    )
    
    g_item, _ = GlobalMenuItem.objects.get_or_create(
        category=category,
        name='经典拿铁',
        defaults={'base_price': 1500, 'is_active': True}
    )

    g_sku, _ = GlobalMenuSku.objects.get_or_create(
        item=g_item,
        name='大杯/热',
        defaults={'price_delta': 300, 'is_active': True}
    )
    
    GlobalSkuIngredient.objects.update_or_create(sku=g_sku, material=inv_bean, defaults={'quantity': 15})
    GlobalSkuIngredient.objects.update_or_create(sku=g_sku, material=inv_milk, defaults={'quantity': 150})

    # 同步门店菜单
    MenuItem.sync_store_menu(store)

    # 确保数据库里至少有一个微信测试用户
    User.objects.get_or_create(
        openid='dev-test-openid',
        defaults={
            'username': 'dev_tester',
            'nickname': '微信开发模拟账号'
        }
    )
    logger.info("[数据准备] 基础测试数据预置完毕！")


class UpperMachineSimulator:
    """
    上位机设备与微信小程序点单端的一体化流程模拟类
    """
    def __init__(self, server_url="http://127.0.0.1:8000", mqtt_host="127.0.0.1", mqtt_port=1883, device_sn="sn001", key_code="TEST-KEY-001", store_id=100000):
        self.server_url = server_url.rstrip('/')
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.device_sn = device_sn
        self.key_code = key_code
        self.store_id = store_id
        
        self.cart = {}
        self.session = requests.Session()
        
        # 加载微信支付解密密钥
        self.api_v3_key = self._load_api_v3_key()
        
        # 默认配方
        self.recipes = {
            "经典拿铁": {"coffee_bean": 15, "fresh_milk": 150}
        }
        
        # MQTT 客户端配置
        self.mqtt_client = None
        self.mqtt_connected = False
        self.is_making = False
        self.active_order_no = None
        self.force_fail = False
        self.fail_reason = ""

    def _load_api_v3_key(self) -> str:
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            env_path = os.path.join(os.path.dirname(base_dir), '.env')
            if os.path.exists(env_path):
                with open(env_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.startswith('WECHAT_PAY_API_V3_KEY='):
                            key = line.strip().split('=', 1)[1]
                            if key and len(key) in (16, 24, 32):
                                return key
        except Exception:
            pass
        return "abcdefghijklmnopqrstuvwxyz123456"

    # ============================================================
    # 模拟微信小程序点单端逻辑
    # ============================================================

    def add_to_cart(self, item_id: int, sku_ids: list, quantity: int = 1):
        key = (item_id, tuple(sku_ids))
        self.cart[key] = self.cart.get(key, 0) + quantity
        logger.info(f"[微信端] 添加商品 ID={item_id}, 规格={sku_ids}, 数量={quantity} 到购物车")

    def precheck_order(self) -> dict:
        items_payload = []
        for (item_id, sku_ids), qty in self.cart.items():
            items_payload.append({
                "item": item_id,
                "sku": list(sku_ids),
                "quantity": qty
            })
        payload = {"store_id": self.store_id, "items": items_payload}
        url = f"{self.server_url}/api/order/precheck"
        response = self.session.post(url, json=payload, timeout=5)
        if response.status_code == 200:
            return response.json().get('data', {})
        else:
            logger.error(f"[微信端] 预校验接口失败: HTTP {response.status_code}, 内容: {response.text}")
        return {}

    def create_order(self, remark: str = "") -> str:
        items_payload = []
        for (item_id, sku_ids), qty in self.cart.items():
            items_payload.append({
                "item": item_id,
                "sku": list(sku_ids),
                "quantity": qty
            })
        payload = {"store_id": self.store_id, "items": items_payload, "remark": remark}
        url = f"{self.server_url}/api/order/create"
        response = self.session.post(url, json=payload, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get('code') == 0:
                return data['data'].get('order_no', '')
            else:
                logger.error(f"[微信端] 下单接口业务失败: {data.get('message')}")
        else:
            logger.error(f"[微信端] 下单接口 HTTP 失败: HTTP {response.status_code}, 内容: {response.text}")
        return ""

    def create_pay_request(self, order_no: str) -> dict:
        url = f"{self.server_url}/api/pay/create"
        response = self.session.post(url, json={"order_no": order_no}, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get('code') == 0:
                return data['data']
        return {}

    def simulate_payment(self, order_no: str, amount_cents: int) -> bool:
        logger.info(f"[微信端] 正在构造模拟微信回调确认，金额: {amount_cents/100:.2f}元")
        plaintext_data = {
            "out_trade_no": order_no,
            "transaction_id": f"WX{int(time.time()*1000)}{random.randint(100, 999)}",
            "success_time": timezone_iso_now(),
            "amount": {
                "payer_total": amount_cents,
                "total": amount_cents,
                "currency": "CNY"
            }
        }
        try:
            nonce = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
            associated_data_str = "transaction"
            aesgcm = AESGCM(self.api_v3_key.encode('utf-8'))
            plaintext_bytes = json.dumps(plaintext_data, ensure_ascii=False).encode('utf-8')
            ciphertext_bytes = aesgcm.encrypt(nonce.encode('utf-8'), plaintext_bytes, associated_data_str.encode('utf-8'))
            ciphertext_b64 = base64.b64encode(ciphertext_bytes).decode('utf-8')

            callback_payload = {
                "id": f"evt_{random.randint(100000, 999999)}",
                "create_time": timezone_iso_now(),
                "event_type": "TRANSACTION.SUCCESS",
                "resource_type": "encrypt-resource",
                "resource": {
                    "algorithm": "AEAD_AES_256_GCM",
                    "ciphertext": ciphertext_b64,
                    "associated_data": associated_data_str,
                    "nonce": nonce
                },
                "summary": "微信支付成功通知"
            }
            headers = {
                "Wechatpay-Signature": "mock_signature_from_simulator",
                "Wechatpay-Timestamp": str(int(time.time())),
                "Wechatpay-Nonce": ''.join(random.choices(string.ascii_letters + string.digits, k=16))
            }
            url = f"{self.server_url}/api/pay/callback"
            response = self.session.post(url, json=callback_payload, headers=headers, timeout=5)
            if response.status_code == 200:
                return response.json().get('code') == 'SUCCESS'
        except Exception as e:
            logger.error(f"[微信端] 模拟微信支付回调失败: {e}")
        return False

    # ============================================================
    # 模拟上位机设备端逻辑
    # ============================================================

    def start_mqtt_client(self):
        """连接本地 MQTT Broker"""
        client_id = f"simulator_{self.device_sn}_{random.randint(1000, 9999)}"
        self.mqtt_client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            clean_session=True
        )
        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.on_message = self._on_mqtt_message
        
        logger.info(f"[设备端MQTT] 正在连接 MQTT Broker ({self.mqtt_host}:{self.mqtt_port})...")
        self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, keepalive=60)
        self.mqtt_client.loop_start()

    def stop_mqtt_client(self):
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
            logger.info("[设备端MQTT] MQTT 客户端已安全断开")

    def _on_mqtt_connect(self, client, userdata, flags, reason_code, properties):
        self.mqtt_connected = True
        cmd_topic = f"automake/device/{self.device_sn}/command"
        client.subscribe(cmd_topic, qos=1)
        logger.info(f"[设备端MQTT] 订阅指令主题成功: {cmd_topic}")
        # 定时上报心跳
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()

    def _heartbeat_loop(self):
        status_topic = f"automake/device/{self.device_sn}/status"
        while self.mqtt_connected:
            try:
                self.mqtt_client.publish(
                    status_topic, 
                    json.dumps({"type": "heartbeat", "status": "online"}), 
                    qos=1
                )
            except Exception as e:
                logger.error(f"心跳发布错误: {e}")
            time.sleep(5)

    def publish_status(self, order_no: str, status: str, message: str = ""):
        status_topic = f"automake/device/{self.device_sn}/status"
        payload = {
            "type": "order_status",
            "order_no": order_no,
            "status": status,
            "message": message
        }
        self.mqtt_client.publish(status_topic, json.dumps(payload), qos=1)
        logger.info(f"[设备端MQTT] 发布订单 {order_no} 状态: {status} -> {message}")

    def lock_inventory(self, order_no: str, recipe: dict) -> bool:
        url = f"{self.server_url}/api/device/inventory/lock"
        payload = {
            "device_sn": self.device_sn,
            "order_no": order_no,
            "materials": [{"material_code": k, "quantity": v} for k, v in recipe.items()]
        }
        res = self.session.post(url, json=payload, timeout=5)
        return res.status_code == 200 and res.json().get('code') == 0

    def deduct_inventory(self, order_no: str, recipe: dict) -> bool:
        url = f"{self.server_url}/api/device/inventory/deduct"
        payload = {
            "device_sn": self.device_sn,
            "order_no": order_no,
            "materials": [{"material_code": k, "quantity": v} for k, v in recipe.items()]
        }
        res = self.session.post(url, json=payload, timeout=5)
        return res.status_code == 200 and res.json().get('code') == 0

    def release_inventory(self, order_no: str, recipe: dict) -> bool:
        url = f"{self.server_url}/api/device/inventory/release"
        payload = {
            "device_sn": self.device_sn,
            "order_no": order_no,
            "materials": [{"material_code": k, "quantity": v} for k, v in recipe.items()]
        }
        res = self.session.post(url, json=payload, timeout=5)
        return res.status_code == 200 and res.json().get('code') == 0

    def _on_mqtt_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
        except Exception:
            return
        
        if payload.get('type') == 'make':
            order_no = payload.get('order_no')
            items = payload.get('items', [])
            logger.info(f"[物理硬件] 上位机感知到云边同步指令：开始制造饮品，单号: {order_no}")
            
            # 异步硬件模拟
            threading.Thread(
                target=self._simulate_physical_making, 
                args=(order_no, items), 
                daemon=True
            ).start()

    def _simulate_physical_making(self, order_no: str, items: list):
        self.is_making = True
        self.active_order_no = order_no
        
        # 计算配料消耗
        recipe = {}
        for item in items:
            item_name = item.get('item_name', '')
            quantity = item.get('quantity', 1)
            if "拿铁" in item_name:
                for k, v in self.recipes["经典拿铁"].items():
                    recipe[k] = recipe.get(k, 0) + (v * quantity)
            else:
                recipe["coffee_bean"] = recipe.get("coffee_bean", 0) + (10 * quantity)
                
        logger.info(f"[物理硬件] 硬件逻辑计算用量配方: {recipe}")
        
        # 1. 发送 API 锁仓
        logger.info("[物理硬件] 步骤 1/3: 锁仓预扣中...")
        lock_ok = self.lock_inventory(order_no, recipe)
        if not lock_ok:
            logger.error("[物理硬件] 锁定失败！中止工作")
            self.publish_status(order_no, "failed", "锁定库存失败，物料不足")
            self.is_making = False
            return
            
        # 2. 发送制作状态上报
        self.publish_status(order_no, "making", "磨豆机和萃取泵已就位，制作中...")
        time.sleep(1.5)
        
        if self.force_fail:
            logger.warning(f"[物理硬件] 触发硬件异常断点: {self.fail_reason}")
            self.release_inventory(order_no, recipe)
            self.publish_status(order_no, "failed", f"硬件异常中断: {self.fail_reason}")
            self.is_making = False
            return
            
        # 3. 制作完成，扣减实际库存并上报 done 终态
        logger.info("[物理硬件] 步骤 3/3: 完成物理研磨，调用扣除实际库存接口...")
        deduct_ok = self.deduct_inventory(order_no, recipe)
        if deduct_ok:
            self.publish_status(order_no, "done", "热咖啡已出杯，请取餐")
        else:
            self.release_inventory(order_no, recipe)
            self.publish_status(order_no, "failed", "扣除实际物料失败")
            
        self.is_making = False


# ============================================================
# 测试脚本入口
# ============================================================

def run_test_flow():
    print("=" * 80)
    print("           智能咖啡机一体化自动化集成流程测试 (含耗材扣减与报警)")
    print("=" * 80)

    # 1. 初始化 Redis 状态与数据库数据
    clear_redis_keys(device_sn="sn001")
    # prepare_db_data()
    
    # 2. 开启后台测试 Web 服务进程 (使用 8001 端口以避开冲突)
    start_wsgi_server(port=8001)

    # 3. 创建模拟器实例
    sim = UpperMachineSimulator(
        server_url="http://127.0.0.1:8000",
        mqtt_host="127.0.0.1",
        mqtt_port=1883,
        device_sn="sn001",
        key_code="TEST-KEY-001",
        store_id=100000
    )

    # 获取初始状态的耗材数据库数量
    cup_stock = DeviceConsumableStock.objects.get(device__device_sn='sn001', code__code='paperL')
    lid_stock = DeviceConsumableStock.objects.get(device__device_sn='sn001', code__code='lid')
    
    print(f"\n[耗材初始状态]")
    print(f"  → 纸杯: 初始剩余={cup_stock.quantity} 个, 预警阀值={cup_stock.warn_level} 个")
    print(f"  → 杯盖: 初始剩余={lid_stock.quantity} 个, 预警阀值={lid_stock.warn_level} 个 (触发线: <= 20)")

    # 4. 启动上位机的长连接 MQTT 客户端
    sim.start_mqtt_client()
    time.sleep(1.0) # 等待 MQTT 完成就绪与订阅

    try:
        # 5. 点单端逻辑：从数据库读取菜单 Sku 并点大杯热拿铁 2 杯
        store_obj = Store.objects.get(id=100000)
        # menu_item = MenuItem.objects.get(store=store_obj, global_item__name='经典拿铁')
        # menu_sku = MenuSku.objects.get(item=menu_item, global_sku__name='大杯/热')
        
        sim.add_to_cart(item_id=8, sku_ids=[26,28], quantity=1)

        # 6. 下单预校验 (Precheck)
        precheck_res = sim.precheck_order()
        if not precheck_res:
            raise RuntimeError("预校验接口返回失败")
        print(f"[微信端] 预校验通过，总金额: {precheck_res['total_amount']/100:.2f}元")

        # 7. 正式创建订单
        order_no = sim.create_order(remark="热拿铁 2 杯，多糖")

        if not order_no:
            raise RuntimeError("创建订单失败")
        print(f"[微信端] 正式下单成功，单号: {order_no}")

        # 8. 发起支付请求并支付回调完成确认
        sim.create_pay_request(order_no)
    
        pay_ok = sim.simulate_payment(order_no, precheck_res['pay_amount'])
        if not pay_ok:
            raise RuntimeError("支付确认回调失败")
        print(f"[微信端] 支付成功！已异步通知 Django 逻辑")
        exit()
        # 9. 主测试线程轮询订单状态，等待后台 MQTT 异步交互并完成扣除
        logger.info("[集成测试] 等待硬件接收 make 指令并进行物理动作模拟...")
        order_done = False
        for poll_idx in range(15):
            order = OrderMain.objects.get(order_no=order_no)
            logger.info(f"[主测试轮询] 订单 {order_no} 状态: {order.get_status_display()}")
            if order.status == OrderMain.STATUS_DONE:
                order_done = True
                break
            time.sleep(1.0)

        if not order_done:
            raise RuntimeError("物理出货制作超时")

        # 10. 验证最终耗材数量扣减状态
        cup_stock.refresh_from_db()
        lid_stock.refresh_from_db()
        print(f"\n[耗材最终状态]")
        print(f"  → 纸杯: 剩余={cup_stock.quantity} 个 (应扣除 2 个，预期为 88)")
        print(f"  → 杯盖: 剩余={lid_stock.quantity} 个 (应扣除 2 个，预期为 19)")

        # 断言数据库库存正确性
        if cup_stock.quantity != 88:
            raise AssertionError(f"纸杯扣除错误，实际: {cup_stock.quantity}")
        if lid_stock.quantity != 19:
            raise AssertionError(f"杯盖扣除错误，实际: {lid_stock.quantity}")
        print("✅ 耗材数据库物理库存数值扣除无误！")

        # 验证防抖短信锁及告警（杯盖原本 21 扣减后变为 19，低于或等于预警值 20，应该发送补货告警）
        from django_redis import get_redis_connection
        redis_conn = get_redis_connection("default")
        sms_key = f"automake:sms_sent:sn001:lid"
        if not redis_conn.exists(sms_key):
            raise AssertionError("缺少杯盖物料低水位补货短信预警防抖键！")
        print("✅ 杯盖低水位补货告警与短信提示（防抖锁）成功触发验证通过！")

        print("\n" + "=" * 80)
        print("🎉 恭喜！模拟点单、支付、MQTT 指令分发、真实耗材自动扣减和报警机制一体化流程测试圆满成功！")
        print("=" * 80)

    except Exception as e:
        logger.exception(f"❌ 流程测试中途发生异常: {e}")
        sys.exit(1)
    finally:
        sim.stop_mqtt_client()


if __name__ == '__main__':
    run_test_flow()
