import os
import sys
from datetime import timedelta

# 设置 Django 环境
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')
import django
django.setup()

from django.utils import timezone
from users.models import User
from stores.models import Store
from devices.models import Device
from orders.models import OrderMain
from notifications.models import PickupCode
from notifications.services import create_pickup_code, verify_pickup_code
from django_redis import get_redis_connection

def test_pickup_code_device_and_date_uniqueness():
    print("🚀 开始验证取餐码规则：【设备编号、取餐码、当天】唯一...")
    r = get_redis_connection('default')
    today = timezone.localdate()
    today_str = today.strftime('%Y%m%d')

    user = User.objects.first() or User.objects.create(username='test_user_pk')
    store = Store.objects.first() or Store.objects.create(name='测试门店', code='STORE_PK')
    
    dev_a, _ = Device.objects.get_or_create(device_sn='SN_TEST_A', defaults={'store': store})
    dev_b, _ = Device.objects.get_or_create(device_sn='SN_TEST_B', defaults={'store': store})

    # 清理该测试设备今天的相关 Redis 键和数据
    r.delete(f"automake:pickup_seq:{dev_a.device_sn}:{today_str}")
    r.delete(f"automake:pickup_seq:{dev_b.device_sn}:{today_str}")
    PickupCode.objects.filter(order__device__in=[dev_a, dev_b]).delete()

    # ----------------------------------------------------
    # Case 1: 验证跨日归零（昨天已有 0001，今天该设备仍从 0001 开始）
    # ----------------------------------------------------
    print("\n[Case 1] 验证跨日期归零发号能力...")
    ord_yesterday = OrderMain.objects.create(
        user=user, store=store, device=dev_a,
        total_amount=1000, pay_amount=1000, status=OrderMain.STATUS_PAID,
        paid_at=timezone.now() - timedelta(days=1)
    )
    # 模拟昨天的取餐码 0001
    pk_y = PickupCode.objects.create(
        order=ord_yesterday,
        code='0001',
        expires_at=timezone.now() - timedelta(hours=10),
        status=PickupCode.STATUS_EXPIRED
    )
    local_now = timezone.localtime(timezone.now())
    yesterday_dt = local_now - timedelta(days=1)
    PickupCode.objects.filter(id=pk_y.id).update(created_at=yesterday_dt)

    # 今天设备 A 的第一笔订单
    ord_a_1 = OrderMain.objects.create(
        user=user, store=store, device=dev_a,
        total_amount=1000, pay_amount=1000, status=OrderMain.STATUS_PAID,
        paid_at=timezone.now()
    )
    pk_a_1 = create_pickup_code(ord_a_1)
    print(f"  ✓ 昨天已有 0001，设备 A 今天首单取餐码: {pk_a_1.code}")
    assert pk_a_1.code == '0001', f"设备 A 今天首单应为 0001，实际为 {pk_a_1.code}"

    # ----------------------------------------------------
    # Case 2: 验证不同设备之间允许存在相同取餐码（设备间独立发号）
    # ----------------------------------------------------
    print("\n[Case 2] 验证不同设备间独立从 0001 发号...")
    ord_b_1 = OrderMain.objects.create(
        user=user, store=store, device=dev_b,
        total_amount=1000, pay_amount=1000, status=OrderMain.STATUS_PAID,
        paid_at=timezone.now()
    )
    pk_b_1 = create_pickup_code(ord_b_1)
    print(f"  ✓ 设备 B 今天首单取餐码: {pk_b_1.code}")
    assert pk_b_1.code == '0001', f"设备 B 今天首单应为 0001，实际为 {pk_b_1.code}"
    print(f"  ✓ 验证成功: 设备 A ({dev_a.device_sn}) 与设备 B ({dev_b.device_sn}) 同日各自生成 0001，互不排斥！")

    # ----------------------------------------------------
    # Case 3: 验证同一设备同天内顺序递增 (0002, 0003)
    # ----------------------------------------------------
    print("\n[Case 3] 验证同一设备内同天顺序递增...")
    ord_a_2 = OrderMain.objects.create(
        user=user, store=store, device=dev_a,
        total_amount=1000, pay_amount=1000, status=OrderMain.STATUS_PAID,
        paid_at=timezone.now()
    )
    pk_a_2 = create_pickup_code(ord_a_2)
    print(f"  ✓ 设备 A 第二单取餐码: {pk_a_2.code}")
    assert pk_a_2.code == '0002', f"设备 A 第二单应为 0002，实际为 {pk_a_2.code}"

    ord_a_3 = OrderMain.objects.create(
        user=user, store=store, device=dev_a,
        total_amount=1000, pay_amount=1000, status=OrderMain.STATUS_PAID,
        paid_at=timezone.now()
    )
    pk_a_3 = create_pickup_code(ord_a_3)
    print(f"  ✓ 设备 A 第三单取餐码: {pk_a_3.code}")
    assert pk_a_3.code == '0003', f"设备 A 第三单应为 0003，实际为 {pk_a_3.code}"

    # ----------------------------------------------------
    # Case 4: 验证核销时的设备与当天日期隔离性
    # ----------------------------------------------------
    print("\n[Case 4] 验证核销时的隔离性（设备 A 和 设备 B 都有 0001）...")
    # 在设备 A 上核销 0001
    res_a = verify_pickup_code(code='0001', device_sn=dev_a.device_sn)
    assert res_a['ok'] is True, f"设备 A 核销 0001 应成功: {res_a}"
    assert res_a['order_no'] == ord_a_1.order_no, "设备 A 应核销设备 A 的订单"
    print(f"  ✓ 设备 A 成功核销了自己的 0001 (订单: {res_a['order_no']})")

    # 设备 B 的 0001 应依然有效（未被误核销）
    pk_b_reload = PickupCode.objects.get(id=pk_b_1.id)
    assert pk_b_reload.status == PickupCode.STATUS_ACTIVE, "设备 B 的 0001 不应被设备 A 影响"
    print("  ✓ 确认设备 B 的 0001 依然处于有效待取状态，未被误核销！")

    # 在设备 B 上核销 0001
    res_b = verify_pickup_code(code='0001', device_sn=dev_b.device_sn)
    assert res_b['ok'] is True, f"设备 B 核销 0001 应成功: {res_b}"
    assert res_b['order_no'] == ord_b_1.order_no, "设备 B 应核销设备 B 的订单"
    print(f"  ✓ 设备 B 成功核销了自己的 0001 (订单: {res_b['order_no']})")

    print("\n==================================================================")
    print("🎉 全部测试用例 100% 通过！出餐码（设备编号、取餐码、当天）唯一逻辑验证成功！")
    print("==================================================================")

if __name__ == '__main__':
    test_pickup_code_device_and_date_uniqueness()
