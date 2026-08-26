import time
import json
import ssl
import random
import paho.mqtt.client as mqtt

# 1. 云端 MQTT 配置
BROKER = "tinylab.store"
PORT = 443
WS_PATH = "/mqtt"
DEVICE_SN = "sn005"  # 模拟连接的设备序列号

# 3. 定义 MQTT 消息主题
STATUS_TOPIC = f"c2s/shop/{DEVICE_SN}/state/selfPack"
MATERIALhais_TOPIC = STATUS_TOPIC
health = '''

{
    "healthy": 1,
    "disconnected": 0,
    "free": {"master": 1024, "slave": 64},
    "temperature": {"t1": 4, "t2": 175},
    "ice": {"a1": 0, "a2": 0, "a3": 0},
    "transfer": {"a1": 0},
    "cup": {
        "plasticL": {"a1": 0, "a2": 0},
        "plasticM": {"a1": 0, "a2": 0},
        "paperL": {"a1": 0, "a2": 0},
        "paperM": {"a1": 0, "a2": 0},
        "membrane": {"a1": 0, "a2": 0},
        "lid": {"a1": 0, "a2": 0}
    },
    "thinP": {
        "b01": {"v": 40000, "a1": 0},
        "b02": {"v": 19900, "a1": 0},
        "b03": {"v": 19900, "a1": 0},
        "b04": {"v": 1091, "a1": 0},
        "b05": {"v": 1910, "a1": 0},
        "b06": {"v": 19900, "a1": 0},
        "b07": {"v": 19900, "a1": 0},
        "b08": {"v": 3000, "a1": 0}
    },
                                                                                                                                                         
    
    
    "thickP": {
        "b09": {"v": 5800, "a1": 0},
        "b10": {"v": 5800, "a1": 0},
        "b11": {"v": 5800, "a1": 0},
        "b12": {"v": 5800, "a1": 0},
        "b13": {"v": 5800, "a1": 0},
        "b14": {"v": 5800, "a1": 0},
        "b15": {"v": 5800, "a1": 0},
        "b16": {"v": 5800, "a1": 0},
        "b17": {"v": 5800, "a1": 0},
        "b18": {"v": 5800, "a1": 0},
        "b19": {"v": 5800, "a1": 0},
        "b20": {"v": 5800, "a1": 0},
        "b21": {"v": 5800, "a1": 0},
        "b22": {"v": 5800, "a1": 0},
        "b23": {"v": 5800, "a1": 0},
        "b24": {"v": 5800, "a1": 0},
        "b25": {"v": 5800, "a1": 0},
        "b26": {"v": 5800, "a1": 0},
        "b27": {"v": 5800, "a1": 0},
        "b28": {"v": 5800, "a1": 0},
        "b29": {"v": 5800, "a1": 0},
        "b30": {"v": 5800, "a1": 0},
        "b31": {"v": 5800, "a1": 0}
    },
    "solidP": {
        "b32": {"v": 3500, "a1": 0},
        "b33": {"v": 3500, "a1": 0},
        "b34": {"v": 3500, "a1": 0},
        "b35": {"v": 3500, "a1": 0},
        "b36": {"v": 3500, "a1": 0},
        "b37": {"v": 3500, "a1": 0}
    },
    "press": {"a1": 0},
    "heat": {"a1": 0, "a2": 0, "a3": 0},
    "arm": {"a1": 0},
    "take": {"a1": 0, "a2": 0, "a3": 0},
    "spray": {"a1": 0},
    "ticket": {"a1": 0, "a2": 0, "a3": 0, "a4": 0, "a5": 0}
}
'''



# 4. 回调函数：连接成功/失败事件
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[OK] 成功连接至云端 MQTT 代理服务器 (Client ID: {DEVICE_SN})")
    else:
        print(f"[ERROR] 连接失败，错误码为: {rc}")

# 5. 回调函数：发布成功事件
def on_publish(client, userdata, mid, reason_code=None, properties=None):
    print(f"[INFO] 消息发布成功 (Message ID: {mid})")

# 6. 初始化 MQTT 客户端 (采用 WebSocket 传输方式)
client = mqtt.Client(
    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    client_id=DEVICE_SN,
    transport="websockets"
)

# 7. 配置 WebSocket 与 SSL/TLS 证书规则
client.ws_set_options(path=WS_PATH)
client.tls_set(cert_reqs=ssl.CERT_NONE)  # 忽略自签名证书检测限制以确保直连成功

# 绑定事件回调
client.on_connect = on_connect
client.on_publish = on_publish

# 8. 开始连接
print(f"正在尝试连接云端 MQTT 代理: wss://{BROKER}:{PORT}{WS_PATH} ...")
client.connect(BROKER, PORT, keepalive=60)

# 在后台启动网络循环线程
client.loop_start()

try:
    print(f"\n[开始心跳] 开始循环发送心跳数据，每 10 秒发送一次...")
    i = 0
    while True:
        heartbeat_data = {
            "type": "heartbeat",
            "status": "online"
        }
        i += 1
        print(f'the {i} time sent!')
        client.publish(STATUS_TOPIC, health, qos=1)
        time.sleep(10)

except KeyboardInterrupt:
    print("\n[INFO] 正在退出客户端...")
finally:
    client.loop_stop()
    client.disconnect()
    print("[INFO] 连接已断开，程序结束。")
