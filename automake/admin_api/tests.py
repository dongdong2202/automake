from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from users.models import User
from stores.models import Store
from devices.models import Device
from inventory.models import Material
from orders.models import OrderMain


class AdminApiTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.super_admin = User.objects.create_superuser(
            username='admin_test',
            password='Password123!',
            role=User.SUPER_ADMIN
        )
        self.store = Store.objects.create(
            name='北京测试旗舰店',
            address='北京市朝阳区三里屯',
            status=Store.STATUS_OPEN
        )
        self.device = Device.objects.create(
            device_sn='TEST-ADMIN-SN01',
            device_name='1号测试机',
            store=self.store,
            status=Device.STATUS_ONLINE
        )
        self.material = Material.objects.create(
            name='特级咖啡豆',
            code='M001',
            material_type=Material.TYPE_INGREDIENT,
            quantity=50.0,
            unit='kg'
        )

    def test_admin_login(self):
        response = self.client.post('/api/user/admin/login', {
            'username': 'admin_test',
            'password': 'Password123!'
        }, format='json')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['code'], 0)
        self.assertIn('access', data['data'])
        self.assertEqual(data['data']['user']['role'], User.SUPER_ADMIN)

    def test_dashboard_stats(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get('/api/admin/dashboard/stats')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['code'], 0)
        self.assertIn('kpis', data['data'])
        self.assertIn('trend', data['data'])

    def test_sales_analytics(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get('/api/admin/analytics/sales/trend')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['code'], 0)

        response_hour = self.client.get('/api/admin/analytics/sales/by-hour')
        self.assertEqual(response_hour.status_code, 200)
        self.assertEqual(len(response_hour.json()['data']), 24)

    def test_material_stock_and_record(self):
        self.client.force_authenticate(user=self.super_admin)
        # 1. 查询物料
        res_list = self.client.get('/api/admin/inventory/materials/')
        self.assertEqual(res_list.status_code, 200)

        # 2. 登记入库
        res_in = self.client.post('/api/admin/inventory/records/', {
            'material_id': self.material.id,
            'record_type': 'in',
            'quantity': 20.0,
            'price': 60.0,
            'remarks': '采购入库测试'
        }, format='json')
        self.assertEqual(res_in.status_code, 200)

        # 验证物料库存增加至 70.0
        self.material.refresh_from_db()
        self.assertEqual(float(self.material.quantity), 70.0)

        # 3. 登记出库
        res_out = self.client.post('/api/admin/inventory/records/', {
            'material_id': self.material.id,
            'record_type': 'out',
            'quantity': 10.0,
            'store_id': self.store.id,
            'remarks': '分拨门店出库测试'
        }, format='json')
        self.assertEqual(res_out.status_code, 200)

        self.material.refresh_from_db()
        self.assertEqual(float(self.material.quantity), 60.0)

    def test_device_province_and_city_management_and_filter(self):
        """测试设备档案录入省/市字段及按省/市过滤接口"""
        self.client.force_authenticate(user=self.super_admin)

        # 1. 录入带省、市的新设备
        create_res = self.client.post('/api/admin/devices/', {
            'device_sn': 'DEV-GZ-001',
            'device_name': '广州天河城1号机',
            'store': self.store.id,
            'province': '广东省',
            'city': '广州市',
            'address': '天河路208号天河城B1',
            'status': 'online'
        }, format='json')
        self.assertEqual(create_res.status_code, 200)
        data = create_res.json()['data']
        self.assertEqual(data['province'], '广东省')
        self.assertEqual(data['city'], '广州市')

        # 2. 录入第二台设备（不同省市）
        self.client.post('/api/admin/devices/', {
            'device_sn': 'DEV-SZ-001',
            'device_name': '深圳万象天地2号机',
            'store': self.store.id,
            'province': '广东省',
            'city': '深圳市',
            'address': '深南大道9668号万象天地',
            'status': 'online'
        }, format='json')

        # 3. 按省份过滤（查询广东省）
        res_prov = self.client.get('/api/admin/devices/', {'province': '广东'})
        self.assertEqual(res_prov.status_code, 200)
        results_prov = res_prov.json()['data']['results']
        sn_list_prov = [d['device_sn'] for d in results_prov]
        self.assertIn('DEV-GZ-001', sn_list_prov)
        self.assertIn('DEV-SZ-001', sn_list_prov)

        # 4. 按城市过滤（查询广州市）
        res_city = self.client.get('/api/admin/devices/', {'city': '广州'})
        self.assertEqual(res_city.status_code, 200)
        results_city = res_city.json()['data']['results']
        sn_list_city = [d['device_sn'] for d in results_city]
        self.assertIn('DEV-GZ-001', sn_list_city)
        self.assertNotIn('DEV-SZ-001', sn_list_city)

        # 5. 更新设备省市
        update_res = self.client.put('/api/admin/devices/DEV-GZ-001/', {
            'province': '广东省',
            'city': '珠海市'
        }, format='json')
        self.assertEqual(update_res.status_code, 200)
        dev = Device.objects.get(device_sn='DEV-GZ-001')
        self.assertEqual(dev.city, '珠海市')

    def test_device_business_hours_and_status(self):
        """测试 api/admin/devices/ 接口的营业时间判断与打烊/正在营业中提示"""
        self.client.force_authenticate(user=self.super_admin)

        # 1. 设置门店营业时间为全天 00:00-23:59
        self.store.business_hours = {
            "mon": "00:00-23:59", "tue": "00:00-23:59", "wed": "00:00-23:59",
            "thu": "00:00-23:59", "fri": "00:00-23:59", "sat": "00:00-23:59", "sun": "00:00-23:59"
        }
        self.store.save()

        res_open = self.client.get('/api/admin/devices/', {'search': self.device.device_sn})
        self.assertEqual(res_open.status_code, 200)
        dev_open_data = res_open.json()['data']['results'][0]
        self.assertTrue(dev_open_data['is_in_business_hours'])
        self.assertEqual(dev_open_data['business_status'], '正在营业中')
        self.assertEqual(dev_open_data['business_status_text'], '正在营业中')

        # 2. 设置门店营业时间为全天已打烊 closed
        self.store.business_hours = {
            "mon": "closed", "tue": "closed", "wed": "closed",
            "thu": "closed", "fri": "closed", "sat": "closed", "sun": "closed"
        }
        self.store.save()

        res_closed = self.client.get('/api/admin/devices/', {'search': self.device.device_sn})
        self.assertEqual(res_closed.status_code, 200)
        dev_closed_data = res_closed.json()['data']['results'][0]
        self.assertFalse(dev_closed_data['is_in_business_hours'])
        self.assertEqual(dev_closed_data['business_status'], '今日休息')
        self.assertEqual(dev_closed_data['business_status_text'], '今日休息')

    def test_admin_order_refund_wechat_error_message(self):
        """测试退款遇到微信商户余额不足等错误时，友好返回具体错误信息"""
        from unittest.mock import patch, MagicMock
        from payments.models import PaymentRecord
        import requests

        self.client.force_authenticate(user=self.super_admin)

        order = OrderMain.objects.create(
            order_no='ORD_TEST_REFUND_FAIL_001',
            order_token='token-fail-001',
            user=self.super_admin,
            store=self.store,
            device=self.device,
            status=OrderMain.STATUS_PAID,
            total_amount=100,
            pay_amount=100
        )
        PaymentRecord.objects.create(
            order=order,
            user=self.super_admin,
            transaction_id='4500000000000000000000000001',
            out_trade_no=order.order_no,
            amount=100,
            status=PaymentRecord.STATUS_SUCCESS
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = '{"code":"NOT_ENOUGH","message":"基本账户余额不足，请充值后重新发起"}'
        mock_resp.json.return_value = {"code": "NOT_ENOUGH", "message": "基本账户余额不足，请充值后重新发起"}
        http_error = requests.exceptions.HTTPError("403 Client Error: Forbidden", response=mock_resp)
        mock_resp.raise_for_status.side_effect = http_error

        with patch('requests.request', return_value=mock_resp):
            res = self.client.post(f'/api/admin/orders/{order.order_no}/refund/', {'reason': '人工退款'}, format='json')
            self.assertEqual(res.status_code, 400)
            data = res.json()
            self.assertEqual(data['code'], 4001)
            self.assertIn('基本账户余额不足', data['message'])
            self.assertIn('NOT_ENOUGH', data['message'])

    def test_admin_order_refund_offline(self):
        """测试管理员标记线下退款成功流程"""
        from payments.models import PaymentRecord, RefundRecord

        self.client.force_authenticate(user=self.super_admin)

        order = OrderMain.objects.create(
            order_no='ORD_TEST_REFUND_OFFLINE_001',
            order_token='token-offline-001',
            user=self.super_admin,
            store=self.store,
            device=self.device,
            status=OrderMain.STATUS_PAID,
            total_amount=200,
            pay_amount=200
        )
        PaymentRecord.objects.create(
            order=order,
            user=self.super_admin,
            transaction_id='4500000000000000000000000002',
            out_trade_no=order.order_no,
            amount=200,
            status=PaymentRecord.STATUS_SUCCESS
        )

        res = self.client.post(
            f'/api/admin/orders/{order.order_no}/refund/',
            {'reason': '现场赔付现金', 'offline': True},
            format='json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['code'], 0)
        self.assertIn('线下退款已成功记录', data['message'])

        order.refresh_from_db()
        self.assertEqual(order.status, OrderMain.STATUS_REFUNDED)
        refund_record = RefundRecord.objects.filter(order=order).first()
        self.assertIsNotNone(refund_record)
        self.assertEqual(refund_record.status, RefundRecord.STATUS_SUCCESS)
        self.assertIn('现场赔付现金', refund_record.reason)

    @patch('orders.services.restore_order_inventory')
    @patch('admin_api.views.orders.refund_order')
    def test_admin_order_auto_refund_flow(self, mock_refund_order, mock_restore_inventory):
        """测试未制作订单自动退款（放库存，自动退款）"""
        self.client.force_authenticate(user=self.super_admin)
        mock_restore_inventory.return_value = {
            'success': True,
            'restored_materials': [
                {'name': '纸大杯', 'quantity': 1, 'unit': '个'}
            ]
        }

        order = OrderMain.objects.create(
            order_no='ORD_TEST_AUTO_REFUND_001',
            order_token='token-auto-001',
            user=self.super_admin,
            store=self.store,
            device=self.device,
            status=OrderMain.STATUS_PAID,
            total_amount=1800,
            pay_amount=1800
        )

        res = self.client.post(
            f'/api/admin/orders/{order.order_no}/refund/',
            {'refund_type': 'auto', 'reason': '用户未制作取消'},
            format='json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['code'], 0)
        self.assertIn('自动退款成功', data['message'])
        self.assertIn('纸大杯 x1个', data['message'])

        mock_restore_inventory.assert_called_once()
        mock_refund_order.assert_called_once()

    def test_admin_order_auto_refund_on_done_order_fails(self):
        """测试已完成订单调用自动退款会被拦截并提示改用强制退款"""
        self.client.force_authenticate(user=self.super_admin)

        order = OrderMain.objects.create(
            order_no='ORD_TEST_AUTO_DONE_FAIL_001',
            order_token='token-auto-fail-001',
            user=self.super_admin,
            store=self.store,
            device=self.device,
            status=OrderMain.STATUS_DONE,  # 已完成制作
            total_amount=1800,
            pay_amount=1800
        )

        res = self.client.post(
            f'/api/admin/orders/{order.order_no}/refund/',
            {'refund_type': 'auto', 'reason': '已出杯退款测试'},
            format='json'
        )
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertEqual(data['code'], 4003)
        self.assertIn('无法使用自动退款（放库存），请使用【强制退款】', data['message'])

    @patch('orders.services.restore_order_inventory')
    @patch('admin_api.views.orders.refund_order')
    def test_admin_order_force_refund_flow(self, mock_refund_order, mock_restore_inventory):
        """测试强制退款（不退库存，如客诉或制作失败）"""
        self.client.force_authenticate(user=self.super_admin)

        order = OrderMain.objects.create(
            order_no='ORD_TEST_FORCE_REFUND_001',
            order_token='token-force-001',
            user=self.super_admin,
            store=self.store,
            device=self.device,
            status=OrderMain.STATUS_DONE,
            total_amount=1800,
            pay_amount=1800
        )

        res = self.client.post(
            f'/api/admin/orders/{order.order_no}/refund/',
            {'refund_type': 'force', 'reason': '顾客投诉咖啡口感变质'},
            format='json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['code'], 0)
        self.assertIn('强制退款成功', data['message'])
        self.assertIn('未归还物料库存', data['message'])

        # 验证：绝不调用放库函数
        mock_restore_inventory.assert_not_called()
        # 验证：微信退款正常触发
        mock_refund_order.assert_called_once()


