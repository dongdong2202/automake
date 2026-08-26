"""
验证永久有效物料（如纸杯、吸管、杯盖等耗材）不填保质期、永久有效标签及不触发任何误报警专项测试
"""

import os
import django
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')
django.setup()

from inventory.models import Material, InventoryRecord, parse_shelf_life_duration_days, calculate_default_expiration_date
from admin_api.serializers import MaterialSerializer, InventoryRecordSerializer
from inventory.tasks import check_inventory_expiration_task
from notifications.models import NotifyEvent


def test_permanent_materials():
    print("🚀 开始测试永久有效物料（如纸杯、耗材）业务逻辑...")

    # 1. 验证各种永久有效文本解析
    assert parse_shelf_life_duration_days('') is None
    assert parse_shelf_life_duration_days(None) is None
    assert parse_shelf_life_duration_days('永久有效') is None
    assert parse_shelf_life_duration_days('无') is None
    assert parse_shelf_life_duration_days('长期') is None
    print("  ✓ 永久有效与空保质期解析为 None 校验通过")

    # 2. 创建纸杯物料（永久有效，无保质期）
    mat_cup, _ = Material.objects.get_or_create(
        code='TEST_CUP_PERMANENT_01',
        defaults={
            'name': '加厚环保热饮纸杯 500ml',
            'material_type': Material.TYPE_CUP,
            'price': Decimal('0.35'),
            'quantity': Decimal('1000.00'),
            'unit': '个',
            'shelf_life': '',
            'storage_conditions': '常温干燥'
        }
    )
    mat_cup.shelf_life = ''
    mat_cup.save()

    # 3. 验证计算过期日为 None
    exp_date = calculate_default_expiration_date(mat_cup)
    print(f"  ✓ 纸杯品类计算默认批次到期日: {exp_date} (None 代表无到期日)")
    assert exp_date is None

    # 4. 验证 Serializer 输出
    mat_data = MaterialSerializer(mat_cup).data
    assert mat_data['shelf_life_days'] is None
    assert mat_data['default_expiration_date'] == ''
    print("  ✓ MaterialSerializer 输出 shelf_life_days=None, default_expiration_date=''")

    # 5. 创建该纸杯的入库批次记录 (expiration_date=None)
    rec_cup, _ = InventoryRecord.objects.get_or_create(
        material=mat_cup,
        record_type=InventoryRecord.RECORD_TYPE_IN,
        quantity=Decimal('500.00'),
        price=Decimal('0.35'),
        expiration_date=None,
        defaults={'remarks': '采购常备纸杯'}
    )
    rec_data = InventoryRecordSerializer(rec_cup).data
    assert rec_data['expiration_status'] == 'permanent'
    assert rec_data['days_until_expiration'] is None
    print(f"  ✓ 流水记录序列化输出 expiration_status='{rec_data['expiration_status']}'")

    # 6. 执行全库保质期扫描任务，确认永久有效批次绝不产生误报警
    NotifyEvent.objects.filter(event_type=NotifyEvent.EVENT_MATERIAL_EXPIRING).delete()
    scan_res = check_inventory_expiration_task(alert_days=30, force=True)
    
    # 验证生成的告警中绝对没有纸杯
    cup_alerts = NotifyEvent.objects.filter(
        event_type=NotifyEvent.EVENT_MATERIAL_EXPIRING,
        extra_data__material_code='TEST_CUP_PERMANENT_01'
    )
    assert cup_alerts.count() == 0
    print("  ✓ Celery 保质期预警扫描已确认：永久有效物料（纸杯）0 误报警，安全正常！")

    print("\n🎉 永久有效物料（纸杯/耗材）免填保质期与防误报机制 100% 验证通过！")


if __name__ == '__main__':
    test_permanent_materials()
