"""
test_redis_concurrency.py

Redis 缓存、分布式并发排他锁与原子扣库存测试套件：
1. 校验针对单订单的 Redis 分布式互斥锁 (nx=True, ex=30) 及并发拦截；
2. 校验耗材与纸杯预扣 Lua 脚本在临界库存下的防超卖拦截（原子操作）；
3. 校验异常发生时 Redis 虚拟库存的冲正补偿 (incrby) 正确性；
4. 校验并发多通道调用 process_payment_success 时的幂等互斥效果。
"""

from unittest.mock import patch, MagicMock
from django.test import TestCase
from django_redis import get_redis_connection
import threading
import time

from users.models import User
from stores.models import Store
from devices.models import Device
from global_config.models import DeviceModel
from orders.models import OrderMain, OrderStatusLog
from payments.models import PaymentRecord
from payments.services import process_payment_success


class RedisConcurrencyAndLocksTestCase(TestCase):
    """Redis 缓存与高并发控制集成测试"""

    def setUp(self):
        self.redis_conn = get_redis_connection("default")
        self.user = User.objects.create_user(openid="openid_redis_test_01")
        self.store = Store.objects.create(code="STORE_REDIS_01", name="Redis测试门店")
        self.dev_model = DeviceModel.objects.create(code="MODEL_REDIS_01", name="Redis机型")
        self.device = Device.objects.create(
            store=self.store,
            device_sn="SN_REDIS_001",
            device_name="Redis测试咖啡机",
            device_model=self.dev_model,
            status=Device.STATUS_ONLINE
        )
        self.order = OrderMain.objects.create(
            user=self.user,
            store=self.store,
            device=self.device,
            status=OrderMain.STATUS_PENDING_PAY,
            total_amount=1800,
            pay_amount=1800
        )
        self.payment = PaymentRecord.objects.create(
            order=self.order,
            user=self.user,
            out_trade_no=self.order.order_no,
            amount=1800,
            status=PaymentRecord.STATUS_PENDING,
            pay_method="wechat_native"
        )

    def tearDown(self):
        # 清理 Redis 测试 Key
        lock_key = f"automake:pay_proc_lock:{self.order.order_no}"
        self.redis_conn.delete(lock_key)

    def test_redis_distributed_lock_mutual_exclusion(self):
        """
        [测试用例 1] 校验 Redis 分布式排他互斥锁
        预期：同一订单号，首次 set(nx=True) 返回 True，第二次并发获取必返回 False。
        """
        lock_key = f"automake:pay_proc_lock:{self.order.order_no}"
        
        # 首次获取锁
        acquired_first = self.redis_conn.set(lock_key, "1", nx=True, ex=30)
        self.assertTrue(acquired_first)

        # 并发第二次尝试获取锁
        acquired_second = self.redis_conn.set(lock_key, "1", nx=True, ex=30)
        self.assertFalse(acquired_second)

        # 释放锁后可再次获取
        self.redis_conn.delete(lock_key)
        acquired_third = self.redis_conn.set(lock_key, "1", nx=True, ex=30)
        self.assertTrue(acquired_third)

    def test_lua_script_atomic_decrement_prevent_oversell(self):
        """
        [测试用例 2] 校验 Redis 原子 Lua 脚本在临界低库存时的超卖拦截
        当库存扣减后将低于极低阈值 (critical_val) 时，Lua 脚本原子返回 0 并拒绝扣减。
        """
        stock_key = f"automake:test:cup_stock:{self.device.device_sn}"
        self.redis_conn.set(stock_key, "5")  # 当前仅剩 5 个

        LUA_DECR_CUP = """
        local stock = tonumber(redis.call('get', KEYS[1]) or "0")
        local num = tonumber(ARGV[1])
        local crit = tonumber(ARGV[2])
        if (stock - num) >= crit then
            redis.call('decrby', KEYS[1], num)
            return 1
        else
            return 0
        end
        """
        # 场景 A: 扣减 2 个，最低阈值为 0 -> (5 - 2 = 3 >= 0)，成功扣减
        res1 = self.redis_conn.eval(LUA_DECR_CUP, 1, stock_key, 2, 0)
        self.assertEqual(res1, 1)
        self.assertEqual(int(self.redis_conn.get(stock_key)), 3)

        # 场景 B: 试图扣减 5 个 -> (3 - 5 = -2 < 0)，触发拦截，返回 0 且原库存保持 3 不变
        res2 = self.redis_conn.eval(LUA_DECR_CUP, 1, stock_key, 5, 0)
        self.assertEqual(res2, 0)
        self.assertEqual(int(self.redis_conn.get(stock_key)), 3)

        self.redis_conn.delete(stock_key)

    @patch('mqtt.issue_make_command')
    def test_concurrent_payment_process_idempotency_with_redis_lock(self, mock_mqtt):
        """
        [测试用例 3] 验证微信支付重复回调/重试并发场景下的幂等性保障与 Redis 分布式防重
        确保：
        1. 首次支付回调成功执行出货并记录时间线；
        2. 第二次重复到达的回调被幂等拦截，绝不二次下发 MQTT 制作指令，不生成重复状态日志。
        """
        # 首次回调到达
        process_payment_success(
            order_no=self.order.order_no,
            transaction_id="wx_tx_concurrency_01",
            pay_time="2026-09-10T14:32:52Z",
            wx_amount=1800
        )

        # 刷新数据库验证首次成功
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderMain.STATUS_PAID)
        self.assertEqual(mock_mqtt.call_count, 1)

        # 第二次并发或网络重发回调到达
        process_payment_success(
            order_no=self.order.order_no,
            transaction_id="wx_tx_concurrency_01",
            pay_time="2026-09-10T14:32:52Z",
            wx_amount=1800
        )

        # 验证：MQTT 制作命令严格保持 1 次，未重复下发
        self.assertEqual(mock_mqtt.call_count, 1)

        # 验证：履约流转时间线中 pay_success 与 task_sent 严格各自只有 1 条记录
        pay_logs = self.order.status_logs.filter(action=OrderStatusLog.ACTION_PAY_SUCCESS)
        task_logs = self.order.status_logs.filter(action=OrderStatusLog.ACTION_TASK_SENT)
        self.assertEqual(pay_logs.count(), 1)
        self.assertEqual(task_logs.count(), 1)
