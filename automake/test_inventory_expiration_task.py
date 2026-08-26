"""
物料保质期预警、短信通知与 Celery 定时任务专项测试
"""

import os
import django
from datetime import timedelta
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')
django.setup()

from django.test import TestCase
from django.utils import timezone
from inventory.models import Material, InventoryRecord
from notifications.models import NotifyEvent
from users.models import User
from inventory.tasks import check_inventory_expiration_task


def run_tests():
    print("🚀 开始测试物料保质期预警、平台告警、去重及 Celery 任务...")

    today = timezone.now().date()

    # 1. 准备物料数据
    mat_normal, _ = Material.objects.get_or_create(
        code='MAT_EXP_NORMAL_01',
        defaults={
            'name': '常温保鲜红茶',
            'material_type': Material.TYPE_INGREDIENT,
            'price': Decimal('30.00'),
            'quantity': Decimal('100.00'),
            'unit': '包',
            'shelf_life': '12个月',
            'storage_conditions': '常温'
        }
    )

    mat_expiring, _ = Material.objects.get_or_create(
        code='MAT_EXP_SOON_02',
        defaults={
            'name': '短保鲜牛奶 (临期15天)',
            'material_type': Material.TYPE_INGREDIENT,
            'price': Decimal('15.00'),
            'quantity': Decimal('50.00'),
            'unit': '盒',
            'shelf_life': '30天',
            'storage_conditions': '冷藏'
        }
    )

    mat_expired, _ = Material.objects.get_or_create(
        code='MAT_EXP_PAST_03',
        defaults={
            'name': '鲜榨柠檬汁 (已过期5天)',
            'material_type': Material.TYPE_INGREDIENT,
            'price': Decimal('20.00'),
            'quantity': Decimal('20.00'),
            'unit': '瓶',
            'shelf_life': '7天',
            'storage_conditions': '冷藏'
        }
    )

    # 2. 准备管理员手机号
    admin_user = User.objects.filter(role=User.SUPER_ADMIN).first()
    if admin_user:
        admin_user.phone = '13800138000'
        admin_user.save(update_fields=['phone'])

    # 3. 创建 3 类入库批次记录
    # 批次 1: 正常批次 (120天后到期)
    rec_normal, _ = InventoryRecord.objects.get_or_create(
        material=mat_normal,
        record_type=InventoryRecord.RECORD_TYPE_IN,
        quantity=Decimal('100.00'),
        price=Decimal('30.00'),
        expiration_date=today + timedelta(days=120),
        defaults={'remarks': '正常保质期批次'}
    )

    # 批次 2: 临期批次 (15天后到期 <= 30天)
    rec_expiring, _ = InventoryRecord.objects.get_or_create(
        material=mat_expiring,
        record_type=InventoryRecord.RECORD_TYPE_IN,
        quantity=Decimal('50.00'),
        price=Decimal('15.00'),
        expiration_date=today + timedelta(days=15),
        defaults={'remarks': '临期15天批次'}
    )

    # 批次 3: 已过期批次 (5天前已过期 < 0天)
    rec_expired, _ = InventoryRecord.objects.get_or_create(
        material=mat_expired,
        record_type=InventoryRecord.RECORD_TYPE_IN,
        quantity=Decimal('20.00'),
        price=Decimal('20.00'),
        expiration_date=today - timedelta(days=5),
        defaults={'remarks': '已过期5天批次'}
    )

    # 清理旧的历史测试事件
    NotifyEvent.objects.filter(event_type=NotifyEvent.EVENT_MATERIAL_EXPIRING).delete()

    # 4. 执行 Celery 任务 (force=True)
    print("  -> 执行保质期预警 Celery 异步任务 (force=True)...")
    res = check_inventory_expiration_task(alert_days=30, force=True)
    print(f"  ✓ 任务返回结果: {res}")

    assert res['status'] == 'completed'
    assert res['alert_days_threshold'] == 30
    assert res['expiring_soon_batches'] >= 1
    assert res['expired_batches'] >= 1
    assert res['alerted_batches'] >= 2

    # 5. 校验数据库中的 NotifyEvent 平台告警
    events = list(NotifyEvent.objects.filter(event_type=NotifyEvent.EVENT_MATERIAL_EXPIRING))
    print(f"  ✓ 生成平台通知事件数: {len(events)}")
    assert len(events) >= 2

    # 验证临期预警
    soon_event = NotifyEvent.objects.filter(
        event_type=NotifyEvent.EVENT_MATERIAL_EXPIRING,
        level=NotifyEvent.LEVEL_WARNING,
        extra_data__material_code='MAT_EXP_SOON_02'
    ).first()
    assert soon_event is not None
    assert "临期" in soon_event.title or "15" in soon_event.title
    print(f"  ✓ 临期预警事件校验通过: [{soon_event.title}] - {soon_event.content[:40]}...")

    # 验证过期告警
    expired_event = NotifyEvent.objects.filter(
        event_type=NotifyEvent.EVENT_MATERIAL_EXPIRING,
        level=NotifyEvent.LEVEL_CRITICAL,
        extra_data__material_code='MAT_EXP_PAST_03'
    ).first()
    assert expired_event is not None
    assert "过期" in expired_event.title
    print(f"  ✓ 严重过期事件校验通过: [{expired_event.title}] - {expired_event.content[:40]}...")

    # 6. 验证防重复报警机制 (force=False)
    print("  -> 测试当日去重机制 (再次执行 force=False)...")
    res2 = check_inventory_expiration_task(alert_days=30, force=False)
    print(f"  ✓ 第二次执行结果 (去重跳过): {res2}")
    assert res2['alerted_batches'] == 0
    assert res2['skipped_dedup_batches'] >= 2
    print("  ✓ 当日去重防轰炸机制 100% 生效！")

    print("\n🎉 全部物料保质期预警与 Celery 异步任务专项自动化测试 100% PASS！")


if __name__ == '__main__':
    run_tests()
