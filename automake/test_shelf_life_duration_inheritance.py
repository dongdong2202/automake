"""
验证物料继承的是保质期时长 (Duration Days) 而非死日期专项测试
例如：新建时设定 2027-08-23 过期 (时长 365 天)，则 3 天后 (2026-08-26) 入库的自动继承为 2027-08-26 过期！
"""

import os
import django
import datetime
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')
django.setup()

from django.utils import timezone
from inventory.models import Material, InventoryRecord, parse_shelf_life_duration_days, calculate_default_expiration_date
from admin_api.serializers import MaterialSerializer


def test_duration_logic():
    print("🚀 开始验证物料保质期时长（Duration）继承核心逻辑...")

    today = timezone.now().date()
    # 模拟新建物料时选择 365 天后的日期
    target_date_str = str(today + datetime.timedelta(days=365))

    # 1. 验证时长解析
    days = parse_shelf_life_duration_days(target_date_str, reference_date=today)
    print(f"  ✓ 日期字符串 '{target_date_str}' 基于创建日 {today} 解析为有效保质期时长: {days} 天")
    assert days == 365

    # 2. 创建测试物料
    mat, _ = Material.objects.get_or_create(
        code='TEST_DURATION_MAT_01',
        defaults={
            'name': '保质期时长测试物料',
            'material_type': Material.TYPE_INGREDIENT,
            'price': Decimal('50.00'),
            'quantity': Decimal('10.00'),
            'unit': '包',
            'shelf_life': target_date_str,
            'storage_conditions': '常温'
        }
    )
    mat.shelf_life = target_date_str
    mat.save()

    # 3. 验证 Serializer 序列化输出
    s_data = MaterialSerializer(mat).data
    print(f"  ✓ Serializer 输出: shelf_life_days={s_data['shelf_life_days']}, default_expiration_date={s_data['default_expiration_date']}")
    assert s_data['shelf_life_days'] == 365

    # 4. 模拟今日 (Day 0) 入库计算
    exp_today = calculate_default_expiration_date(mat, base_date=today)
    print(f"  ✓ 今日 ({today}) 初始入库批次过期日: {exp_today}")
    assert exp_today == today + datetime.timedelta(days=365)

    # 5. 模拟 3 天后 (Day 3, 2026-08-26) 进货入库计算
    day_3 = today + datetime.timedelta(days=3)
    exp_day_3 = calculate_default_expiration_date(mat, base_date=day_3)
    print(f"  ✓ 3 天后 ({day_3}) 新入库批次自动继承保质期时长计算出的过期日: {exp_day_3}")
    assert exp_day_3 == day_3 + datetime.timedelta(days=365)
    assert exp_day_3 == exp_today + datetime.timedelta(days=3)

    # 6. 模拟 30 天后 (Day 30) 进货入库计算
    day_30 = today + datetime.timedelta(days=30)
    exp_day_30 = calculate_default_expiration_date(mat, base_date=day_30)
    print(f"  ✓ 30 天后 ({day_30}) 新入库批次过期日: {exp_day_30}")
    assert exp_day_30 == day_30 + datetime.timedelta(days=365)

    print("\n🎉 物料保质期时长继承核心业务逻辑 100% 验证通过！")


if __name__ == '__main__':
    test_duration_logic()
