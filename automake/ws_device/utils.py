"""
ws_device utils.py —— 服务端主动向上位机推送消息的工具函数

使用场景：
  - 订单支付成功后，由 orders/services.py 调用 push_dispense_order() 下发出餐指令
  - 管理后台操作触发某些设备动作时，调用 push_device_message() 通知设备

注意：
  - 此模块内的函数均为同步函数，可在普通 Django 视图和 Celery 任务中直接调用。
  - 若在异步上下文中使用，请改用 channel_layer.group_send()（await 形式）。
"""

import logging
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger('ws_device')


def push_device_message(sn: str, payload: dict) -> bool:
    """
    向指定设备（sn）的 WebSocket 连接推送任意消息。

    :param sn:      设备编号（与 WebSocket 连接时 URL 中的 sn 一致）
    :param payload: 要推送的消息体（dict），会被序列化为 JSON 发给 Java 客户端
    :return:        True 表示成功发送到 Channel Layer（不代表设备已收到）

    示例调用：
        push_device_message('SN001', {
            'type': 'dispense_order',
            'order_no': '20260622155515197985',
            'items': [{'name': '拿铁', 'qty': 1}]
        })
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        logger.error('[WS Push] Channel Layer 未配置，无法推送消息。')
        return False

    group_name = f'device_{sn}'
    try:
        # async_to_sync 将异步的 group_send 包装为同步调用
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                'type': 'device.message',   # 对应 DeviceConsumer.device_message 方法
                'payload': payload,
            }
        )
        logger.info(f'[WS Push] 消息已推送到 group={group_name}, type={payload.get("type")}')
        return True
    except Exception as e:
        logger.error(f'[WS Push] 推送失败: sn={sn}, error={e}')
        return False


def push_dispense_order(sn: str, order_no: str, items: list) -> bool:
    """
    向上位机下发出餐指令（封装了 push_device_message）。

    :param sn:       设备编号
    :param order_no: 订单号
    :param items:    出餐商品列表，格式如 [{'name': '拿铁', 'qty': 1, 'sku': '标准'}]
    :return:         是否成功推送到 Channel Layer
    """
    payload = {
        'type': 'dispense_order',
        'order_no': order_no,
        'data': {
            'items': items,
        }
    }
    return push_device_message(sn, payload)
