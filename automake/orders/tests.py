from django.test import TestCase
from django.utils import timezone
from decimal import Decimal
from unittest.mock import patch, MagicMock

from stores.models import Store
from devices.models import Device, DeviceMaterialStock
from global_config.models import DeviceModel, GlobalMenuCategory, GlobalMenuItem, GlobalMenuSku, GlobalSkuIngredient
from menus.models import MenuItem, MenuSku
from users.models import User
from orders.models import OrderMain, OrderItem, ProductionTask, OrderStatusLog
from orders.services import precheck_order, create_order, process_dispense_failure, reconcile_device_orders, get_redis_stock_key, update_order_status
from payments.services import process_payment_success, PaymentRecord


@patch('django_redis.get_redis_connection')
class OptimizedOrderProcessTests(TestCase):
    def setUp(self):
        # 1. 基础数据准备
        self.user = User.objects.create_user(openid='openid-test-user')
        self.store = Store.objects.create(
            name="测试门店",
            status=Store.STATUS_OPEN,
            code="STORE-CODE-1"
        )
        self.dev_type = DeviceModel.objects.create(name="咖啡机", code="coffee_maker")
        
        self.device = Device.objects.create(
            store=self.store,
            device_sn="SN-TEST-100",
            device_name="测试咖啡机",
            device_model=self.dev_type,
            key_code="STORE-CODE-1",
            status=Device.STATUS_ONLINE
        )

        # 2. 全局物料与菜单定义
        from inventory.models import Material
        self.inv_bean = Material.objects.create(name="咖啡豆", code="coffee_bean", unit="g")
        self.inv_milk = Material.objects.create(name="鲜牛奶", code="fresh_milk", unit="ml")
        self.inv_cup = Material.objects.create(name="大纸杯", code="paperL", unit="个", material_type=Material.TYPE_CONSUMABLE)

        self.category = GlobalMenuCategory.objects.create(
            device_model=self.dev_type, name="咖啡", sort_order=1, is_active=True
        )
        self.g_item = GlobalMenuItem.objects.create(
            category=self.category, name="拿铁", base_price=1500, is_active=True
        )

        # 3. 规格与配方用量
        self.g_sku = GlobalMenuSku.objects.create(
            item=self.g_item, name="大杯/热", price_delta=300, is_active=True
        )
        GlobalSkuIngredient.objects.create(sku=self.g_sku, material=self.inv_bean, quantity=15)
        GlobalSkuIngredient.objects.create(sku=self.g_sku, material=self.inv_milk, quantity=150)
        GlobalSkuIngredient.objects.create(sku=self.g_sku, material=self.inv_cup, quantity=1)

        # 4. 同步门店菜单
        MenuItem.sync_store_menu(self.store)
        self.menu_item = MenuItem.objects.get(store=self.store, global_item=self.g_item)
        self.menu_sku = MenuSku.objects.get(item=self.menu_item, global_sku=self.g_sku)

        # 5. 设备物理库存 (DB_Book_Stock)
        self.db_bean_stock = DeviceMaterialStock.objects.create(
            device=self.device, name=self.inv_bean, code="coffee_bean", initHight=100
        )
        self.db_milk_stock = DeviceMaterialStock.objects.create(
            device=self.device, name=self.inv_milk, code="fresh_milk", initHight=1000
        )
        self.db_cup_stock = DeviceMaterialStock.objects.create(
            device=self.device, name=self.inv_cup, code="paperL", initHight=500
        )

    def test_precheck_order_success(self, mock_get_redis):
        # Mock Redis available stock
        mock_redis_client = MagicMock()
        mock_redis_client.get.side_effect = lambda key: b"5000" if "coffee_bean" in key else b"50000"
        mock_get_redis.return_value = mock_redis_client

        items_data = [
            {
                'item': self.menu_item.id,
                'sku': [self.menu_sku.id],
                'quantity': 2
            }
        ]

        # 预校验应当通过，并返回价格和设备绑定
        result = precheck_order(self.store.id, items_data)
        self.assertTrue(result['ok'])
        self.assertEqual(result['total_amount'], 3600)  # (1500 + 300) * 2 = 3600
        self.assertEqual(result['device'], self.device)
        self.assertEqual(result['required_materials']['coffee_bean'], Decimal('30.00'))
        self.assertEqual(result['required_materials']['fresh_milk'], Decimal('300.00'))

    def test_precheck_order_insufficient_stock(self, mock_get_redis):
        # Mock Redis stock to be 0
        mock_redis_client = MagicMock()
        mock_redis_client.get.return_value = b"0"
        mock_get_redis.return_value = mock_redis_client

        items_data = [
            {
                'item': self.menu_item.id,
                'sku': [self.menu_sku.id],
                'quantity': 1
            }
        ]

        # 预校验应当因为库存不足而失败
        with self.assertRaises(ValueError) as ctx:
            precheck_order(self.store.id, items_data)
        self.assertIn("原料不足", str(ctx.exception))

    def test_create_order_pending_pay(self, mock_get_redis):
        mock_redis_client = MagicMock()
        mock_redis_client.get.side_effect = lambda key: b"5000" if "coffee_bean" in key else b"50000"
        mock_get_redis.return_value = mock_redis_client

        items_data = [
            {
                'item': self.menu_item.id,
                'sku': [self.menu_sku.id],
                'quantity': 1
            }
        ]

        order = create_order(self.user, self.store.id, items_data, remark="多放冰")
        self.assertEqual(order.status, OrderMain.STATUS_PENDING_PAY)  # 'created'
        self.assertEqual(order.pay_amount, 1800)
        self.assertEqual(order.device, self.device)
        
        # 验证 OrderItem 明细和 ManyToMany 关联
        oi = order.items.first()
        self.assertEqual(oi.item, self.menu_item)
        self.assertIn(self.menu_sku, oi.skus.all())

    @patch('mqtt.issue_make_command')
    def test_process_payment_success_flow(self, mock_issue_make, mock_get_redis):
        # Mock Redis precheck success
        mock_redis_client = MagicMock()
        mock_redis_client.get.side_effect = lambda key: b"5000" if "coffee_bean" in key else b"50000"
        mock_redis_client.register_script.return_value = MagicMock(return_value=1)  # 扣减成功
        mock_get_redis.return_value = mock_redis_client

        items_data = [
            {
                'item': self.menu_item.id,
                'sku': [self.menu_sku.id],
                'quantity': 1
            }
        ]
        # 创建待支付订单
        order = create_order(self.user, self.store.id, items_data)
        payment = PaymentRecord.objects.create(
            order=order, user=self.user, out_trade_no=order.order_no, amount=order.pay_amount
        )

        # 支付成功
        process_payment_success(order.order_no, "WX-TX-9999", timezone.now().isoformat(), order.pay_amount)

        # 验证订单状态和 DB 乐观扣减库存
        order.refresh_from_db()
        self.assertEqual(order.status, OrderMain.STATUS_PAID)  # 'pending_dispense'
        self.assertIsNotNone(order.order_token)



        # 验证生产任务下发
        self.assertTrue(ProductionTask.objects.filter(order=order).exists())
        mock_issue_make.assert_called_once()



    def test_explicit_failure_rollback(self, mock_get_redis):
        mock_redis_client = MagicMock()
        mock_redis_client.get.side_effect = lambda key: b"5000" if "coffee_bean" in key else b"50000"
        mock_get_redis.return_value = mock_redis_client

        items_data = [
            {
                'item': self.menu_item.id,
                'sku': [self.menu_sku.id],
                'quantity': 1
            }
        ]
        order = create_order(self.user, self.store.id, items_data)
        order.status = OrderMain.STATUS_PAID
        order.save()

        # 上位机明确出库失败，进行回滚
        process_dispense_failure(order, operator='device:SN-TEST-100', remark='吐杯杯口卡死')

        # 订单应失败，且 DB 库存和 Redis 虚拟库存应当加回补偿
        order.refresh_from_db()
        self.assertEqual(order.status, OrderMain.STATUS_EXCEPTION)  # 'failed'



        mock_redis_client.incrby.assert_any_call(get_redis_stock_key(self.device.device_sn, "coffee_bean"), 1500)

    def test_reconciliation_lost_command_rollback(self, mock_get_redis):
        mock_redis_client = MagicMock()
        mock_redis_client.get.side_effect = lambda key: b"5000" if "coffee_bean" in key else b"50000"
        mock_get_redis.return_value = mock_redis_client

        items_data = [
            {
                'item': self.menu_item.id,
                'sku': [self.menu_sku.id],
                'quantity': 1
            }
        ]
        order = create_order(self.user, self.store.id, items_data)
        order.status = OrderMain.STATUS_PAID  # pending_dispense
        order.order_token = "uuid-reconcile-1"
        order.save()

        # 设备重连对账：设备报告没有此订单的 token 记录（指令丢失）
        # 结果应：触发冲正，订单失败，库存退回
        res = reconcile_device_orders(self.device.device_sn, [])
        self.assertEqual(res['reconciled_count'], 1)
        self.assertEqual(res['details'][0]['action'], 'rollback_unexecuted')

        order.refresh_from_db()
        self.assertEqual(order.status, OrderMain.STATUS_EXCEPTION)

    def test_reconciliation_executed_confirm_success(self, mock_get_redis):
        mock_redis_client = MagicMock()
        mock_redis_client.get.side_effect = lambda key: b"5000" if "coffee_bean" in key else b"50000"
        mock_get_redis.return_value = mock_redis_client

        items_data = [
            {
                'item': self.menu_item.id,
                'sku': [self.menu_sku.id],
                'quantity': 1
            }
        ]
        order = create_order(self.user, self.store.id, items_data)
        order.status = OrderMain.STATUS_PAID  # pending_dispense
        order.order_token = "uuid-reconcile-2"
        order.save()

        # 对账时设备携带已执行 token 并报告成功
        res = reconcile_device_orders(self.device.device_sn, [{'order_token': 'uuid-reconcile-2', 'status': 'success'}])
        self.assertEqual(res['reconciled_count'], 1)
        self.assertEqual(res['details'][0]['action'], 'confirm_success')

        order.refresh_from_db()
        self.assertEqual(order.status, OrderMain.STATUS_DONE)

    def test_consumable_stock_deduction_and_alert(self, mock_get_redis):
        # 1. 模拟 Redis 客户端
        mock_redis_client = MagicMock()
        mock_redis_client.get.side_effect = lambda key: b"5000" if "coffee_bean" in key else b"50000"
        mock_redis_client.set.return_value = True
        mock_get_redis.return_value = mock_redis_client

        # 2. 预先创建 DeviceConsumableStock 记录
        from devices.models import DeviceConsumableStock
        from inventory.models import Material
        
        m_cup = self.inv_cup
        m_lid = Material.objects.create(
            name="杯盖",
            code="lid",
            material_type=Material.TYPE_CONSUMABLE,
            unit="个",
            shelf_life="永久",
            storage_conditions="常温"
        )
        GlobalSkuIngredient.objects.create(sku=self.g_sku, material=m_lid, quantity=1)

        paper_cup_stock = DeviceConsumableStock.objects.create(
            device=self.device,
            code=m_cup,
            quantity=21,  # 比预警值 20 多 1
            init_quantity=100,
            unit="个",
            warn_level=20
        )
        lid_stock = DeviceConsumableStock.objects.create(
            device=self.device,
            code=m_lid,
            quantity=50,
            init_quantity=100,
            unit="个",
            warn_level=20
        )

        # 3. 创建订单（大杯热拿铁，使用 paperL 和 lid）
        items_data = [
            {
                'item': self.menu_item.id,
                'sku': [self.menu_sku.id],
                'quantity': 2
            }
        ]
        order = create_order(self.user, self.store.id, items_data)
        
        # 4. 更新订单状态为已完成，触发耗材扣减与报警检查
        update_order_status(order, OrderMain.STATUS_DONE)

        # 5. 校验数据库中的耗材库存是否正确扣减
        paper_cup_stock.refresh_from_db()
        lid_stock.refresh_from_db()
        self.assertEqual(paper_cup_stock.quantity, 19)  # 21 - 2 = 19 (低于 warn_level，触发预警)
        self.assertEqual(lid_stock.quantity, 48)       # 50 - 2 = 48 (高于 warn_level，不触发预警)

        # 6. 校验 Redis 防抖标志及短信是否被触发
        any_sms_set_call = False
        for call in mock_redis_client.set.call_args_list:
            args, kwargs = call
            if args and ("sms_sent" in args[0] or b"sms_sent" in args[0].encode()):
                if "paperL" in args[0]:
                    any_sms_set_call = True
        self.assertTrue(any_sms_set_call, "应该向物料员发送纸杯的短信预警（设置了 Redis sms_sent 防抖锁）")

