from django.test import TestCase, Client
from devices.models import Device
from stores.models import Store
from users.models import User
from orders.models import OrderMain


class DeviceOrderPendingCheckTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create(username='test_checker_user', role='user')
        self.store = Store.objects.create(code='ST_CHECK_01', name='测试门店1')
        self.device = Device.objects.create(device_sn='sn004', device_name='北京2店设备1', store=self.store)
        self.other_device = Device.objects.create(device_sn='sn999', device_name='其他设备')

    def test_pending_order_returns_code_1(self):
        order = OrderMain.objects.create(
            user=self.user, store=self.store, device=self.device,
            status=OrderMain.STATUS_PAID,
            total_amount=1000, pay_amount=1000
        )
        # POST 请求
        res = self.client.post(
            '/api/device/order/check_pending',
            data={'device_sn': 'sn004', 'order_no': order.order_no},
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['code'], 1)
        self.assertEqual(data['data'], {})
        self.assertIn('等待制作', data['msg'])
        self.assertIsInstance(data['ts'], int)
        self.assertGreater(data['ts'], 1000000000000)

    def test_get_method_supported(self):
        order = OrderMain.objects.create(
            user=self.user, store=self.store, device=self.device,
            status=OrderMain.STATUS_PAID,
            total_amount=1000, pay_amount=1000
        )
        res = self.client.get(f'/api/device/order/check_pending?device_sn=sn004&order_no={order.order_no}')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['code'], 1)
        self.assertIn('等待制作', res.json()['msg'])

    def test_unpaid_order_returns_code_0(self):
        order = OrderMain.objects.create(
            user=self.user, store=self.store, device=self.device,
            status=OrderMain.STATUS_PENDING_PAY,
            total_amount=1000, pay_amount=1000
        )
        res = self.client.post(
            '/api/device/order/check_pending',
            data={'device_sn': 'sn004', 'order_no': order.order_no},
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['code'], 0)
        self.assertEqual(data['data'], {})
        self.assertIn('尚未支付', data['msg'])
        self.assertIsInstance(data['ts'], int)

    def test_making_order_returns_code_0(self):
        order = OrderMain.objects.create(
            user=self.user, store=self.store, device=self.device,
            status=OrderMain.STATUS_MAKING,
            total_amount=1000, pay_amount=1000
        )
        res = self.client.post(
            '/api/device/order/check_pending',
            data={'device_sn': 'sn004', 'order_no': order.order_no},
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['code'], 0)
        self.assertIn('制作中', data['msg'])

    def test_completed_order_returns_code_0(self):
        order = OrderMain.objects.create(
            user=self.user, store=self.store, device=self.device,
            status=OrderMain.STATUS_DONE,
            total_amount=1000, pay_amount=1000
        )
        res = self.client.post(
            '/api/device/order/check_pending',
            data={'device_sn': 'sn004', 'order_no': order.order_no},
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['code'], 0)
        self.assertIn('已制作完成', data['msg'])

    def test_non_existent_device_or_order(self):
        res1 = self.client.post(
            '/api/device/order/check_pending',
            data={'device_sn': 'sn_not_exist', 'order_no': '202608250001'},
            content_type='application/json'
        )
        self.assertEqual(res1.json()['code'], 0)
        self.assertIn('不存在', res1.json()['msg'])

        res2 = self.client.post(
            '/api/device/order/check_pending',
            data={'device_sn': 'sn004', 'order_no': '20260825_not_exist'},
            content_type='application/json'
        )
        self.assertEqual(res2.json()['code'], 0)
        self.assertIn('不存在', res2.json()['msg'])

    def test_mismatched_device(self):
        order = OrderMain.objects.create(
            user=self.user, store=self.store, device=self.device,
            status=OrderMain.STATUS_PAID,
            total_amount=1000, pay_amount=1000
        )
        res = self.client.post(
            '/api/device/order/check_pending',
            data={'device_sn': 'sn999', 'order_no': order.order_no},
            content_type='application/json'
        )
        self.assertEqual(res.json()['code'], 0)
        self.assertIn('不一致', res.json()['msg'])

