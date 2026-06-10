"""
上位机与业务流程模拟器 (Upper Machine & Business Flow Simulator)

本模块实现了一个独立的模拟类 `UpperMachineSimulator`，用于模拟：
1. 微信点单端：购物车管理、订单预校验 (precheck)、正式下单 (create)、完全真实的加密微信支付回调 (pay callback)。
2. 上位机设备端：设备注册 (register)、MQTT 心跳上报 (heartbeat)、MQTT 接收云端制作指令、HTTPS 锁定库存、HTTPS 扣减实际库存、HTTPS 释放锁定库存、MQTT 上报制作进度与状态变化。

通信协议：
- 用户端/设备注册/库存操作：HTTPS (HTTP)
- 状态上报/制作指令：MQTT
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


class UpperMachineSimulator:
    """
    上位机与业务流程模拟器类
    """

    def __init__(self, server_url="http://127.0.0.1:8000", mqtt_host="127.0.0.1", mqtt_port=1883, device_sn="SN001"):
        """
        初始化模拟器
        """
        self.server_url = server_url.rstrip('/')
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.device_sn = device_sn

        # 购物车，格式：{sku_id: quantity}
        self.cart = {}

        # HTTP 会话，依靠 Django 的 DevMockAuthentication，不带 Token 请求会自动登录为 dev_tester
        self.session = requests.Session()

        # 从 .env 文件读取微信支付加密密钥，用于构造真实的微信支付回调
        self.api_v3_key = self._load_api_v3_key()

        # MQTT 客户端相关
        self.mqtt_client = None
        self.mqtt_connected = False
        self.is_making = False
        self.active_order_no = None

        # 默认物料配方（每杯饮品消耗的原料量）
        self.recipes = {
            "美式咖啡": {"coffee_bean": 15.0},
            "拿铁咖啡": {"coffee_bean": 15.0, "fresh_milk": 150.0},
        }

        # 强制制作失败标志
        self.force_fail = False
        self.fail_reason = ""

    def _load_api_v3_key(self) -> str:
        """
        从项目根目录的 .env 文件加载 WECHAT_PAY_API_V3_KEY
        """
        try:
            # 向上寻找 .env 文件
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            env_path = os.path.join(os.path.dirname(base_dir), '.env')
            if os.path.exists(env_path):
                with open(env_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.startswith('WECHAT_PAY_API_V3_KEY='):
                            key = line.strip().split('=', 1)[1]
                            logger.info(f"成功从 .env 中加载支付密钥: {key[:4]}...{key[-4:]}")
                            return key
        except Exception as e:
            logger.warning(f"从 .env 加载微信支付密钥失败，将使用默认密钥: {e}")
        
        # 默认回退密钥，须与 settings.py 保持一致
        return "abcdefghijklmnopqrstuvwxyz123456"

    # ============================================================
    # 微信用户点单端模拟 (HTTP/HTTPS)
    # ============================================================

    def add_to_cart(self, sku_id: int, quantity: int = 1):
        """
        向购物车中添加商品 SKU
        """
        if sku_id in self.cart:
            self.cart[sku_id] += quantity
        else:
            self.cart[sku_id] = quantity
        logger.info(f"[购物车] 已添加 SKU ID: {sku_id}，数量: {quantity}，当前购物车: {self.cart}")

    def remove_from_cart(self, sku_id: int, quantity: int = 1):
        """
        从购物车减少/移除商品
        """
        if sku_id in self.cart:
            self.cart[sku_id] -= quantity
            if self.cart[sku_id] <= 0:
                del self.cart[sku_id]
        logger.info(f"[购物车] 已移除/减少 SKU ID: {sku_id}，减少数量: {quantity}，当前购物车: {self.cart}")

    def clear_cart(self):
        """
        清空购物车
        """
        self.cart.clear()
        logger.info("[购物车] 购物车已清空")

    def get_menu(self, store_id: int = 1) -> list:
        """
        拉取门店菜单信息
        """
        url = f"{self.server_url}/api/menu/store/{store_id}"
        try:
            response = self.session.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('code') == 0:
                    res_data = data.get('data', {})
                    categories = res_data.get('categories', [])
                    logger.info(f"[点单端] 成功拉取门店 {store_id} 的菜单分类列表:")
                    for cat in categories:
                        print(f"--- 分类: {cat['name']} ---")
                        for item in cat.get('items', []):
                            sku_str = ", ".join([f"{sku['name']}(ID:{sku['id']}) 价格:{sku['final_price']/100:.2f}元" for sku in item.get('skus', [])])
                            print(f" 商品: {item['name']} (ID:{item['id']}) 基准价:{item['base_price']/100:.2f}元 | 规格: [{sku_str}]")
                    return categories
            logger.error(f"[点单端] 拉取菜单接口响应错误: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"[点单端] 拉取菜单失败，网络异常: {e}")
        return []

    def precheck_order(self, store_id: int = 1) -> dict:
        """
        订单预校验 (precheck)
        """
        if not self.cart:
            logger.warning("[预校验] 购物车为空，无法校验")
            return {}

        items_payload = [{"sku_id": sku_id, "quantity": qty} for sku_id, qty in self.cart.items()]
        payload = {
            "store_id": store_id,
            "items": items_payload
        }

        url = f"{self.server_url}/api/order/precheck"
        logger.info(f"[预校验] 正在提交预校验接口, 数据: {payload}")
        try:
            response = self.session.post(url, json=payload, timeout=5)
            if response.status_code == 200:
                res_data = response.json()
                if res_data.get('code') == 0:
                    logger.info(f"[预校验] 校验成功！总金额: {res_data['data']['total_amount']/100:.2f}元，实付金额: {res_data['data']['pay_amount']/100:.2f}元")
                    return res_data['data']
                else:
                    logger.error(f"[预校验] 校验被拒: {res_data.get('message')}")
            else:
                logger.error(f"[预校验] 接口返回状态异常: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"[预校验] 网络请求发生错误: {e}")
        return {}

    def create_order(self, store_id: int = 1, remark: str = "模拟器下单") -> str:
        """
        正式创建订单
        """
        if not self.cart:
            logger.warning("[下单] 购物车为空，无法创建订单")
            return ""

        items_payload = [{"sku_id": sku_id, "quantity": qty} for sku_id, qty in self.cart.items()]
        payload = {
            "store_id": store_id,
            "items": items_payload,
            "remark": remark
        }

        url = f"{self.server_url}/api/order/create"
        logger.info(f"[下单] 发送创建订单请求, 数据: {payload}")
        try:
            response = self.session.post(url, json=payload, timeout=5)
            if response.status_code == 200:
                res_data = response.json()
                if res_data.get('code') == 0:
                    order_no = res_data['data']['order_no']
                    pay_amount = res_data['data']['pay_amount']
                    logger.info(f"[下单] 下单成功！订单号: {order_no}，应付金额: {pay_amount/100:.2f}元")
                    return order_no
                else:
                    logger.error(f"[下单] 下单失败: {res_data.get('message')}")
            else:
                logger.error(f"[下单] 接口状态异常: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"[下单] 网络异常: {e}")
        return ""

    def create_pay_request(self, order_no: str) -> dict:
        """
        发起支付请求，向服务器申请预支付记录 (PaymentRecord)
        """
        url = f"{self.server_url}/api/pay/create"
        payload = {"order_no": order_no}
        logger.info(f"[点单端] 正在发起预支付申请, 订单号: {order_no}")
        try:
            response = self.session.post(url, json=payload, timeout=5)
            if response.status_code == 200:
                res_data = response.json()
                if res_data.get('code') == 0:
                    logger.info(f"[点单端] 预支付申请成功！支付参数: {res_data['data']}")
                    return res_data['data']
                else:
                    logger.error(f"[点单端] 预支付申请失败: {res_data.get('message')}")
            else:
                logger.error(f"[点单端] 预支付接口异常: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"[点单端] 预支付申请网络异常: {e}")
        return {}

    def simulate_payment(self, order_no: str, amount_cents: int) -> bool:
        """
        完全模拟微信支付成功异步回调过程。
        该方法会在模拟端根据 APIv3 协议与 .env 加密密钥，构造真实的 AEAD_AES_256_GCM 加密报文发送至服务端 /api/pay/callback 接口。
        """
        logger.info(f"[支付模拟] 开始构造微信支付成功回调数据, 订单号: {order_no}, 实付金额: {amount_cents/100:.2f}元")

        # 1. 构造微信支付解密后的数据包
        plaintext_data = {
            "out_trade_no": order_no,
            "transaction_id": f"WX{int(time.time()*1000)}{random.randint(100, 999)}",
            "success_time": timezone_iso_now() if hasattr(self, 'timezone_iso_now') else time.strftime('%Y-%m-%dT%H:%M:%S+08:00'),
            "amount": {
                "payer_total": amount_cents,
                "total": amount_cents,
                "currency": "CNY"
            }
        }

        # 2. 对明文进行 AES-256-GCM 加密
        try:
            # 微信要求 12 字节 nonce
            nonce = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
            nonce_bytes = nonce.encode('utf-8')
            associated_data_str = "transaction"
            associated_data_bytes = associated_data_str.encode('utf-8')

            aesgcm = AESGCM(self.api_v3_key.encode('utf-8'))
            plaintext_bytes = json.dumps(plaintext_data, ensure_ascii=False).encode('utf-8')
            
            ciphertext_bytes = aesgcm.encrypt(nonce_bytes, plaintext_bytes, associated_data_bytes)
            ciphertext_b64 = base64.b64encode(ciphertext_bytes).decode('utf-8')

            # 3. 组装回调外层结构
            callback_payload = {
                "id": f"evt_{random.randint(100000, 999999)}",
                "create_time": time.strftime('%Y-%m-%dT%H:%M:%S+08:00'),
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

            # 4. 构造 HTTP 头（绕过平台验证必须带上格式正确的 Header 供时间校验）
            headers = {
                "Wechatpay-Signature": "mock_signature_from_simulator",
                "Wechatpay-Timestamp": str(int(time.time())),
                "Wechatpay-Nonce": ''.join(random.choices(string.ascii_letters + string.digits, k=16)),
                "Content-Type": "application/json"
            }

            url = f"{self.server_url}/api/pay/callback"
            logger.info(f"[支付模拟] 正在发送加密回调数据至: {url}")
            response = self.session.post(url, json=callback_payload, headers=headers, timeout=5)
            if response.status_code == 200:
                res_data = response.json()
                if res_data.get('code') == 'SUCCESS':
                    logger.info(f"[支付模拟] 服务端已成功接收并解密回调！订单已进入已支付待制作状态。")
                    return True
                else:
                    logger.error(f"[支付模拟] 服务端返回回调处理失败: {res_data.get('message')}")
            else:
                logger.error(f"[支付模拟] 回调接口状态异常: {response.status_code} - {response.text}")
        except Exception as e:
            logger.exception(f"[支付模拟] 构造/发送微信支付回调异常: {e}")
        return False

    # ============================================================
    # 上位机设备端模拟 (HTTPS & MQTT)
    # ============================================================

    def register_device(self) -> bool:
        """
        通过 HTTPS 接口向服务器注册设备，通知服务器设备上线并拉取 MQTT 主题等配置
        """
        url = f"{self.server_url}/api/device/register"
        payload = {
            "device_sn": self.device_sn,
            "device_name": f"模拟上位机咖啡机 {self.device_sn}",
            "device_version": "v2.1.0",
            "device_address": "北京市海淀区西二旗软件园"
        }
        logger.info(f"[设备端] 发送设备注册上线请求至: {url}")
        try:
            response = self.session.post(url, json=payload, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('code') == 0:
                    logger.info(f"[设备端] 注册成功！配置参数: {data['data']}")
                    return True
                else:
                    logger.error(f"[设备端] 注册失败: {data.get('message')}")
            else:
                logger.error(f"[设备端] 注册接口异常: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"[设备端] 注册网络故障: {e}")
        return False

    def report_inventory(self, materials: list = None) -> bool:
        """
        通过 HTTPS POST 接口向服务器上报当前物料库存
        """
        if materials is None:
            materials = [
                {"material_code": "coffee_bean", "material_name": "咖啡豆", "quantity": 1000.0, "unit": "g"},
                {"material_code": "fresh_milk", "material_name": "鲜牛奶", "quantity": 5000.0, "unit": "ml"}
            ]

        url = f"{self.server_url}/api/device/inventory/report"
        payload = {
            "device_sn": self.device_sn,
            "materials": materials
        }
        logger.info(f"[设备端] 通过 HTTPS POST 上报设备物料库存至: {url}, 数据: {payload}")
        try:
            response = self.session.post(url, json=payload, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('code') == 0:
                    logger.info("[设备端] 物料库存上报成功！")
                    return True
                else:
                    logger.error(f"[设备端] 物料库存上报失败: {data.get('message')}")
            else:
                logger.error(f"[设备端] 物料上报接口异常: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"[设备端] 物料库存上报网络故障: {e}")
        return False

    def report_inventory_mqtt(self, coffee_val: int = 1000, milk_val: int = 5000) -> bool:
        """
        通过 MQTT 发送物料状态上报
        """
        if not self.mqtt_client or not self.mqtt_connected:
            logger.error("[MQTT] 客户端未连接，无法通过 MQTT 上报物料库存")
            return False

        topic = f"automake/device/{self.device_sn}/material"
        payload = {
            "materials": [
                { "code": "coffee_bean", "name": "咖啡豆", "quantity": coffee_val, "unit": "g" },
                { "code": "fresh_milk", "name": "鲜牛奶", "quantity": milk_val, "unit": "ml" }
            ]
        }

        try:
            self.mqtt_client.publish(
                topic,
                json.dumps(payload, ensure_ascii=False),
                qos=1
            )
            logger.info(f"[MQTT] 已上报物料库存到主题: {topic}，数据: {payload}")
            return True
        except Exception as e:
            logger.error(f"[MQTT] 物料库存上报失败: {e}")
        return False

    def lock_inventory(self, order_no: str, recipe: dict) -> bool:
        """
        调用 HTTPS 接口向服务器锁定物料库存
        """
        url = f"{self.server_url}/api/device/inventory/lock"
        payload = {
            "device_sn": self.device_sn,
            "order_no": order_no,
            "materials": [{"material_code": k, "quantity": v} for k, v in recipe.items()]
        }
        logger.info(f"[设备端] 调用接口锁定物料库存, 数据: {payload}")
        try:
            response = self.session.post(url, json=payload, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('code') == 0:
                    logger.info("[设备端] 锁定库存成功！")
                    return True
                else:
                    logger.warning(f"[设备端] 锁定库存失败: {data.get('message')}")
            else:
                logger.error(f"[设备端] 锁定接口故障: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"[设备端] 锁定库存网络请求异常: {e}")
        return False

    def deduct_inventory(self, order_no: str, recipe: dict) -> bool:
        """
        调用 HTTPS 接口向服务器扣减实际物料库存（并释放在锁定库存中预占的部分）
        """
        url = f"{self.server_url}/api/device/inventory/deduct"
        payload = {
            "device_sn": self.device_sn,
            "order_no": order_no,
            "materials": [{"material_code": k, "quantity": v} for k, v in recipe.items()]
        }
        logger.info(f"[设备端] 调用接口扣减物料库存, 数据: {payload}")
        try:
            response = self.session.post(url, json=payload, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('code') == 0:
                    logger.info("[设备端] 实际扣减库存成功！")
                    return True
                else:
                    logger.error(f"[设备端] 扣减库存失败: {data.get('message')}")
            else:
                logger.error(f"[设备端] 扣减接口故障: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"[设备端] 扣减库存网络异常: {e}")
        return False

    def release_inventory(self, order_no: str, recipe: dict) -> bool:
        """
        调用 HTTPS 接口向服务器释放锁定的库存（在异常或取消订单时使用）
        """
        url = f"{self.server_url}/api/device/inventory/release"
        payload = {
            "device_sn": self.device_sn,
            "order_no": order_no,
            "materials": [{"material_code": k, "quantity": v} for k, v in recipe.items()]
        }
        logger.info(f"[设备端] 调用接口释放锁定库存, 数据: {payload}")
        try:
            response = self.session.post(url, json=payload, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('code') == 0:
                    logger.info("[设备端] 释放锁定库存成功！")
                    return True
                else:
                    logger.error(f"[设备端] 释放锁定库存失败: {data.get('message')}")
            else:
                logger.error(f"[设备端] 释放接口故障: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"[设备端] 释放锁定库存网络异常: {e}")
        return False

    def start_mqtt_client(self):
        """
        连接 MQTT 代理服务器并启动后台监听线程
        """
        client_id = f"simulator_{self.device_sn}_{''.join(random.choices(string.digits, k=4))}"
        self.mqtt_client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            clean_session=True
        )

        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
        self.mqtt_client.on_message = self._on_mqtt_message

        try:
            logger.info(f"[MQTT] 正在连接至 MQTT 服务器 {self.mqtt_host}:{self.mqtt_port}...")
            self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, keepalive=60)
            self.mqtt_client.loop_start()
        except Exception as e:
            logger.error(f"[MQTT] 启动连接异常: {e}")

    def stop_mqtt_client(self):
        """
        断开 MQTT 客户端连接
        """
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
            logger.info("[MQTT] 已断开客户端连接并终止 Loop 循环")

    def _on_mqtt_connect(self, client, userdata, flags, reason_code, properties):
        """
        MQTT 连接成功回调
        """
        if reason_code.is_failure:
            logger.error(f"[MQTT] 连上失败，原因码: {reason_code}")
            return
        
        self.mqtt_connected = True
        logger.info(f"[MQTT] 连上成功！会话已建立。")

        # 订阅云端给当前设备下发指令的主题
        cmd_topic = f"automake/device/{self.device_sn}/command"
        client.subscribe(cmd_topic, qos=1)
        logger.info(f"[MQTT] 已订阅命令主题: {cmd_topic}")

        # 开启定时心跳发送（非阻塞线程）
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()

    def _on_mqtt_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        """
        MQTT 断开回调
        """
        self.mqtt_connected = False
        logger.warning(f"[MQTT] 连接断开，原因码: {reason_code}")

    def _on_mqtt_message(self, client, userdata, msg):
        """
        处理云端发来的 MQTT 命令
        """
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
        except Exception as e:
            logger.error(f"[MQTT] 解析消息载荷失败: {e}，原始消息: {msg.payload}")
            return

        logger.info(f"[MQTT] 收到指令! 主题: {topic}，内容: {payload}")

        if payload.get('type') == 'make':
            order_no = payload.get('order_no')
            items = payload.get('items', [])
            
            # 在单独的线程中异步模拟制作，避免阻塞 MQTT 主循环
            threading.Thread(
                target=self._simulate_order_processing, 
                args=(order_no, items), 
                daemon=True
            ).start()
        
        elif payload.get('type') == 'cancel':
            logger.info(f"[MQTT] 收到取消制作指令。")
            self.is_making = False

    def _heartbeat_loop(self):
        """
        设备心跳循环，每 10 秒向云端发送一次在线心跳
        """
        status_topic = f"automake/device/{self.device_sn}/status"
        while self.mqtt_connected:
            heartbeat_payload = {
                "type": "heartbeat",
                "status": "online"
            }
            try:
                self.mqtt_client.publish(
                    status_topic, 
                    json.dumps(heartbeat_payload), 
                    qos=1
                )
                logger.debug(f"[MQTT] 已上报在线心跳到主题: {status_topic}")
            except Exception as e:
                logger.error(f"[MQTT] 发送心跳异常: {e}")
            time.sleep(10)

    def publish_status(self, order_no: str, status: str, message: str = ""):
        """
        通过 MQTT 发送订单进度和状态报告
        """
        status_topic = f"automake/device/{self.device_sn}/status"
        payload = {
            "type": "order_status",
            "order_no": order_no,
            "status": status,
            "message": message
        }
        try:
            self.mqtt_client.publish(
                status_topic, 
                json.dumps(payload, ensure_ascii=False), 
                qos=1
            )
            logger.info(f"[MQTT] 已上报订单 {order_no} 状态 [{status}] 到 {status_topic}，附言: {message}")
        except Exception as e:
            logger.error(f"[MQTT] 状态上报失败: {e}")

    def _simulate_order_processing(self, order_no: str, items: list):
        """
        模拟真实的饮品制作流程、物料库存锁定/扣减以及异常上报
        """
        if self.is_making:
            logger.warning(f"[设备制作] 设备繁忙！当前已有任务在执行，拒绝新任务: {order_no}")
            self.publish_status(order_no, "failed", "设备繁忙，拒绝制作指令。")
            return

        self.is_making = True
        self.active_order_no = order_no
        logger.info(f"[设备制作] 开始制作订单: {order_no}，包含商品: {items}")

        # 1. 计算总配料消耗量
        recipe = {}
        for item in items:
            item_name = item.get('item_name', '')
            quantity = item.get('quantity', 1)
            
            # 匹配配方，模糊匹配
            matched_recipe = None
            for name, rep in self.recipes.items():
                if name in item_name:
                    matched_recipe = rep
                    break
            
            if not matched_recipe:
                # 模糊 fallback
                if "拿铁" in item_name or "奶" in item_name:
                    matched_recipe = self.recipes["拿铁咖啡"]
                else:
                    matched_recipe = self.recipes["美式咖啡"]
            
            for code, qty in matched_recipe.items():
                recipe[code] = recipe.get(code, 0.0) + (qty * quantity)

        logger.info(f"[设备制作] 本订单预计消耗物料配料: {recipe}")

        # 2. 上位机调用锁定接口
        logger.info("[设备制作] 【步骤1】上位机向服务器发送锁库存请求 (Lock Inventory)...")
        lock_success = self.lock_inventory(order_no, recipe)
        if not lock_success:
            logger.error(f"[设备制作] 锁定库存失败！原因为物料不足或设备异常。制作被迫中断。")
            self.publish_status(order_no, "failed", "锁定配料库存失败，原料不足")
            self.is_making = False
            self.active_order_no = None
            return

        # 3. 锁定成功，发送制作中状态
        self.publish_status(order_no, "making", "磨豆机已启动，咖啡豆研磨中...")
        time.sleep(1.5)

        # 4. 模拟制作时间，制作过程可能抛出异常
        if self.force_fail:
            logger.warning(f"[设备制作] 【步骤2-异常触发】模拟设备制作中突发异常: {self.fail_reason}")
            # 释放锁定的库存
            self.release_inventory(order_no, recipe)
            self.publish_status(order_no, "failed", f"制作中断，设备硬件发生错误: {self.fail_reason}")
            self.is_making = False
            self.active_order_no = None
            return

        self.publish_status(order_no, "making", "浓缩萃取中，牛奶加热拉花中...")
        time.sleep(1.5)

        # 5. 扣减实际库存并释放锁定
        logger.info("[设备制作] 【步骤3】制作完成，上位机调用扣库存接口 (Deduct Inventory)...")
        deduct_success = self.deduct_inventory(order_no, recipe)
        if deduct_success:
            self.publish_status(order_no, "done", "制作完成！饮品已出杯，请及时取走。")
            logger.info(f"[设备制作] 订单 {order_no} 成功出杯！上位机重置为空闲。")
        else:
            logger.error(f"[设备制作] 扣减实际库存失败！正在释防预占部分。")
            self.release_inventory(order_no, recipe)
            self.publish_status(order_no, "failed", "扣减实际物料库存遭遇异常")

        self.is_making = False
        self.active_order_no = None


# ============================================================
# 命令行运行演示入口 (Demo execution)
# ============================================================

if __name__ == '__main__':
    print("=" * 60)
    print("                上位机与业务流程模拟器 Demo")
    print("=" * 60)

    # 1. 初始化模拟器，连至本地测试服务器 30002
    sim = UpperMachineSimulator(
        server_url="http://127.0.0.1:30002",
        mqtt_host="127.0.0.1",
        mqtt_port=1883,
        device_sn="SN001"
    )

    # 2. 启动上位机的 MQTT 客户端以连接代理，订阅命令并自动定时发心跳
    sim.start_mqtt_client()
    time.sleep(1.0) # 等待 MQTT 建立连接

    # 确保上位机已经在云端注册并上线
    reg_ok = sim.register_device()
    if not reg_ok:
        logger.error("设备注册上线失败，请确保 Django 服务器运行在 30002 端口且已启动！")
        sim.stop_mqtt_client()
        sys.exit(1)

    # 上位机通过 HTTPS POST 上报当前物料库存（服务器库存由上位机上报，无需手动维护）
    report_ok = sim.report_inventory()
    if not report_ok:
        logger.warning("设备物料库存上报失败，继续后续测试...")

    print("\n--- 模拟开始 ---")
    try:
        # 3. 模拟微信点单端：获取门店菜单
        sim.get_menu(store_id=1)
        time.sleep(0.5)

        # 4. 模拟点单端：往购物车添加 1 杯美式和 1 杯拿铁
        print("\n--- 购物车选品 ---")
        sim.add_to_cart(sku_id=1, quantity=1) # 美式咖啡
        sim.add_to_cart(sku_id=2, quantity=1) # 拿铁咖啡
        time.sleep(0.5)

        # 5. 模拟点单端：订单预校验 (precheck)
        print("\n--- 订单预结算校验 ---")
        precheck_res = sim.precheck_order(store_id=1)
        if not precheck_res:
            raise ValueError("预校验失败")
        time.sleep(0.5)

        # 6. 模拟点单端：正式下单创建订单
        print("\n--- 创建正式订单 ---")
        order_no = sim.create_order(store_id=1, remark="来一杯美式，一杯拿铁")
        if not order_no:
            raise ValueError("创建订单失败")
        time.sleep(0.5)

        # 6.5 发起支付请求以在数据库中创建支付挂起记录 (PaymentRecord)
        print("\n--- 申请获取预支付参数 ---")
        pay_params = sim.create_pay_request(order_no)
        if not pay_params:
            raise ValueError("预支付参数获取失败")
        time.sleep(0.5)

        # 7. 模拟微信支付回调：对支付明文进行 GCM 加密，并向 /api/pay/callback 发送 POST
        print("\n--- 支付确认（完全加密解密流程） ---")
        pay_amount_cents = precheck_res['pay_amount']
        pay_ok = sim.simulate_payment(order_no, pay_amount_cents)
        if not pay_ok:
            raise ValueError("支付失败")

        # 8. 等待上位机接收命令并异步制作
        print("\n--- 等待设备端制作与通信反馈 ---")
        # 制作一般消耗大约 3 秒以上
        time.sleep(5.0)

        # 9. 异常情况流程测试：再次下一单，但这一次模拟设备制作硬件故障
        print("\n" + "="*50)
        print("          开始模拟第二笔订单：制作突发硬件异常测试")
        print("="*50)

        sim.clear_cart()
        sim.add_to_cart(sku_id=2, quantity=1) # 拿铁咖啡
        order_no_fail = sim.create_order(store_id=1, remark="这杯要异常失败")
        if order_no_fail:
            # 发起支付请求以在数据库中创建支付挂起记录
            sim.create_pay_request(order_no_fail)
            time.sleep(0.5)

            # 强制模拟设备异常故障
            sim.force_fail = True
            sim.fail_reason = "咖啡杯感应器硬件松动故障"

            # 模拟支付
            sim.simulate_payment(order_no_fail, 1800) # 18元
            time.sleep(5.0)

    except KeyboardInterrupt:
        logger.info("模拟被用户手动中止")
    except Exception as e:
        logger.error(f"模拟过程出错: {e}")
    finally:
        # 关闭 MQTT 连接
        sim.stop_mqtt_client()
        print("--- 模拟结束 ---")
