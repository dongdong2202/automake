"""
消息通知业务函数模块

提供三类核心功能：
  1. send_order_status_notify() — 订单状态变更通知（发给下单用户）
  2. send_alert_notify()        — 告警消息推送（发给管理员/运营）
  3. create_pickup_code()       — 生成取餐码，并推送取餐码通知

调用时序（与 orders/payments 联动）：
  支付成功 → process_payment_success()
  设备回调制作中 → send_order_status_notify(order, 'making')
  设备回调完成   → create_pickup_code(order) + send_order_status_notify(order, 'success')
  设备异常/断线  → send_alert_notify(device, level='critical')

所有微信消息发送均通过 Celery 异步执行，不阻塞主请求链路。

微信订阅消息模板说明（需要在 .env 中配置对应 template_id）：
  WECHAT_TPL_ORDER_STATUS  订单状态通知模板
  WECHAT_TPL_ALERT         告警通知模板（发给管理员）
  WECHAT_TPL_PICKUP        取餐码通知模板（发给用户）
"""

import logging
from datetime import timedelta
from django.conf import settings
from django.utils import timezone

from .models import WxSubscribeMsg, PickupCode, NotifyEvent

logger = logging.getLogger(__name__)

# 订单状态中文映射，用于组装消息文案
ORDER_STATUS_CN = {
    'created': '已创建',
    'pending_dispense': '等待制作',
    'making': '制作中',
    'success': '制作完成，请取餐',
    'cancelled': '已取消',
    'failed': '制作失败',
    'refunding': '退款中',
    'refunded': '已退款',
}

# 取餐码默认有效期（分钟）
PICKUP_CODE_EXPIRE_MINUTES = getattr(settings, 'PICKUP_CODE_EXPIRE_MINUTES', 30)


# ============================================================
# 订单状态变更通知
# ============================================================

def send_order_status_notify(order, new_status: str, extra_remark: str = '') -> None:
    """
    发送订单状态变更的微信订阅消息通知（异步）

    在订单状态流转的关键节点调用（如：制作中、已完成、已失败）。
    只有用户有 openid 才能发送，管理员账号跳过。

    :param order:       OrderMain 实例
    :param new_status:  新订单状态字符串（如 'making', 'success'）
    :param extra_remark: 附加说明（可选，如等待时间估算）
    """
    from notifications.tasks import send_wx_subscribe_msg

    user = order.user
    openid = user.openid if user else None

    # 用户没有 openid（管理员账号）则跳过
    if not openid:
        logger.debug(f'[Notify] 用户无 openid，跳过订单状态通知: order_no={order.order_no}')
        return

    template_id = getattr(settings, 'WECHAT_TPL_ORDER_STATUS', '')
    if not template_id:
        logger.warning('[Notify] 未配置 WECHAT_TPL_ORDER_STATUS 模板 ID，跳过推送')
        return

    status_cn = ORDER_STATUS_CN.get(new_status, new_status)
    item_name = order.items.values_list('item_name', flat=True).first() or '商品'

    # 组装微信消息模板数据（字段名需与微信后台的模板变量严格对应）
    # 通用模板示例（实际以申请的模板为准）：
    #   {{thing1.DATA}} 商品名称
    #   {{phrase2.DATA}} 订单状态
    #   {{character_string3.DATA}} 订单号
    #   {{thing4.DATA}} 备注
    data_payload = {
        "thing1": {"value": item_name[:20]},              # 商品名称（最长20字）
        "phrase2": {"value": status_cn},                  # 订单状态
        "character_string3": {"value": order.order_no},  # 订单编号
        "thing4": {"value": (extra_remark or '如有问题请联系客服')[:20]},
    }

    # 创建发送记录（pending 状态），进入 Celery 队列
    msg = WxSubscribeMsg.objects.create(
        user=user,
        openid=openid,
        order=order,
        msg_type=WxSubscribeMsg.TYPE_ORDER_STATUS,
        template_id=template_id,
        data_payload=data_payload,
        status=WxSubscribeMsg.STATUS_PENDING,
    )

    # 异步发送（Celery），不阻塞主流程
    task = send_wx_subscribe_msg.delay(msg.id)
    msg.celery_task_id = task.id
    msg.save(update_fields=['celery_task_id'])

    # 同时记录 NotifyEvent（系统内部事件日志）
    NotifyEvent.objects.create(
        level=NotifyEvent.LEVEL_INFO,
        event_type=NotifyEvent.EVENT_ORDER_STATUS,
        order=order,
        title=f'订单状态：{status_cn}',
        content=f'订单 {order.order_no} 状态变更为【{status_cn}】。{extra_remark}',
        extra_data={'new_status': new_status, 'openid': openid}
    )

    logger.info(
        f'[Notify] 订单状态通知已入队: order_no={order.order_no}, '
        f'status={new_status}, msg_id={msg.id}'
    )


# ============================================================
# 告警消息推送（发给管理员）
# ============================================================

def send_alert_notify(
    title: str,
    content: str,
    level: str = NotifyEvent.LEVEL_WARNING,
    device=None,
    order=None,
    extra_data: dict = None,
) -> None:
    """
    发送告警消息通知给所有管理员（异步）

    适用场景：
      - 设备断线或故障（level='critical'）
      - 物料不足告警（level='warning'）
      - 订单异常（level='warning'）

    会向所有拥有 openid 的 ADMIN/SUPER_ADMIN 账号推送微信订阅消息。
    即使管理员未订阅模板，也会写入 NotifyEvent 供后台查看。

    :param title:      告警标题（简短，最多 20 字）
    :param content:    告警详情
    :param level:      告警级别 ('info' / 'warning' / 'critical')
    :param device:     关联设备（可选）
    :param order:      关联订单（可选）
    :param extra_data: 附加数据（用于调试）
    """
    from notifications.tasks import send_wx_subscribe_msg
    from users.models import User

    # 记录系统通知事件（无论是否能发微信，都要先写日志）
    notify = NotifyEvent.objects.create(
        level=level,
        event_type=NotifyEvent.EVENT_DEVICE_ALERT if device else NotifyEvent.EVENT_SYSTEM,
        order=order,
        device=device,
        title=title,
        content=content,
        extra_data=extra_data or {},
    )

    template_id = getattr(settings, 'WECHAT_TPL_ALERT', '')
    if not template_id:
        logger.warning(f'[Notify] 未配置 WECHAT_TPL_ALERT 模板 ID，仅记录 NotifyEvent: id={notify.id}')
        return

    # 获取所有管理员的 openid（仅有 openid 的账号才能接收微信订阅消息）
    admins = User.objects.filter(
        role__in=(User.SUPER_ADMIN, User.ADMIN),
        is_active=True,
        openid__isnull=False,
    ).exclude(openid='')

    if not admins.exists():
        logger.warning('[Notify] 无可用管理员 openid，跳过微信告警推送')
        return

    # 组装告警消息模板数据
    # 告警模板示例字段：
    #   {{thing1.DATA}} 告警标题
    #   {{thing2.DATA}} 告警详情
    #   {{time3.DATA}}  发生时间
    #   {{phrase4.DATA}} 告警级别
    level_cn = {'info': '提示', 'warning': '⚠️警告', 'critical': '🚨严重告警'}.get(level, level)
    data_payload = {
        "thing1": {"value": title[:20]},
        "thing2": {"value": content[:20]},
        "time3": {"value": timezone.now().strftime('%m月%d日 %H:%M')},
        "phrase4": {"value": level_cn},
    }

    # 为每位管理员创建消息记录并入队
    for admin in admins:
        msg = WxSubscribeMsg.objects.create(
            user=admin,
            openid=admin.openid,
            order=order,
            msg_type=WxSubscribeMsg.TYPE_ALERT,
            template_id=template_id,
            data_payload=data_payload,
            status=WxSubscribeMsg.STATUS_PENDING,
        )
        task = send_wx_subscribe_msg.delay(msg.id)
        msg.celery_task_id = task.id
        msg.save(update_fields=['celery_task_id'])

    logger.info(
        f'[Notify] 告警通知已入队: level={level}, title={title}, '
        f'管理员数量={admins.count()}'
    )


# ============================================================
# 生成取餐码并通知
# ============================================================

def create_pickup_code(order, max_retry: int = 5) -> PickupCode:
    """
    为完成制作的订单生成取餐码，并异步推送取餐码通知

    取餐码 6 位数字，有效期默认 30 分钟（由 settings.PICKUP_CODE_EXPIRE_MINUTES 控制）。
    由于 code 字段有 unique 约束，用重试机制防止极低概率的碰撞。

    :param order:      OrderMain 实例（订单状态应为 success/making）
    :param max_retry:  碰撞重试上限
    :return:           创建的 PickupCode 实例
    :raises ValueError: 超过重试次数仍碰撞时抛出
    """
    from .models import generate_pickup_code
    from notifications.tasks import send_wx_subscribe_msg

    # 幂等检查：若已有取餐码则直接返回
    existing = PickupCode.objects.filter(order=order).first()
    if existing:
        logger.info(f'[Notify] 取餐码已存在: order_no={order.order_no}, code={existing.code}')
        return existing

    expires_at = timezone.now() + timedelta(minutes=PICKUP_CODE_EXPIRE_MINUTES)

    # 带重试的唯一码生成（碰撞概率极低，保留重试兜底）
    for attempt in range(max_retry):
        code = generate_pickup_code()
        if not PickupCode.objects.filter(code=code).exists():
            break
    else:
        raise ValueError(f'取餐码生成碰撞超过上限（{max_retry}次），请稍后重试')

    pickup = PickupCode.objects.create(
        order=order,
        code=code,
        expires_at=expires_at,
        status=PickupCode.STATUS_ACTIVE,
    )
    logger.info(
        f'[Notify] 取餐码生成成功: order_no={order.order_no}, '
        f'code={code}, expires_at={expires_at}'
    )

    # 记录系统通知事件
    NotifyEvent.objects.create(
        level=NotifyEvent.LEVEL_INFO,
        event_type=NotifyEvent.EVENT_PICKUP_READY,
        order=order,
        title='取餐就绪',
        content=f'您的餐品已准备好，取餐码：{code}，有效期 {PICKUP_CODE_EXPIRE_MINUTES} 分钟',
        extra_data={'code': code, 'expires_at': expires_at.isoformat()},
    )

    # 推送取餐码微信通知（异步）
    _send_pickup_code_notify(order, pickup)

    return pickup


def _send_pickup_code_notify(order, pickup: PickupCode) -> None:
    """
    内部函数：向用户推送取餐码微信订阅消息

    :param order:   OrderMain 实例
    :param pickup:  PickupCode 实例
    """
    from notifications.tasks import send_wx_subscribe_msg

    user = order.user
    openid = user.openid if user else None

    if not openid:
        logger.debug(f'[Notify] 用户无 openid，跳过取餐码推送: order_no={order.order_no}')
        return

    template_id = getattr(settings, 'WECHAT_TPL_PICKUP', '')
    if not template_id:
        logger.warning('[Notify] 未配置 WECHAT_TPL_PICKUP 模板 ID，跳过推送')
        return

    item_name = order.items.values_list('item_name', flat=True).first() or '餐品'

    # 取餐码模板示例字段：
    #   {{character_string1.DATA}} 取餐码
    #   {{thing2.DATA}}            商品名称
    #   {{time3.DATA}}             过期时间
    #   {{character_string4.DATA}} 订单号
    data_payload = {
        "character_string1": {"value": pickup.code},
        "thing2": {"value": item_name[:20]},
        "time3": {
            "value": pickup.expires_at.strftime('%H:%M 前有效')
        },
        "character_string4": {"value": order.order_no},
    }

    msg = WxSubscribeMsg.objects.create(
        user=user,
        openid=openid,
        order=order,
        msg_type=WxSubscribeMsg.TYPE_PICKUP,
        template_id=template_id,
        data_payload=data_payload,
        status=WxSubscribeMsg.STATUS_PENDING,
    )
    task = send_wx_subscribe_msg.delay(msg.id)
    msg.celery_task_id = task.id
    msg.save(update_fields=['celery_task_id'])

    logger.info(
        f'[Notify] 取餐码通知已入队: order_no={order.order_no}, '
        f'code={pickup.code}, msg_id={msg.id}'
    )


# ============================================================
# 物料不足告警（便捷函数）
# ============================================================

def send_material_low_alert(device, material_code: str, current_qty, threshold) -> None:
    """
    物料不足告警通知（便捷封装）

    当物料量低于阈值时调用，发送微信告警并记录 NotifyEvent。

    :param device:        Device 实例
    :param material_code: 物料代码（如 'coffee_bean'）
    :param current_qty:   当前剩余量
    :param threshold:     告警阈值
    """
    title = f'物料不足告警'
    content = (
        f'设备 {device.device_sn} 的【{material_code}】'
        f'剩余 {current_qty}，低于阈值 {threshold}，请及时补充。'
    )
    send_alert_notify(
        title=title,
        content=content,
        level=NotifyEvent.LEVEL_WARNING,
        device=device,
        extra_data={
            'device_sn': device.device_sn,
            'material_code': material_code,
            'current_qty': str(current_qty),
            'threshold': str(threshold),
        }
    )


# ============================================================
# 设备告警（便捷函数）
# ============================================================

def send_device_alert(device, reason: str, level: str = NotifyEvent.LEVEL_CRITICAL) -> None:
    """
    设备故障/断线告警通知（便捷封装）

    :param device:  Device 实例
    :param reason:  告警原因描述
    :param level:   告警级别（默认 critical）
    """
    title = f'设备告警：{device.device_sn}'
    content = f'设备 {device.device_sn}（{device.device_name}）发生告警：{reason}'
    send_alert_notify(
        title=title,
        content=content,
        level=level,
        device=device,
        extra_data={
            'device_sn': device.device_sn,
            'device_name': device.device_name,
            'reason': reason,
        }
    )


# ============================================================
# 扫码核销取餐码
# ============================================================

def verify_pickup_code(code: str, device_sn: str = '') -> dict:
    """
    核销取餐码（设备扫码或后台操作调用）

    验证取餐码有效性，成功后标记为已使用，返回订单信息供设备展示。

    :param code:       用户出示的 6 位取餐码
    :param device_sn:  操作设备序列号（记录用，可选）
    :return:           {'ok': True, 'order_no': ..., 'items': [...]} 或 {'ok': False, 'reason': ...}
    """
    try:
        pickup = PickupCode.objects.select_related('order').get(code=code)
    except PickupCode.DoesNotExist:
        return {'ok': False, 'reason': '取餐码不存在'}

    if pickup.status == PickupCode.STATUS_USED:
        return {'ok': False, 'reason': '取餐码已使用'}

    if pickup.status == PickupCode.STATUS_EXPIRED or timezone.now() > pickup.expires_at:
        # 同步更新状态为 expired
        pickup.status = PickupCode.STATUS_EXPIRED
        pickup.save(update_fields=['status'])
        return {'ok': False, 'reason': f'取餐码已过期（有效期至 {pickup.expires_at.strftime("%H:%M")}）'}

    # 核销成功，标记为已使用
    pickup.status = PickupCode.STATUS_USED
    pickup.scanned_at = timezone.now()
    pickup.save(update_fields=['status', 'scanned_at'])

    order = pickup.order
    items = list(order.items.values('item_name', 'sku_name', 'quantity'))

    logger.info(
        f'[Notify] 取餐码核销成功: code={code}, '
        f'order_no={order.order_no}, device_sn={device_sn}'
    )

    return {
        'ok': True,
        'order_no': order.order_no,
        'items': items,
        'scanned_at': pickup.scanned_at.isoformat(),
    }


# ============================================================
# 发送短信通知 (阿里云 SMS)
# ============================================================

def send_sms_notify(phone_numbers: str, template_param: str = None, template_code: str = None, sign_name: str = None) -> dict:
    """
    发送阿里云短信通知（支持其他模块调用）

    :param phone_numbers: 接收短信的手机号码，多个用逗号隔开
    :param template_param: 短信模板变量对应的 JSON 字符串，例如 '{"code":"1234"}'
    :param template_code: 短信模板代码，默认从 .env 中读取 ali.sms.default_templateCode
    :param sign_name: 短信签名名称，默认从 .env 中读取 ali.sms.default_signName
    :return: 包含成功与否和返回数据的字典，如 {'ok': True, 'data': ...}
    """
    import os
    import codecs
    from alibabacloud_dysmsapi20170525.client import Client as DysmsapiClient
    from alibabacloud_tea_openapi import models as open_api_models
    from alibabacloud_dysmsapi20170525 import models as dysmsapi_models

    access_key_id = os.environ.get('ali.root.accessKeyId')
    access_key_secret = os.environ.get('ali.root.accessKeySecret')
    region_id = os.environ.get('ali.root.regionId', 'cn-zhangjiakou')
    
    default_sign_name = os.environ.get('ali.sms.default_signName')
    default_template_code = os.environ.get('ali.sms.default_templateCode')

    if not all([access_key_id, access_key_secret]):
        logger.error('[Notify] 阿里云 SMS 配置缺失 (access_key)')
        return {'ok': False, 'reason': '阿里云 SMS 配置缺失'}

    # 中文的 Unicode 转义在 dotenv 读取时可能被原样保留为字符串，如果需要转换：
    if default_sign_name and '\\u' in default_sign_name:
        try:
            default_sign_name = codecs.decode(default_sign_name, 'unicode_escape')
        except Exception as e:
            logger.warning(f'[Notify] 短信签名解码失败: {e}')

    sign_name = sign_name or default_sign_name
    template_code = template_code or default_template_code

    if not all([sign_name, template_code]):
        logger.error('[Notify] 阿里云 SMS 配置缺失 (sign_name 或 template_code)')
        return {'ok': False, 'reason': '签名或模板代码未提供'}

    try:
        config = open_api_models.Config(
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
            region_id=region_id
        )
        config.endpoint = f'dysmsapi.aliyuncs.com'
        client = DysmsapiClient(config)

        send_request = dysmsapi_models.SendSmsRequest(
            phone_numbers=phone_numbers,
            sign_name=sign_name,
            template_code=template_code,
            template_param=template_param
        )
        
        response = client.send_sms(send_request)
        
        if response.body.code == 'OK':
            logger.info(f'[Notify] 短信发送成功: phone={phone_numbers}, req_id={response.body.request_id}')
            return {'ok': True, 'data': response.body.to_map()}
        else:
            logger.error(f'[Notify] 短信发送失败: phone={phone_numbers}, code={response.body.code}, msg={response.body.message}')
            return {'ok': False, 'reason': response.body.message}
            
    except Exception as e:
        logger.error(f'[Notify] 短信发送异常: {str(e)}')
        return {'ok': False, 'reason': str(e)}

