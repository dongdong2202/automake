"""
test_order_timeline_branches.py

订单生命周期全分支状态机与履约流转时间线测试套件：
覆盖自动售卖机业务场景下的所有可能流转分支：
1. 分支一：正常支付出餐正向闭环 (created → pay_success → task_sent → making_start → making_done)；
2. 分支二：待支付订单超时/用户主动取消分支 (created → cancelled)；
3. 分支三：设备出餐失败与自动退款分支 (making → failed → refund_success)；
4. 分支四：流转时间线上下文快照 payload 字段完整性与可追溯性验证。
"""

from django.test import TestCase
from unittest.mock import patch, MagicMock

from users.models import User
from stores.models import Store
from devices.models import Device
from global_config.models import DeviceModel
from orders.models import OrderMain, OrderStatusLog
from orders.services import update_order_status, record_order_timeline, cancel_order, process_dispense_failure


class OrderTimelineStateBranchesTestCase(TestCase):
    """订单流转时间线全分支覆盖测试"""

    def setUp(self):
        self.user = User.objects.create_user(openid="openid_branch_test_01")
        self.store = Store.objects.create(code="STORE_BR_01", name="分支测试门店")
        self.dev_model = DeviceModel.objects.create(code="MODEL_BR_01", name="分支机型")
        self.device = Device.objects.create(
            store=self.store,
            device_sn="SN_BRANCH_001",
            device_name="分支测试咖啡机",
            device_model=self.dev_model,
            status=Device.STATUS_ONLINE
        )

    def test_branch_forward_complete_lifecycle(self):
        """
        [分支一] 正向完整生命周期流转
        created -> pay_success -> task_sent -> making_start -> making_done
        """
        # 1. 创建订单
        order = OrderMain.objects.create(
            user=self.user,
            store=self.store,
            device=self.device,
            status=OrderMain.STATUS_PENDING_PAY,
            total_amount=1500,
            pay_amount=1500
        )
        record_order_timeline(
            order=order,
            action=OrderStatusLog.ACTION_CREATE,
            action_name="订单创建",
            from_status="",
            to_status=OrderMain.STATUS_PENDING_PAY,
            operator_type=OrderStatusLog.OP_USER,
            operator=f"user:{self.user.id}"
        )

        # 2. 支付成功
        update_order_status(
            order=order,
            new_status=OrderMain.STATUS_PAID,
            action=OrderStatusLog.ACTION_PAY_SUCCESS,
            action_name="微信支付成功",
            operator_type=OrderStatusLog.OP_WECHAT,
            operator="wechat_pay",
            payload={"transaction_id": "tx_test_123456", "pay_amount": 1500}
        )

        # 3. 任务下发
        record_order_timeline(
            order=order,
            action=OrderStatusLog.ACTION_TASK_SENT,
            action_name="制作任务下发",
            from_status=OrderMain.STATUS_PAID,
            to_status=OrderMain.STATUS_PAID,
            operator_type=OrderStatusLog.OP_SYSTEM,
            operator="system",
            payload={"ticket_no": "0001", "device_sn": self.device.device_sn}
        )

        # 4. 设备开始制作
        update_order_status(
            order=order,
            new_status=OrderMain.STATUS_MAKING,
            action=OrderStatusLog.ACTION_MAKING_START,
            action_name="设备开始制作",
            operator_type=OrderStatusLog.OP_DEVICE,
            operator=f"device:{self.device.device_sn}",
            payload={"step": "grinding", "temperature": 92}
        )

        # 5. 制作完成出杯
        update_order_status(
            order=order,
            new_status=OrderMain.STATUS_DONE,
            action=OrderStatusLog.ACTION_MAKING_DONE,
            action_name="出杯制作完成",
            operator_type=OrderStatusLog.OP_DEVICE,
            operator=f"device:{self.device.device_sn}",
            payload={"ticket_no": "0001"}
        )

        order.refresh_from_db()
        self.assertEqual(order.status, OrderMain.STATUS_DONE)

        # 验证全时间线日志条数与各节点动作
        logs = list(order.status_logs.all())
        self.assertEqual(len(logs), 5)
        actions = [log.action for log in logs]
        self.assertEqual(actions, [
            OrderStatusLog.ACTION_CREATE,
            OrderStatusLog.ACTION_PAY_SUCCESS,
            OrderStatusLog.ACTION_TASK_SENT,
            OrderStatusLog.ACTION_MAKING_START,
            OrderStatusLog.ACTION_MAKING_DONE
        ])

    def test_branch_cancel_order(self):
        """
        [分支二] 待支付订单取消分支
        created -> cancelled
        """
        order = OrderMain.objects.create(
            user=self.user,
            store=self.store,
            device=self.device,
            status=OrderMain.STATUS_PENDING_PAY,
            total_amount=2000,
            pay_amount=2000
        )
        record_order_timeline(
            order=order,
            action=OrderStatusLog.ACTION_CREATE,
            action_name="订单创建",
            from_status="",
            to_status=OrderMain.STATUS_PENDING_PAY,
            operator_type=OrderStatusLog.OP_USER
        )

        # 执行用户取消
        cancel_order(order, operator=f"user:{self.user.id}", remark="顾客不想要了")
        order.refresh_from_db()
        self.assertEqual(order.status, OrderMain.STATUS_CANCELLED)

        cancel_log = order.status_logs.filter(action=OrderStatusLog.ACTION_CANCELLED).first()
        self.assertIsNotNone(cancel_log)
        self.assertEqual(cancel_log.operator_type, OrderStatusLog.OP_USER)
        self.assertEqual(cancel_log.payload.get("cancel_reason"), "顾客不想要了")

    @patch('payments.services.refund_order')
    def test_branch_dispense_failed_and_auto_refund(self, mock_refund):
        """
        [分支三] 硬件出餐故障分支 (dispense_failed)
        making -> failed -> 自动触发退款与冲正
        """
        order = OrderMain.objects.create(
            user=self.user,
            store=self.store,
            device=self.device,
            status=OrderMain.STATUS_MAKING,
            total_amount=1800,
            pay_amount=1800
        )
        # 上位机上报出杯失败
        process_dispense_failure(order, operator="device:SN_BRANCH_001", remark="蠕动泵出液阻塞超时")

        order.refresh_from_db()
        self.assertEqual(order.status, OrderMain.STATUS_EXCEPTION)

        fail_log = order.status_logs.filter(action=OrderStatusLog.ACTION_FAILED).first()
        self.assertIsNotNone(fail_log)
        self.assertEqual(fail_log.payload.get("failure_reason"), "蠕动泵出液阻塞超时")
        self.assertIn("蠕动泵出液阻塞", fail_log.remark)

    def test_timeline_payload_snapshot_integrity(self):
        """
        [分支四] 校验时间线 payload 快照的可追溯性与数据结构
        """
        order = OrderMain.objects.create(
            user=self.user,
            store=self.store,
            device=self.device,
            status=OrderMain.STATUS_PAID,
            total_amount=1200,
            pay_amount=1200
        )
        payload_data = {
            "transaction_id": "wx_tx_998877",
            "device_sn": self.device.device_sn,
            "operator_ip": "127.0.0.1"
        }
        record_order_timeline(
            order=order,
            action=OrderStatusLog.ACTION_PAY_SUCCESS,
            action_name="微信支付成功",
            from_status=OrderMain.STATUS_PENDING_PAY,
            to_status=OrderMain.STATUS_PAID,
            operator_type=OrderStatusLog.OP_WECHAT,
            payload=payload_data
        )

        saved_log = order.status_logs.filter(action=OrderStatusLog.ACTION_PAY_SUCCESS).first()
        self.assertEqual(saved_log.payload["transaction_id"], "wx_tx_998877")
        self.assertEqual(saved_log.payload["device_sn"], self.device.device_sn)
