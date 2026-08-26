"""
消息通知 Celery 异步任务模块

所有涉及网络 IO 的消息发送（调用微信 API）均通过 Celery 异步执行，
防止阻塞 Django 主线程，确保消息发送高可靠。

重试策略：
  - 自动重试最多 3 次，间隔指数退避 (60s → 120s → 240s)
  - 所有重试失败后，将 WxSubscribeMsg 状态更新为 'failed'，便于人工排查

使用方式（在 services.py 中调用）：
  from notifications.tasks import send_wx_subscribe_msg
  send_wx_subscribe_msg.delay(msg_id)
"""

import logging
import requests
from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def _get_access_token() -> str:
    """
    获取微信小程序 access_token（带简单内存缓存，生产建议用 Redis 缓存 7000s）

    access_token 有效期为 7200 秒，微信接口有频率限制（每日 2000 次），
    生产环境必须缓存复用，不能每次请求都重新拉取。
    """
    from django_redis import get_redis_connection
    redis_conn = get_redis_connection("default")

    # 尝试从 Redis 读取缓存的 access_token（key 格式 automake:wx:access_token）
    cache_key = 'automake:wx:access_token'
    cached = redis_conn.get(cache_key)
    if cached:
        return cached.decode('utf-8')

    # 未命中缓存，向微信接口申请新 token
    app_id = settings.WECHAT_APP_ID
    secret = settings.WECHAT_APP_SECRET

    if not app_id or not secret:
        raise ValueError('微信 AppID 或 AppSecret 未配置，请检查 .env 文件')

    resp = requests.get(
        'https://api.weixin.qq.com/cgi-bin/token',
        params={
            'grant_type': 'client_credential',
            'appid': app_id,
            'secret': secret,
        },
        timeout=10
    )
    resp.raise_for_status()
    data = resp.json()

    if 'errcode' in data and data['errcode'] != 0:
        raise ValueError(f"获取 access_token 失败: {data.get('errmsg')}")

    token = data['access_token']
    # 缓存 7000 秒（比微信的 7200 秒稍短，避免临界过期）
    redis_conn.setex(cache_key, 7000, token)
    return token


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,       # 首次重试等待 60 秒
    autoretry_for=(Exception,),   # 所有异常均自动重试
    retry_backoff=True,           # 指数退避：60s → 120s → 240s
    retry_jitter=True,            # 加入随机抖动，防止大量任务同时重试
)
def send_wx_subscribe_msg(self, msg_id: int) -> dict:
    """
    发送微信订阅消息（异步 Celery 任务）

    通过微信的 subscribeMessage.send 接口向用户发送服务通知。
    支持三种类型：order_status（订单状态）、alert（告警）、pickup（取餐码）。

    微信接口文档：
      https://developers.weixin.qq.com/miniprogram/dev/api-backend/open-api/subscribe-message/subscribeMessage.send.html

    :param msg_id: WxSubscribeMsg 主键 ID
    :return: 微信接口返回结果
    """
    from notifications.models import WxSubscribeMsg

    # 查询消息记录，如果不存在则直接结束（无需重试）
    try:
        msg = WxSubscribeMsg.objects.get(pk=msg_id)
    except WxSubscribeMsg.DoesNotExist:
        logger.error(f'[Celery] WxSubscribeMsg id={msg_id} 不存在，跳过')
        return {'status': 'skipped', 'reason': 'record not found'}

    # 防止重复发送：若已成功或已跳过，不重复发送
    if msg.status in (WxSubscribeMsg.STATUS_SUCCESS, WxSubscribeMsg.STATUS_SKIPPED):
        logger.info(f'[Celery] 消息 id={msg_id} 已处理（状态={msg.status}），跳过')
        return {'status': 'already_done'}

    # 更新 Celery 任务 ID（用于追踪）
    if not msg.celery_task_id:
        msg.celery_task_id = self.request.id or ''
        msg.save(update_fields=['celery_task_id'])

    logger.info(
        f'[Celery] 开始发送微信订阅消息: id={msg_id}, '
        f'type={msg.msg_type}, openid={msg.openid}'
    )

    try:
        access_token = _get_access_token()
    except ValueError as e:
        # access_token 获取失败，直接标记失败，不重试（配置问题非临时错误）
        logger.error(f'[Celery] 获取 access_token 失败，id={msg_id}: {e}')
        msg.status = WxSubscribeMsg.STATUS_FAILED
        msg.wx_errmsg = str(e)
        msg.save(update_fields=['status', 'wx_errmsg'])
        return {'status': 'failed', 'reason': str(e)}

    # 调用微信订阅消息发送接口
    url = f'https://api.weixin.qq.com/cgi-bin/message/subscribe/send?access_token={access_token}'
    payload = {
        'touser': msg.openid,
        'template_id': msg.template_id,
        'data': msg.data_payload,
    }

    # 如果消息有跳转 page（小程序内页面），可在 data_payload 中携带 'miniprogram_state' 和 'lang'
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        result = resp.json()
    except requests.RequestException as exc:
        # 网络异常：更新重试次数后，Celery 会自动重试
        msg.retry_count += 1
        msg.save(update_fields=['retry_count'])
        logger.warning(f'[Celery] 网络异常，将重试 id={msg_id}: {exc}')
        raise self.retry(exc=exc, countdown=60 * (2 ** (self.request.retries)))

    wx_errcode = result.get('errcode', 0)
    wx_errmsg = result.get('errmsg', '')

    # 微信错误码 43101：用户未订阅该消息模板（需要用户主动订阅）
    if wx_errcode == 43101:
        logger.warning(
            f'[Celery] 用户未订阅模板，标记为 skipped: id={msg_id}, openid={msg.openid}'
        )
        msg.status = WxSubscribeMsg.STATUS_SKIPPED
        msg.wx_errcode = wx_errcode
        msg.wx_errmsg = wx_errmsg
        msg.save(update_fields=['status', 'wx_errcode', 'wx_errmsg'])
        return {'status': 'skipped', 'errcode': wx_errcode}

    if wx_errcode != 0:
        # 其他微信错误，重试有可能恢复（如 token 过期：-1，系统繁忙：40001）
        # token 过期时清除缓存，下次重试会重新获取
        if wx_errcode in (-1, 40001, 42001):
            from django_redis import get_redis_connection
            get_redis_connection("default").delete('automake:wx:access_token')
            logger.warning(f'[Celery] access_token 可能已过期，已清除缓存，将重试 id={msg_id}')
            msg.retry_count += 1
            msg.save(update_fields=['retry_count'])
            raise self.retry(countdown=30)

        # 其他不可恢复错误，直接标记失败
        logger.error(
            f'[Celery] 微信接口返回错误，id={msg_id}: errcode={wx_errcode}, errmsg={wx_errmsg}'
        )
        msg.status = WxSubscribeMsg.STATUS_FAILED
        msg.wx_errcode = wx_errcode
        msg.wx_errmsg = wx_errmsg
        msg.save(update_fields=['status', 'wx_errcode', 'wx_errmsg'])
        return {'status': 'failed', 'errcode': wx_errcode, 'errmsg': wx_errmsg}

    # 发送成功
    msg.status = WxSubscribeMsg.STATUS_SUCCESS
    msg.wx_errcode = 0
    msg.wx_errmsg = 'ok'
    msg.sent_at = timezone.now()
    msg.save(update_fields=['status', 'wx_errcode', 'wx_errmsg', 'sent_at'])
    logger.info(f'[Celery] 微信订阅消息发送成功: id={msg_id}')
    return {'status': 'success'}


@shared_task(bind=True, max_retries=2)
def expire_pickup_codes(self) -> dict:
    """
    定期清理过期取餐码（Celery Beat 定时任务）

    将超过 expires_at 且状态仍为 active 的取餐码批量标记为 expired。
    建议配置为每 5 分钟执行一次。

    :return: 处理结果统计
    """
    from notifications.models import PickupCode

    now = timezone.now()
    # 批量更新，效率高于逐条 save()
    updated = PickupCode.objects.filter(
        status=PickupCode.STATUS_ACTIVE,
        expires_at__lt=now
    ).update(status=PickupCode.STATUS_EXPIRED)

    logger.info(f'[Celery] 清理过期取餐码：共处理 {updated} 条')
    return {'expired_count': updated}
