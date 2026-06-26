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
from global_config.models import DeviceModel, GlobalMenuCategory, GlobalMenuItem, GlobalMenuSku, GlobalSkuIngredient
from menus.models import MenuItem, MenuSku
from orders.models import OrderMain, OrderItem
from payments.models import PaymentRecord


from django.test import override_settings

class PaymentAPITests(APITestCase):
    # ... setUp code ...

    def setUp(self):
        # 1. 基础数据准备
        self.user = User.objects.create_user(openid='openid-test-user-pay')
        self.store = Store.objects.create(
            name="测试支付门店",
            status=Store.STATUS_OPEN,
            code="STORE-PAY-1"
        )
        self.dev_type = DeviceModel.objects.create(name="咖啡机", code="coffee_maker_pay")
        
        self.device = Device.objects.create(
            store=self.store,
            device_sn="SN-TEST-PAY-100",
            device_name="测试支付咖啡机",
            device_model=self.dev_type,
            key_code="STORE-PAY-1",
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

            # 模拟出库设备物料库存准备
            from devices.models import DeviceMaterialStock
            DeviceMaterialStock.objects.create(device=self.device, name=self.inv_bean, code="coffee_bean")
            DeviceMaterialStock.objects.create(device=self.device, name=self.inv_milk, code="fresh_milk")

            success_response = self.client.post(mock_success_url, {"order_no": self.order.order_no}, format='json')
            self.assertEqual(success_response.status_code, status.HTTP_200_OK)
            self.assertEqual(success_response.data['code'], 0)

            # 验证订单状态是否已经转为 PAID (pending_dispense)
            self.order.refresh_from_db()
            self.assertEqual(self.order.status, OrderMain.STATUS_PAID)
            mock_mqtt.assert_called_once()
