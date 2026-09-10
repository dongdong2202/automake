"""
支付模块测试用例
"""

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from unittest.mock import patch, MagicMock

from users.models import User
from stores.models import Store
from devices.models import Device
from global_config.models import DeviceModel, GlobalMenuCategory, GlobalMenuItem, GlobalSkuTemplate, GlobalMenuSku, GlobalSkuIngredient
from menus.models import MenuItem, MenuSku
from orders.models import OrderMain, OrderItem
from payments.models import PaymentRecord


from django.test import override_settings

class PaymentAPITests(APITestCase):
    # ... setUp code ...

    def setUp(self):
        # 1. 基础数据准备
        self.user = User.objects.create_user(openid="test_openid_123")
        self.store = Store.objects.create(
            code="test_store_01",
            name="测试门店",
            status=Store.STATUS_OPEN
        )
        self.dev_type = DeviceModel.objects.create(
            code="test_dev_01",
            name="测试设备类型"
        )
        self.device = Device.objects.create(
            store=self.store,
            device_sn="SN_PAY_TEST_01",
            device_name="测试咖啡机",
            device_model=self.dev_type,
            status=Device.STATUS_ONLINE
        )

        from inventory.models import Material
        self.inv_bean, _ = Material.objects.get_or_create(code="coffee_bean", defaults={"name": "咖啡豆", "unit": "g", "quantity": 1000})
        self.inv_milk, _ = Material.objects.get_or_create(code="fresh_milk", defaults={"name": "牛奶", "unit": "ml", "quantity": 5000})
        self.inv_cup, _ = Material.objects.get_or_create(code="paperL", defaults={"name": "纸大杯", "unit": "个", "quantity": 100, "material_type": "cup"})
        self.inv_cup.quantity = 100
        self.inv_cup.save()

        from devices.models import DeviceConsumableStock, DeviceMaterialStock
        for cup_code in ['paperL', 'paperM', 'plasticL', 'plasticM', 'membrane', 'lid']:
            mat, _ = Material.objects.get_or_create(code=cup_code, defaults={'name': cup_code, 'material_type': 'cup'})
            DeviceConsumableStock.objects.create(
                device=self.device,
                code=mat,
                init_quantity=100,
                quantity=100,
                warn_level=15
            )
        DeviceMaterialStock.objects.create(device=self.device, name=self.inv_bean, code="coffee_bean")
        DeviceMaterialStock.objects.create(device=self.device, name=self.inv_milk, code="fresh_milk")

        # 2. 全局菜单体系
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

        # 5. 创建待支付订单
        self.order = OrderMain.objects.create(
            order_no="20260622052151001",
            user=self.user,
            store=self.store,
            device=self.device,
            total_amount=1800,
            discount_amount=0,
            pay_amount=1800,
            status=OrderMain.STATUS_PENDING_PAY
        )
        self.order_item = OrderItem.objects.create(
            order=self.order,
            item=self.menu_item,
            item_name="拿铁",
            sku_name="大杯/热",
            quantity=1,
            unit_price=1800,
            subtotal=1800
        )
        self.order_item.skus.add(self.menu_sku)

    @patch('utils.wechat.WechatPayV3.create_jsapi_order')
    @override_settings(DEBUG=True)
    def test_create_payment_and_mock_success(self, mock_create_jsapi):
        """测试发起支付请求并在开发模式下模拟支付成功"""
        # 1. 模拟微信统一下单返回 prepay_id
        mock_create_jsapi.return_value = {"prepay_id": "wx_prepay_id_test_123456"}

        self.client.force_authenticate(user=self.user)
        create_url = reverse('pay-create')
        data = {"order_no": self.order.order_no}

        response = self.client.post(create_url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['code'], 0)
        self.assertIn('package', response.data['data'])
        self.assertEqual(response.data['data']['package'], 'prepay_id=wx_prepay_id_test_123456')

        # 2. 模拟支付成功请求
        mock_success_url = reverse('pay-mock-success')
        
        # 使用 patch 模拟 Redis 和 MQTT 下发
        with patch('django_redis.get_redis_connection') as mock_redis, \
             patch('mqtt.issue_make_command') as mock_mqtt:
            
            # 模拟 Lua 预扣脚本返回成功 (1)
            mock_conn = MagicMock()
            mock_conn.register_script().return_value = 1
            mock_redis.return_value = mock_conn

            success_response = self.client.post(mock_success_url, {"order_no": self.order.order_no}, format='json')
            self.assertEqual(success_response.status_code, status.HTTP_200_OK)
            self.assertEqual(success_response.data['code'], 0)

            # 验证订单状态是否已经转为 PAID (pending_dispense)
            self.order.refresh_from_db()
            self.assertEqual(self.order.status, OrderMain.STATUS_PAID)
            mock_mqtt.assert_called_once()

    @patch('utils.wechat.WechatPayV3.create_native_order')
    def test_create_native_order_and_qr(self, mock_create_native):
        """测试发起 Native 扫码支付获取 code_url"""
        mock_create_native.return_value = {"code_url": "weixin://wxpay/bizpayurl?pr=test_native_qr_123"}
        
        # 测试 /api/pay/wechat/native
        res = self.client.post('/api/pay/wechat/native', {'order_no': self.order.order_no}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['code'], 0)
        self.assertEqual(res.data['data']['code_url'], "weixin://wxpay/bizpayurl?pr=test_native_qr_123")
        self.assertEqual(res.data['data']['pay_method'], "wechat_native")

        # 测试别名路由 /api/orders/<order_id>/native-payment/
        res_alias = self.client.post(f'/api/orders/{self.order.order_no}/native-payment/', format='json')
        self.assertEqual(res_alias.status_code, 200)
        self.assertEqual(res_alias.data['code'], 0)
        self.assertEqual(res_alias.data['data']['code_url'], "weixin://wxpay/bizpayurl?pr=test_native_qr_123")

    @patch('utils.wechat.WechatPayV3.create_codepay_order')
    @patch('mqtt.issue_make_command')
    def test_process_codepay_success(self, mock_mqtt, mock_codepay):
        """测试付款码支付成功并自动流转至已支付与下发制作"""
        mock_codepay.return_value = {
            'return_code': 'SUCCESS',
            'result_code': 'SUCCESS',
            'transaction_id': 'wx_tx_codepay_998877',
            'out_trade_no': self.order.order_no,
            'time_end': '20260825203000'
        }

        # 调用付款码接口 /api/internal/payments/wechat/codepay/
        res = self.client.post('/api/internal/payments/wechat/codepay/', {
            'order_no': self.order.order_no,
            'auth_code': '134567890123456789',
            'device_sn': self.device.device_sn
        }, format='json')

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['code'], 0)
        self.assertEqual(res.data['data']['status'], 'success')
        self.assertEqual(res.data['data']['transaction_id'], 'wx_tx_codepay_998877')

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderMain.STATUS_PAID)
        mock_mqtt.assert_called_once()

    @patch('utils.wechat.WechatPayV3.query_order')
    @patch('mqtt.issue_make_command')
    def test_query_and_sync_payment_status(self, mock_mqtt, mock_query):
        """测试主动查单补偿机制"""
        # 模拟生成支付记录
        PaymentRecord.objects.create(
            order=self.order,
            user=self.user,
            out_trade_no=self.order.order_no,
            amount=self.order.pay_amount,
            status=PaymentRecord.STATUS_PENDING,
            pay_method='wechat_native'
        )

        mock_query.return_value = {
            'trade_state': 'SUCCESS',
            'transaction_id': 'wx_tx_query_112233',
            'amount': {'payer_total': 1800}
        }

        # 调用状态查询接口（带 sync_wechat=1 主动向微信查单补偿）
        res = self.client.get(f'/api/orders/{self.order.order_no}/payment-status/?sync_wechat=1')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data['data']['paid'])
        self.assertEqual(res.data['data']['trade_state'], 'SUCCESS')

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderMain.STATUS_PAID)
        mock_mqtt.assert_called_once()

    @patch('utils.wechat.WechatPayV3.query_order')
    @patch('mqtt.issue_make_command')
    def test_client_polling_read_only_mode(self, mock_mqtt, mock_query):
        """测试客户端高频轮询模式只读本地数据库状态，绝不触发微信查单与履约"""
        PaymentRecord.objects.create(
            order=self.order,
            user=self.user,
            out_trade_no=self.order.order_no,
            amount=self.order.pay_amount,
            status=PaymentRecord.STATUS_PENDING,
            pay_method='wechat_native'
        )
        # 客户端默认轮询（不带 sync_wechat）
        res = self.client.get(f'/api/orders/{self.order.order_no}/payment-status/')
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data['data']['paid'])
        self.assertEqual(res.data['data']['trade_state'], 'NOTPAY')
        mock_query.assert_not_called()
        mock_mqtt.assert_not_called()

    @patch('mqtt.issue_make_command')
    def test_payment_callback_idempotency_and_no_duplicate_timeline(self, mock_mqtt):
        """测试微信支付回调防重与履约时间线幂等性（多次通知仅下发一次、时间线各记一次）"""
        from payments.services import process_payment_success
        from orders.models import OrderStatusLog
        PaymentRecord.objects.create(
            order=self.order,
            user=self.user,
            out_trade_no=self.order.order_no,
            amount=self.order.pay_amount,
            status=PaymentRecord.STATUS_PENDING,
            pay_method='wechat_native'
        )

        # 第一次回调通知到达
        process_payment_success(
            order_no=self.order.order_no,
            transaction_id='wx_tx_123456',
            pay_time='2026-09-10T14:32:52Z',
            wx_amount=self.order.pay_amount
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderMain.STATUS_PAID)
        self.assertEqual(mock_mqtt.call_count, 1)

        # 第二次回调重试到达（模拟网络重试）
        process_payment_success(
            order_no=self.order.order_no,
            transaction_id='wx_tx_123456',
            pay_time='2026-09-10T14:32:52Z',
            wx_amount=self.order.pay_amount
        )

        # 验证：MQTT 命令依然只发布了 1 次
        self.assertEqual(mock_mqtt.call_count, 1)

        # 验证：时间线中 pay_success 和 task_sent 各自只有 1 条记录
        pay_success_logs = self.order.status_logs.filter(action=OrderStatusLog.ACTION_PAY_SUCCESS)
        task_sent_logs = self.order.status_logs.filter(action=OrderStatusLog.ACTION_TASK_SENT)
        self.assertEqual(pay_success_logs.count(), 1)
        self.assertEqual(task_sent_logs.count(), 1)

    def test_payment_test_page_render(self):
        """测试真实支付测试控制台 HTML 页面渲染"""
        res = self.client.get('/payment-test/')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, '微信支付真实测试控制台')
        self.assertContains(res, 'Native 扫码支付')
        self.assertContains(res, '付款码支付')
