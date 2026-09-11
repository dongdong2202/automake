"""
物料保质期预警 Celery 异步任务与定时调度模块
"""

import json
import logging
from datetime import timedelta
from celery import shared_task
from django.utils import timezone
from django.conf import settings

from inventory.models import Material, InventoryRecord, StoreInventoryBatch
from notifications.models import NotifyEvent
from notifications.tasks import async_send_sms_task
from users.models import User

logger = logging.getLogger(__name__)


def send_sms_notify(phone_numbers: str, template_param: str, template_code: str = None):
    """
    短信通知分发函数：在生产环境异步投递至 Celery 队列，避免阻塞主任务线程；
    同时支持测试与直接调用。
    """
    try:
        return async_send_sms_task.delay(
            phone_numbers=phone_numbers,
            template_param=template_param,
            template_code=template_code
        )
    except Exception as e:
        logger.warning(f"[Celery] 投递短信任务异常，尝试直接发送: {e}")
        from notifications.services import send_sms_notify as _real_send_sms
        return _real_send_sms(phone_numbers=phone_numbers, template_param=template_param, template_code=template_code)


@shared_task(bind=True, max_retries=2)
def check_inventory_expiration_task(self, alert_days: int = 30, force: bool = False) -> dict:
    """
    定期全量扫描在库物料保质期（Celery / Celery Beat 异步任务）

    触发规则：
      - 距离过期时间 <= alert_days (默认 30 天) 且在库物料批次：
        1. 写入 NotifyEvent 系统告警（0~30天为 warning 预警，已过期为 critical 告警）；
        2. 向所有物料管理员/超管/店长发送短信告警 (send_sms_notify)；
        3. 防重复推送机制：默认每日同一批次仅告警一次（基于 Redis / DB 记录判断）。

    :param alert_days: 预警提前天数，默认 30 天
    :param force: 是否强制触发（忽略当日去重）
    :return: 扫描与告警统计结果字典
    """
    today = timezone.now().date()
    threshold_date = today + timedelta(days=alert_days)

    logger.info(f'[Celery] 开始执行物料保质期预警扫描: 今日={today}, 预警阈值={threshold_date} (<= {alert_days}天)')

    # 查询所有入库批次且当前批次在总仓剩余量大于 0 的记录
    records = InventoryRecord.objects.filter(
        record_type=InventoryRecord.RECORD_TYPE_IN,
        expiration_date__isnull=False,
        expiration_date__lte=threshold_date,
        remaining_quantity__gt=0
    ).select_related('material').order_by('expiration_date')

    # 获取具有手机号的管理员列表 (SUPER_ADMIN, MATERIAL_ADMIN, ADMIN)
    admin_users = User.objects.filter(
        role__in=[User.SUPER_ADMIN, User.MATERIAL_ADMIN, User.ADMIN],
        is_active=True
    ).exclude(phone__isnull=True).exclude(phone='')

    scanned_count = records.count()
    expiring_soon_count = 0
    expired_count = 0
    alerted_count = 0
    skipped_count = 0

    # Redis 去重连接
    redis_conn = None
    try:
        from django_redis import get_redis_connection
        redis_conn = get_redis_connection("default")
    except Exception as e:
        logger.warning(f'[Celery] Redis 连接不可用，将使用 DB 去重策略: {e}')

    for record in records:
        mat = record.material
        exp_date = record.expiration_date
        days_left = (exp_date - today).days

        if days_left < 0:
            expired_count += 1
            is_expired = True
            level = NotifyEvent.LEVEL_CRITICAL
            title = f'【物料过期告警】{mat.name} 已过期 {abs(days_left)} 天'
        else:
            expiring_soon_count += 1
            is_expired = False
            level = NotifyEvent.LEVEL_WARNING
            title = f'【物料保质期预警】{mat.name} 距过期仅剩 {days_left} 天'

        # 防重复推送检查
        dedup_key = f'automake:exp_alert:{record.id}:{today.isoformat()}'
        if not force:
            if redis_conn and redis_conn.get(dedup_key):
                skipped_count += 1
                continue
            # 若无 Redis，检查今日是否已存在该批次的 NotifyEvent
            today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
            if NotifyEvent.objects.filter(
                event_type=NotifyEvent.EVENT_MATERIAL_EXPIRING,
                extra_data__record_id=record.id,
                created_at__gte=today_start
            ).exists():
                skipped_count += 1
                continue

        batch_label = f"批次[{record.batch_no}]" if record.batch_no else f"单号#{record.id}"
        content = (
            f'物料【{mat.name}】(编号:{mat.code}, 类别:{mat.get_material_type_display()}) '
            f'总仓入库{batch_label} 到期日为 {exp_date}，'
            f'{"已过期 " + str(abs(days_left)) + " 天" if is_expired else "距离保质期仅剩 " + str(days_left) + " 天"}！'
            f'当前批次在库余量为 {record.remaining_quantity} {mat.unit}。请及时处理、分拨或下架清理。'
        )

        extra_data = {
            'material_id': mat.id,
            'material_name': mat.name,
            'material_code': mat.code,
            'record_id': record.id,
            'batch_no': record.batch_no,
            'expiration_date': str(exp_date),
            'days_left': days_left,
            'quantity': str(record.remaining_quantity),
            'unit': mat.unit,
            'is_expired': is_expired,
        }

        # 1. 写入平台内部通知 (NotifyEvent)
        notify_event = NotifyEvent.objects.create(
            level=level,
            event_type=NotifyEvent.EVENT_MATERIAL_EXPIRING,
            title=title,
            content=content,
            extra_data=extra_data,
        )

        # 2. 异步投递短信通知 (SMS)
        sms_sent_phones = []
        if admin_users.exists():
            phone_list = [u.phone.strip() for u in admin_users if u.phone.strip()]
            for phone in phone_list:
                try:
                    template_param = json.dumps({
                        "material": mat.name[:10],
                        "days": str(days_left) if days_left >= 0 else "0",
                        "code": mat.code[:10]
                    }, ensure_ascii=False)
                    send_sms_notify(
                        phone_numbers=phone,
                        template_param=template_param
                    )
                    sms_sent_phones.append(phone)
                except Exception as sms_err:
                    logger.warning(f'[Celery] 投递短信任务失败 phone={phone}: {sms_err}')

        # 3. 记录 Redis 防刷标记 (24 小时过期)
        if redis_conn:
            try:
                redis_conn.setex(dedup_key, 86400, '1')
            except Exception:
                pass

        alerted_count += 1
        logger.info(f'[Celery] 保质期告警触发成功: {title}, 事件ID={notify_event.id}, 短信通知={len(sms_sent_phones)}人')

    # 扫描门店端在店批次
    store_batches = StoreInventoryBatch.objects.filter(
        expiration_date__isnull=False,
        expiration_date__lte=threshold_date,
        quantity__gt=0
    ).select_related('store', 'material').prefetch_related('store__admins').order_by('expiration_date')

    store_scanned_count = store_batches.count()
    store_expiring_soon_count = 0
    store_expired_count = 0
    store_alerted_count = 0
    store_skipped_count = 0

    for s_batch in store_batches:
        store = s_batch.store
        mat = s_batch.material
        exp_date = s_batch.expiration_date
        days_left = (exp_date - today).days

        if days_left < 0:
            store_expired_count += 1
            is_expired = True
            level = NotifyEvent.LEVEL_CRITICAL
            title = f'【门店物料过期告警】[{store.name}] {mat.name} 已过期 {abs(days_left)} 天'
        else:
            store_expiring_soon_count += 1
            is_expired = False
            level = NotifyEvent.LEVEL_WARNING
            title = f'【门店物料保质期预警】[{store.name}] {mat.name} 距过期仅剩 {days_left} 天'

        dedup_key = f'automake:store_exp_alert:{s_batch.id}:{today.isoformat()}'
        if not force:
            if redis_conn and redis_conn.get(dedup_key):
                store_skipped_count += 1
                continue
            today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
            if NotifyEvent.objects.filter(
                event_type=NotifyEvent.EVENT_MATERIAL_EXPIRING,
                extra_data__store_batch_id=s_batch.id,
                created_at__gte=today_start
            ).exists():
                store_skipped_count += 1
                continue

        content = (
            f'【{store.name}】店主/管理员您好：门店物料【{mat.name}】批次[{s_batch.batch_no}] 到期日为 {exp_date}，'
            f'{"已过期 " + str(abs(days_left)) + " 天" if is_expired else "距离保质期仅剩 " + str(days_left) + " 天"}！'
            f'当前在店批次库存为 {s_batch.quantity} {mat.unit}。请尽快加料至设备或下架处理。'
        )

        extra_data = {
            'store_id': store.id,
            'store_name': store.name,
            'material_id': mat.id,
            'material_name': mat.name,
            'material_code': mat.code,
            'store_batch_id': s_batch.id,
            'batch_no': s_batch.batch_no,
            'expiration_date': str(exp_date),
            'days_left': days_left,
            'quantity': str(s_batch.quantity),
            'unit': mat.unit,
            'is_expired': is_expired,
        }

        notify_event = NotifyEvent.objects.create(
            level=level,
            event_type=NotifyEvent.EVENT_MATERIAL_EXPIRING,
            title=title,
            content=content,
            extra_data=extra_data,
        )

        # 异步投递短信通知 (SMS)：优先精准提醒该门店店主/管理员 (store.admins)，并抄送系统管理员
        store_admins = [u for u in s_batch.store.admins.all() if u.is_active and u.phone and u.phone.strip()]
        recipient_users = list({u.id: u for u in (store_admins + list(admin_users))}.values())

        sms_sent_phones = []
        if recipient_users:
            phone_list = [u.phone.strip() for u in recipient_users if u.phone and u.phone.strip()]
            for phone in phone_list:
                try:
                    template_param = json.dumps({
                        "material": f"[{store.name[:4]}]{mat.name[:6]}",
                        "days": str(days_left) if days_left >= 0 else "0",
                        "code": mat.code[:10]
                    }, ensure_ascii=False)
                    send_sms_notify(
                        phone_numbers=phone,
                        template_param=template_param
                    )
                    sms_sent_phones.append(phone)
                except Exception as sms_err:
                    logger.warning(f'[Celery] 投递门店保质期短信失败 phone={phone}: {sms_err}')
        if redis_conn:
            try:
                redis_conn.setex(dedup_key, 86400, '1')
            except Exception:
                pass

        store_alerted_count += 1
        logger.info(f'[Celery] 门店保质期告警触发成功: {title}, 事件ID={notify_event.id}, 短信通知={len(sms_sent_phones)}人')

    result = {
        'status': 'completed',
        'scan_date': str(today),
        'alert_days_threshold': alert_days,
        'total_scanned_batches': scanned_count,
        'expiring_soon_batches': expiring_soon_count,
        'expired_batches': expired_count,
        'alerted_batches': alerted_count,
        'skipped_dedup_batches': skipped_count,
        'store_scanned_batches': store_scanned_count,
        'store_expiring_soon_batches': store_expiring_soon_count,
        'store_expired_batches': store_expired_count,
        'store_alerted_batches': store_alerted_count,
        'store_skipped_dedup_batches': store_skipped_count,
    }
    logger.info(f'[Celery] 保质期预警扫描完成: {result}')
    return result
