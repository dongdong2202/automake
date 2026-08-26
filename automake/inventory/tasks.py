"""
物料保质期预警 Celery 异步任务与定时调度模块
"""

import json
import logging
from datetime import timedelta
from celery import shared_task
from django.utils import timezone
from django.conf import settings

from inventory.models import Material, InventoryRecord
from notifications.models import NotifyEvent
from notifications.services import send_sms_notify
from users.models import User

logger = logging.getLogger(__name__)


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

    # 查询所有入库批次且当前物料库存大于 0 的记录
    records = InventoryRecord.objects.filter(
        record_type=InventoryRecord.RECORD_TYPE_IN,
        expiration_date__isnull=False,
        expiration_date__lte=threshold_date,
        material__quantity__gt=0
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

        content = (
            f'物料【{mat.name}】(编号:{mat.code}, 类别:{mat.get_material_type_display()}) '
            f'入库批次 (单号#{record.id}) 到期日为 {exp_date}，'
            f'{"已过期 " + str(abs(days_left)) + " 天" if is_expired else "距离保质期仅剩 " + str(days_left) + " 天"}！'
            f'当前在库余量为 {mat.quantity} {mat.unit}。请及时处理、分拨或下架清理。'
        )

        extra_data = {
            'material_id': mat.id,
            'material_name': mat.name,
            'material_code': mat.code,
            'record_id': record.id,
            'expiration_date': str(exp_date),
            'days_left': days_left,
            'quantity': str(mat.quantity),
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

        # 2. 发送短信通知 (SMS)
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
                    res = send_sms_notify(
                        phone_numbers=phone,
                        template_param=template_param
                    )
                    if res.get('ok'):
                        sms_sent_phones.append(phone)
                except Exception as sms_err:
                    logger.warning(f'[Celery] 短信发送失败 phone={phone}: {sms_err}')

        # 3. 记录 Redis 防刷标记 (24 小时过期)
        if redis_conn:
            try:
                redis_conn.setex(dedup_key, 86400, '1')
            except Exception:
                pass

        alerted_count += 1
        logger.info(f'[Celery] 保质期告警触发成功: {title}, 事件ID={notify_event.id}, 短信通知={len(sms_sent_phones)}人')

    result = {
        'status': 'completed',
        'scan_date': str(today),
        'alert_days_threshold': alert_days,
        'total_scanned_batches': scanned_count,
        'expiring_soon_batches': expiring_soon_count,
        'expired_batches': expired_count,
        'alerted_batches': alerted_count,
        'skipped_dedup_batches': skipped_count,
    }
    logger.info(f'[Celery] 保质期预警扫描完成: {result}')
    return result
