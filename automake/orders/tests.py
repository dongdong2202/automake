from django.test import TestCase
from django.utils import timezone
from decimal import Decimal
from unittest.mock import patch, MagicMock

from stores.models import Store
from devices.models import Device, DeviceMaterialStock
from global_config.models import DeviceModel, GlobalMenuCategory, GlobalMenuItem, GlobalSkuTemplate, GlobalMenuSku, GlobalSkuIngredient
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
        self.inv_bean, _ = Material.objects.get_or_create(name="咖啡豆", code="coffee_bean", unit="g")
        self.inv_milk, _ = Material.objects.get_or_create(name="鲜牛奶", code="fresh_milk", unit="ml")
        self.inv_cup, _ = Material.objects.get_or_create(code="paperL", defaults={"name": "纸大杯", "unit": "个", "material_type": "cup"})

        self.category = GlobalMenuCategory.objects.create(
            device_model=self.dev_type, name="咖啡", sort_order=1, is_active=True
        )
        self.g_item = GlobalMenuItem.objects.create(
            category=self.category, name="拿铁", base_price=1500, is_active=True
        )

        # 3. 规格与配方用量
        self.g_tpl = GlobalSkuTemplate.objects.create(
            name="大杯/热", category="默认", default_price_delta=300, is_active=True
        )
        self.g_sku = GlobalMenuSku.objects.create(
            item=self.g_item, template=self.g_tpl, price_delta=300, is_active=True
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

        # 6. 设备耗材库存 (MySQL DeviceConsumableStock)
        from devices.models import DeviceConsumableStock
        for cup_code in ['paperL', 'paperM', 'plasticL', 'plasticM', 'membrane', 'lid']:
            mat, _ = Material.objects.get_or_create(code=cup_code, defaults={'name': cup_code, 'material_type': 'cup'})
            DeviceConsumableStock.objects.create(
                device=self.device,
                code=mat,
                init_quantity=100,
                quantity=100,
                warn_level=15
            )

    def test_precheck_order_success(self, mock_get_redis):
        # Mock Redis available stock
        mock_redis_client = MagicMock()
        mock_redis_client.get.side_effect = lambda key: b"5000" if "coffee_bean" in key else b"50000"
        mock_redis_client.mget.side_effect = lambda keys: [b"5000" if "coffee_bean" in k else b"50000" for k in keys]
        mock_get_redis.return_value = mock_redis_client

        items_data = [
            {
                'item': self.menu_item.id,
                'sku': [self.menu_sku.id],
                'quantity': 2
            }
        ]

        # 预校验应当通过，并返回价格和设备绑定
        result = precheck_order(self.store.id, items_data, device_sn=self.device.device_sn)
        self.assertTrue(result['ok'])
        self.assertEqual(result['total_amount'], 3600)  # (1500 + 300) * 2 = 3600
        self.assertEqual(result['device'], self.device)
        self.assertEqual(result['required_materials']['coffee_bean'], Decimal('30.00'))
        self.assertEqual(result['required_materials']['fresh_milk'], Decimal('300.00'))

    def test_precheck_order_missing_device_sn(self, mock_get_redis):
        items_data = [
            {
                'item': self.menu_item.id,
                'sku': [self.menu_sku.id],
                'quantity': 1
            }
        ]
        with self.assertRaises(ValueError) as ctx:
            precheck_order(self.store.id, items_data, device_sn='')
        self.assertIn("请传入点餐设备编号", str(ctx.exception))

    def test_precheck_order_nonexistent_device_sn(self, mock_get_redis):
        items_data = [
            {
                'item': self.menu_item.id,
                'sku': [self.menu_sku.id],
                'quantity': 1
            }
        ]
        with self.assertRaises(ValueError) as ctx:
            precheck_order(self.store.id, items_data, device_sn='NON_EXISTENT_SN')
        self.assertIn("指定的设备 NON_EXISTENT_SN 不存在", str(ctx.exception))

    def test_precheck_order_insufficient_stock(self, mock_get_redis):
        # Mock Redis stock to be 0
        mock_redis_client = MagicMock()
        mock_redis_client.get.return_value = b"0"
        mock_redis_client.mget.return_value = [b"0", b"0", b"0"]
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
            precheck_order(self.store.id, items_data, device_sn=self.device.device_sn)
        self.assertIn("原料不足", str(ctx.exception))

    def test_create_order_pending_pay(self, mock_get_redis):
        mock_redis_client = MagicMock()
        mock_redis_client.get.side_effect = lambda key: b"5000" if "coffee_bean" in key else b"50000"
        mock_redis_client.mget.side_effect = lambda keys: [b"5000" if "coffee_bean" in k else b"50000" for k in keys]
        mock_get_redis.return_value = mock_redis_client

        items_data = [
            {
                'item': self.menu_item.id,
                'sku': [self.menu_sku.id],
                'quantity': 1
            }
        ]

        order = create_order(self.user, self.store.id, items_data, remark="多放冰", device_sn=self.device.device_sn)
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
        mock_redis_client.mget.side_effect = lambda keys: [b"5000" if "coffee_bean" in k else b"50000" for k in keys]
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
        order = create_order(self.user, self.store.id, items_data, device_sn=self.device.device_sn)
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
        mock_redis_client.mget.side_effect = lambda keys: [b"5000" if "coffee_bean" in k else b"50000" for k in keys]
        mock_get_redis.return_value = mock_redis_client

        items_data = [
            {
                'item': self.menu_item.id,
                'sku': [self.menu_sku.id],
                'quantity': 1
            }
        ]
        order = create_order(self.user, self.store.id, items_data, device_sn=self.device.device_sn)
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
        mock_redis_client.mget.side_effect = lambda keys: [b"5000" if "coffee_bean" in k else b"50000" for k in keys]
        mock_get_redis.return_value = mock_redis_client

        items_data = [
            {
                'item': self.menu_item.id,
                'sku': [self.menu_sku.id],
                'quantity': 1
            }
        ]
        order = create_order(self.user, self.store.id, items_data, device_sn=self.device.device_sn)
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
        mock_redis_client.mget.side_effect = lambda keys: [b"5000" if "coffee_bean" in k else b"50000" for k in keys]
        mock_get_redis.return_value = mock_redis_client

        items_data = [
            {
                'item': self.menu_item.id,
                'sku': [self.menu_sku.id],
                'quantity': 1
            }
        ]
        order = create_order(self.user, self.store.id, items_data, device_sn=self.device.device_sn)
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
        mock_redis_client.mget.side_effect = lambda keys: [b"5000" if "coffee_bean" in k else b"50000" for k in keys]
        mock_redis_client.set.return_value = True
        mock_get_redis.return_value = mock_redis_client

        # 2. 预先创建 DeviceConsumableStock 记录
        from devices.models import DeviceConsumableStock
        from inventory.models import Material
        
        m_cup = self.inv_cup
        m_lid, _ = Material.objects.get_or_create(
            code="lid",
            defaults={
                "name": "盖",
                "material_type": "cup",
                "unit": "个",
                "shelf_life": "永久",
                "storage_conditions": "常温"
            }
        )
        GlobalSkuIngredient.objects.create(sku=self.g_sku, material=m_lid, quantity=1)

        paper_cup_stock, _ = DeviceConsumableStock.objects.update_or_create(
            device=self.device,
            code=m_cup,
            defaults={
                'quantity': 21,  # 比预警值 20 多 1
                'init_quantity': 100,
                'unit': "个",
                'warn_level': 20
            }
        )
        lid_stock, _ = DeviceConsumableStock.objects.update_or_create(
            device=self.device,
            code=m_lid,
            defaults={
                'quantity': 50,
                'init_quantity': 100,
                'unit': "个",
                'warn_level': 20
            }
        )

        # 3. 创建订单（大杯热拿铁，使用 paperL 和 lid）
        items_data = [
            {
                'item': self.menu_item.id,
                'sku': [self.menu_sku.id],
                'quantity': 2
            }
        ]
        order = create_order(self.user, self.store.id, items_data, device_sn=self.device.device_sn)
        
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

    def test_precheck_with_unproduced_in_flight_orders(self, mock_get_redis):
        """测试预校验扣除已支付但未制作完成的在途订单所占用的物料"""
        # 设备物理库存：咖啡豆 50g, 牛奶 300ml, 纸杯 5个
        mock_redis_client = MagicMock()
        def mock_get(key):
            if "coffee_bean" in key:
                return b"50"
            elif "fresh_milk" in key:
                return b"300"
            elif "paperL" in key:
                return b"5"
            return b"100"

        mock_redis_client.get.side_effect = mock_get
        mock_redis_client.mget.side_effect = lambda keys: [mock_get(k) for k in keys]
        mock_get_redis.return_value = mock_redis_client

        items_data_1 = [
            {
                'item': self.menu_item.id,
                'sku': [self.menu_sku.id],
                'quantity': 1  # 需求: 咖啡豆 15g, 牛奶 150ml, 纸杯 1个
            }
        ]

        # 1. 第1单预校验成功并创建，置为 pending_dispense（待制作在途）
        res1 = precheck_order(self.store.id, items_data_1, device_sn=self.device.device_sn)
        self.assertTrue(res1['ok'])
        order1 = create_order(self.user, self.store.id, items_data_1, device_sn=self.device.device_sn)
        order1.status = OrderMain.STATUS_PAID
        order1.save()

        # 2. 此时在途占用: 咖啡豆 15g, 牛奶 150ml。
        # 设备剩余有效可用: 咖啡豆 50 - 15 = 35g, 牛奶 300 - 150 = 150ml。
        # 尝试下第2单，需求量为 2 杯（需要 30g 咖啡豆, 300ml 牛奶）：牛奶需求 300ml > 有效可用 150ml，预校验应拒绝
        items_data_2 = [
            {
                'item': self.menu_item.id,
                'sku': [self.menu_sku.id],
                'quantity': 2
            }
        ]
        with self.assertRaises(ValueError) as ctx:
            precheck_order(self.store.id, items_data_2, device_sn=self.device.device_sn)
        self.assertIn("原料不足", str(ctx.exception))

        # 3. 当第1单制作完成出杯 (STATUS_DONE)，不再占用在途物料
        order1.status = OrderMain.STATUS_DONE
        order1.save()

        # 此时只下一杯（需要 15g 咖啡豆, 150ml 牛奶），有效可用为 300ml，预校验应成功通过
        res2 = precheck_order(self.store.id, items_data_1, device_sn=self.device.device_sn)
        self.assertTrue(res2['ok'])

    def test_sn005_barrel_and_recipe_material_precheck(self, mock_get_redis):
        """测试设备 sn005 料桶映射、配方多规格物料聚合计算与精准缺料拦截"""
        from devices.models import DeviceBarrelDict
        # 1. 配置 sn005 料桶字典映射
        DeviceBarrelDict.objects.get_or_create(
            device=self.device,
            barrel_code="b01",
            defaults={"material": self.inv_bean, "created_by": self.user}
        )
        DeviceBarrelDict.objects.get_or_create(
            device=self.device,
            barrel_code="b02",
            defaults={"material": self.inv_milk, "created_by": self.user}
        )

        # 2. 模拟 Redis 充裕库存
        mock_redis_client = MagicMock()
        stock_db = {
            get_redis_stock_key(self.device.device_sn, "coffee_bean"): b"5000",
            get_redis_stock_key(self.device.device_sn, "fresh_milk"): b"10000",
            get_redis_stock_key(self.device.device_sn, "paperL"): b"100",
            get_redis_stock_key(self.device.device_sn, "lid"): b"200",
            get_redis_stock_key(self.device.device_sn, "membrane"): b"200",
        }
        mock_redis_client.get.side_effect = lambda k: stock_db.get(k, b"0")
        mock_redis_client.mget.side_effect = lambda keys: [stock_db.get(k, b"0") for k in keys]
        mock_get_redis.return_value = mock_redis_client

        # 3. 预校验 3 杯拿铁 (需要 45g 咖啡豆, 450ml 牛奶, 3个大杯, 3个杯盖, 3张膜)
        items_data = [
            {
                'item': self.menu_item.id,
                'sku': [self.menu_sku.id],
                'quantity': 3
            }
        ]
        res = precheck_order(self.store.id, items_data, device_sn=self.device.device_sn)
        self.assertTrue(res['ok'])
        self.assertEqual(res['required_materials']['coffee_bean'], Decimal('45.00'))
        self.assertEqual(res['required_materials']['fresh_milk'], Decimal('450.00'))
        self.assertEqual(res['required_materials']['paperL'], Decimal('3.00'))
        self.assertEqual(res['required_materials']['lid'], Decimal('3.00'))
        self.assertEqual(res['required_materials']['membrane'], Decimal('3.00'))

        # 4. 模拟咖啡豆不足 (仅剩 20g < 45g)
        stock_db[get_redis_stock_key(self.device.device_sn, "coffee_bean")] = b"20"
        with self.assertRaises(ValueError) as ctx:
            precheck_order(self.store.id, items_data, device_sn=self.device.device_sn)
        self.assertIn("原料不足", str(ctx.exception))
        self.assertIn("20.0", str(ctx.exception))

    def test_calculate_required_materials_per_cup_and_auto_correction(self, mock_get_redis):
        """
        测试用料计算新特性：
        1. 塑料杯不能装热饮，自动纠正为纸杯；
        2. 纸杯成套配备杯盖 (lid)；
        3. 每杯饮品配备封口膜 (membrane)；
        4. 返回 JSON 列表，每个元素为 1 杯独立物料明细，不合并。
        """
        from global_config.models import GlobalMenuCategory, GlobalMenuItem, GlobalSkuTemplate, GlobalMenuSku, GlobalSkuIngredient
        from inventory.models import Material
        from orders.services import calculate_required_materials

        # 准备物料
        mat_plasticL = Material.objects.filter(code="plasticL").first()
        if not mat_plasticL:
            mat_plasticL = Material.objects.create(code="plasticL", name="测试塑料大杯", unit="个", material_type="cup")

        mat_syrup = Material.objects.filter(code="syrup").first()
        if not mat_syrup:
            mat_syrup = Material.objects.create(code="syrup", name="测试风味糖浆", unit="ml", material_type="thick")

        # 构造热饮，但错误配置了塑料大杯 (plasticL) 且未配置杯盖与封口膜
        g_cat = GlobalMenuCategory.objects.create(name="特调咖啡", device_model=self.dev_type, sort_order=2)
        g_item = GlobalMenuItem.objects.create(category=g_cat, name="热焦糖玛奇朵", base_price=2000)
        g_tpl = GlobalSkuTemplate.objects.create(name="大杯/热", category="默认", default_price_delta=0)
        g_sku = GlobalMenuSku.objects.create(item=g_item, template=g_tpl, price_delta=0)

        GlobalSkuIngredient.objects.create(sku=g_sku, material=self.inv_bean, quantity=15)
        GlobalSkuIngredient.objects.create(sku=g_sku, material=self.inv_milk, quantity=160)
        GlobalSkuIngredient.objects.create(sku=g_sku, material=mat_syrup, quantity=20)
        GlobalSkuIngredient.objects.create(sku=g_sku, material=mat_plasticL, quantity=1)  # 错误配置了塑料杯！

        MenuItem.sync_store_menu(self.store)
        m_item = MenuItem.objects.get(store=self.store, global_item=g_item)
        m_sku = MenuSku.objects.get(item=m_item, global_sku=g_sku)

        # 购买 2 杯热焦糖玛奇朵
        items_data = [
            {
                'item': m_item,
                'skus': [m_sku],
                'quantity': 2
            }
        ]

        per_cup_list = calculate_required_materials(items_data)

        # 校验 1：返回列表长度必须为 2（2 杯独立，绝不合并为 1 条）
        self.assertEqual(len(per_cup_list), 2)

        for cup in per_cup_list:
            self.assertEqual(cup['item_name'], "热焦糖玛奇朵")
            self.assertTrue(cup['is_hot'])
            mats = cup['materials']

            # 校验 2：热饮塑料杯 (plasticL) 必须被自动纠正为纸杯 (paperL)
            self.assertNotIn('plasticL', mats, "热饮不应包含塑料杯！")
            self.assertEqual(mats.get('paperL'), Decimal('1.00'), "热饮塑料杯应自动纠正为 paperL！")

            # 校验 3：使用纸杯必须自动成套配备杯盖 (lid)
            self.assertEqual(mats.get('lid'), Decimal('1.00'), "纸杯应自动配备杯盖 lid！")

            # 校验 4：必须配备封口膜 (membrane)
            self.assertEqual(mats.get('membrane'), Decimal('1.00'), "每杯饮品必须配备封口膜 membrane！")

            # 校验 5：单杯食材用量正确（15g 咖啡豆, 160ml 牛奶, 20ml 糖浆）
            self.assertEqual(mats.get('coffee_bean'), Decimal('15.00'))
            self.assertEqual(mats.get('fresh_milk'), Decimal('160.00'))
            self.assertEqual(mats.get('syrup'), Decimal('20.00'))




