#!/usr/bin/env python3
"""
模拟上位机 MQTT 连接脚本
- 设备/用户名: sn001
- 密码: 9058298
- 支持两种连接模式：
  1. WebSocket/WSS 模式 (默认)：tinylab.store:443/mqtt （适合公网免开放1883端口）
  2. TCP 模式：127.0.0.1:1883 或 tinylab.store:1883
"""

import sys
import ssl
import time
import json
import logging
import argparse
import paho.mqtt.client as mqtt

# ==================== 默认配置项 ====================
DEVICE_SN = "sn001"
DEFAULT_USERNAME = "sn001"
DEFAULT_PASSWORD = "9058298"
# ====================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("MqttSimulator")


def on_connect(client, userdata, flags, reason_code, properties=None):
    """连接建立回调"""
    rc = reason_code.value if hasattr(reason_code, "value") else reason_code
    if rc == 0:
        logger.info(f"✅ MQTT 认证并通过连接成功! [Client ID: {client._client_id.decode() if isinstance(client._client_id, bytes) else client._client_id}]")
        
        # 订阅上位机指令主题
        sub_topic = f"s2c/shop/{DEVICE_SN}/state/command"
        client.subscribe(sub_topic, qos=1)
        logger.info(f"📥 已成功订阅云端指令主题: {sub_topic}")
    else:
        logger.error(f"❌ MQTT 连接/认证失败，返回码: {reason_code}")


def on_message(client, userdata, msg):
    """收到消息回调"""
    try:
        payload_str = msg.payload.decode("utf-8")
        logger.info(f"📩 收到云端下发指令 [Topic: {msg.topic}]:\n{payload_str}")
        
        data = json.loads(payload_str)
        action = data.get("action") or data.get("type") or "unknown"
        logger.info(f"⚡ 解析指令动作: {action}")

        if str(action).lower() == "cancel":
            order_no = data.get("order_no") or data.get("orderNo")
            reason = data.get("reason", "用户取消")
            logger.info(f"🛑 收到上位机取消/停机制作指令: order_no={order_no}, reason={reason}")
            reply_topic = f"c2s/shop/{DEVICE_SN}/state/command"
            reply_payload = {
                "type": "cancel_ack",
                "order_no": order_no,
                "status": "ok",
                "reason": "上位机已停止制作并确认取消",
                "ts": int(time.time() * 1000)
            }
            client.publish(reply_topic, json.dumps(reply_payload, ensure_ascii=False), qos=1)
            logger.info(f"📤 已应答 cancel_ack (ok): topic={reply_topic}")
    except Exception as e:
        logger.warning(f"📩 收到非JSON原始数据: {msg.payload} (解析异常: {e})")


def on_publish(client, userdata, mid, reason_code=None, properties=None):
    """消息发布回调"""
    logger.debug(f"📤 消息发布成功 (mid={mid})")


def on_disconnect(client, userdata, disconnect_flags, reason_code=None, properties=None):
    """断开连接回调"""
    logger.warning(f"⚠️ 连接断开，原因: {reason_code}")


def main():
    parser = argparse.ArgumentParser(description="上位机 MQTT 模拟连接测试工具")
    parser.add_argument("--mode", choices=["wss", "tcp"], default="wss", help="连接模式: wss (端口443) 或 tcp (端口1883)，默认 wss")
    parser.add_argument("--host", default=None, help="Broker 主机地址 (wss默认 tinylab.store, tcp默认 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="Broker 端口 (wss默认 443, tcp默认 1883)")
    parser.add_argument("--username", default=DEFAULT_USERNAME, help=f"MQTT 用户名 (默认: {DEFAULT_USERNAME})")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help=f"MQTT 密码 (默认: {DEFAULT_PASSWORD})")
    args = parser.parse_args()

    use_ws = (args.mode == "wss")
    host = args.host or ("tinylab.store" if use_ws else "127.0.0.1")
    port = args.port or (443 if use_ws else 1883)
    username = args.username
    password = args.password

    logger.info(f"🚀 初始化上位机 MQTT 模拟客户端...")
    logger.info(f"   - 设备 SN : {DEVICE_SN}")
    logger.info(f"   - 用户名  : {username}")
    logger.info(f"   - 密码    : {password}")
    logger.info(f"   - 连接目标: {'WSS' if use_ws else 'TCP'}://{host}:{port}{'/mqtt' if use_ws else ''}")

    # 1. 创建 MQTT 客户端实例
    client_id = f"device_{DEVICE_SN}_{int(time.time()) % 10000}"
    try:
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            clean_session=True,
            transport="websockets" if use_ws else "tcp"
        )
    except AttributeError:
        client = mqtt.Client(
            client_id=client_id,
            clean_session=True,
            transport="websockets" if use_ws else "tcp"
        )

    # 2. 【核心】传入用户名和密码
    client.username_pw_set(username=username, password=password)

    # 3. WSS / TLS 特性配置
    if use_ws:
        client.ws_set_options(path="/mqtt")
        if port == 443:
            client.tls_set(cert_reqs=ssl.CERT_NONE)

    # 4. 绑定事件回调
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_publish = on_publish
    client.on_disconnect = on_disconnect

    # 5. 连接并开启网络循环
    try:
        client.connect(host, port, keepalive=60)
    except Exception as e:
        logger.error(f"❌ 建立连接失败: {e}")
        sys.exit(1)

    client.loop_start()

    pub_status_topic = f"c2s/shop/{DEVICE_SN}/state/selfPack"
    logger.info("📡 模拟上位机开始发送心跳包 (每 10 秒一次，按 Ctrl+C 退出)...")
    try:
        seq = 1
        while True:
            heartbeat_data = {
                "type": "heartbeat",
                "device_sn": DEVICE_SN,
                "status": "online",
                "seq": seq,
                "timestamp": int(time.time())
            }
            client.publish(pub_status_topic, json.dumps(heartbeat_data), qos=1)
            logger.info(f"💓 [心跳 #{seq}] 已上报状态至 {pub_status_topic}")
            seq += 1
            time.sleep(10)

    except KeyboardInterrupt:
        logger.info("\n收到退出信号，正在安全断开连接...")
    finally:
        client.loop_stop()
        client.disconnect()
        logger.info("👋 MQTT 客户端已断开并退出。")


if __name__ == "__main__":
    main()
