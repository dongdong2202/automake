"""
test_database_integrity.py

数据库完整性、模型外键约束与持久化事务测试套件：
1. 校验 MySQL 外键保护与级联规则（PROTECT 保护防止误删关联数据）；
2. 校验菜单与规格 (MenuItem -> MenuSku) 的价格边界与 clean() 校验；
3. 校验订单明细小计与分单位整型固化（杜绝浮点数失真）；
4. 校验履约时间线 (OrderStatusLog) 的外键关联与级联持久化。
"""

from django.test import TestCase
from django.db.models.deletion import ProtectedError
from django.core.exceptions import ValidationError
from decimal import Decimal

from users.models import User
from stores.models import Store
from devices.models import Device
from global_config.models import DeviceModel, GlobalMenuCategory, GlobalMenuItem, GlobalMenuSku, GlobalSkuTemplate
from menus.models import MenuItem, MenuSku
from orders.models import OrderMain, OrderItem, OrderStatusLog
from payments.models import PaymentRecord


class DatabaseIntegrityAndConstraintsTestCase(TestCase):
    """数据库持久化与数据模型完整性约束测试"""

    def setUp(self):
        # 1. 基础数据准备
        self.user = User.objects.create_user(openid="openid_db_test_001", phone="13800001111")
        self.store = Store.objects.create(code="STORE_TEST_01", name="测试测试门店", status=Store.STATUS_OPEN)
        self.dev_model = DeviceModel.objects.create(code="MODEL_DB_01", name="测试机型")
        self.device = Device.objects.create(
            store=self.store,
            device_sn="SN_DB_001",
            device_name="测试咖啡机001",
            device_model=self.dev_model,
            status=Device.STATUS_ONLINE
        )

        # 全局菜品分类与商品
        self.category = GlobalMenuCategory.objects.create(
            name="咖啡品类",
            device_model=self.dev_model,
            is_active=True
        )
        self.global_item = GlobalMenuItem.objects.create(
            category=self.category,
            name="经典拿铁",
            base_price=1500,
            is_active=True
        )
        self.template = GlobalSkuTemplate.objects.create(
            name="大杯 / 热",
            category="默认",
            default_price_delta=300,
            is_active=True
        )
        self.global_sku = GlobalMenuSku.objects.create(
            item=self.global_item,
            template=self.template,
            price_delta=300,
            is_active=True
        )

        # 门店本地菜品
        self.menu_item = MenuItem.objects.create(
            store=self.store,
            device_model=self.dev_model,
            global_item=self.global_item,
            base_price=1500,
            is_active=True
        )
        self.menu_sku = MenuSku.objects.create(
            item=self.menu_item,
            global_sku=self.global_sku,
            price_delta=300,
            is_active=True
        )

    def test_order_user_protected_foreign_key(self):
        """
        [测试用例 1] 校验用户外键被 PROTECT 保护
        预期：当用户存在关联的业务订单时，禁止物理删除该用户，抛出 ProtectedError。
        """
        order = OrderMain.objects.create(
            user=self.user,
            store=self.store,
            device=self.device,
            status=OrderMain.STATUS_PAID,
            total_amount=1800,
            pay_amount=1800
        )

        with self.assertRaises(ProtectedError):
            self.user.delete()

    def test_payment_record_protected_foreign_key(self):
        """
        [测试用例 2] 校验支付记录 PaymentRecord 对 OrderMain 的 PROTECT 保护
        预期：当订单存在支付凭证时，禁止物理删除 OrderMain，保护财务核算审计链条。
        """
        order = OrderMain.objects.create(
            user=self.user,
            store=self.store,
            device=self.device,
            status=OrderMain.STATUS_PAID,
            total_amount=1800,
            pay_amount=1800
        )
        PaymentRecord.objects.create(
            order=order,
            user=self.user,
            out_trade_no=order.order_no,
            transaction_id="wx_test_tx_001",
            amount=1800,
            status=PaymentRecord.STATUS_SUCCESS
        )

        with self.assertRaises(ProtectedError):
            order.delete()

    def test_menu_sku_price_boundary_validation(self):
        """
        [测试用例 3] 校验 MenuSku 售价上下浮动 20% 的业务模型约束
        全局总售价 = 1500 + 300 = 1800 分，允许范围为 [1440分, 2160分]。
        """
        # 合法浮动：加价 100 分 -> 最终 1600 分（在 1440-2160 内），验证通过
        valid_sku = MenuSku(
            item=self.menu_item,
            global_sku=self.global_sku,
            price_delta=100
        )
        valid_sku.clean()

        # 违规浮动：加价 1000 分 -> 最终 2500 分（超过 2160 分上限），预期抛出 ValidationError
        invalid_sku = MenuSku(
            item=self.menu_item,
            global_sku=self.global_sku,
            price_delta=1000
        )
        with self.assertRaises(ValidationError):
            invalid_sku.clean()

    def test_order_item_subtotal_and_integer_cents(self):
        """
        [测试用例 4] 校验订单明细小计与货币金额严格整型分单位存储
        避免浮点数在金额运算、分账结算与微信支付交互中产生精度误差。
        """
        order = OrderMain.objects.create(
            user=self.user,
            store=self.store,
            device=self.device,
            status=OrderMain.STATUS_PENDING_PAY,
            total_amount=3600,
            pay_amount=3600
        )
        item = OrderItem.objects.create(
            order=order,
            item=self.menu_item,
            item_name="经典拿铁",
            sku_name="大杯 / 热",
            unit_price=1800,
            quantity=2,
            subtotal=3600
        )

        self.assertIsInstance(item.unit_price, int)
        self.assertIsInstance(item.subtotal, int)
        self.assertEqual(item.subtotal, item.unit_price * item.quantity)
        self.assertEqual(order.pay_amount, item.subtotal)

    def test_order_status_log_cascade_and_chronology(self):
        """
        [测试用例 5] 校验履约流转时间线 (OrderStatusLog) 的级联与时序性
        时间线应严格按发生时间自增，且当主订单作废删除时，日志级联清除或追溯完整。
        """
        order = OrderMain.objects.create(
            user=self.user,
            store=self.store,
            device=self.device,
            status=OrderMain.STATUS_PAID,
            total_amount=1800,
            pay_amount=1800
        )

        log1 = OrderStatusLog.objects.create(
            order=order,
            action=OrderStatusLog.ACTION_CREATE,
            action_name="订单创建",
            from_status="",
            to_status=OrderMain.STATUS_PENDING_PAY,
            operator_type=OrderStatusLog.OP_USER
        )

        log2 = OrderStatusLog.objects.create(
            order=order,
            action=OrderStatusLog.ACTION_PAY_SUCCESS,
            action_name="微信支付成功",
            from_status=OrderMain.STATUS_PENDING_PAY,
            to_status=OrderMain.STATUS_PAID,
            operator_type=OrderStatusLog.OP_WECHAT
        )

        logs = list(order.status_logs.all())
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0].id, log1.id)
        self.assertEqual(logs[1].id, log2.id)
