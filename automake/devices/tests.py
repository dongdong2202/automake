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


class DeviceGuideCheckTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.store1 = Store.objects.create(code='ST_G_01', name='天河店')
        self.store2 = Store.objects.create(code='ST_G_02', name='越秀店')
        self.device1 = Device.objects.create(device_sn='sn005', device_name='咖啡机05', store=self.store1)
        self.device_no_store = Device.objects.create(device_sn='sn006', device_name='测试机06')

        # 超级管理员
        self.super_user = User.objects.create_superuser(username='super_boss', password='password123')
        self.super_user.phone = '13900000001'
        self.super_user.save()

        # 天河店引导员
        self.guide_user = User.objects.create(username='guide_zhang', role=User.GUIDE, phone='13900000002')
        self.guide_user.stores.add(self.store1)

        # 越秀店协调员
        self.coord_user = User.objects.create(username='coord_li', role=User.COORDINATOR, phone='13900000003')
        self.coord_user.stores.add(self.store2)

        # 普通客户
        self.customer_user = User.objects.create_user(openid='wx_cust_001', role=User.CUSTOMER, phone='13900000004')

    def test_missing_params(self):
        res = self.client.post('/api/device/guide/check', data={}, content_type='application/json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['code'], 1)
        self.assertEqual(res.json()['data'], {})

    def test_device_not_found(self):
        res = self.client.post(
            '/api/device/guide/check',
            data={'device_sn': 'sn_not_exist', 'phone': '13900000002'},
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['code'], 0)
        self.assertEqual(res.json()['message'], '不是引导员')
        self.assertEqual(res.json()['data'], {})

    def test_phone_not_found(self):
        res = self.client.post(
            '/api/device/guide/check',
            data={'device_sn': 'sn005', 'phone': '13999999999'},
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['code'], 0)
        self.assertEqual(res.json()['message'], '不是引导员')

    def test_super_admin_is_guide(self):
        res = self.client.post(
            '/api/device/guide/check',
            data={'device_sn': 'sn005', 'phone': '13900000001'},
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['code'], 1)
        self.assertEqual(res.json()['message'], '是引导员')
        self.assertEqual(res.json()['data'], {})

    def test_matched_store_guide_is_guide(self):
        res = self.client.post(
            '/api/device/guide/check',
            data={'device_sn': 'sn005', 'phone': '13900000002'},
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['code'], 1)
        self.assertEqual(res.json()['message'], '是引导员')

    def test_unmatched_store_staff_is_not_guide(self):
        res = self.client.post(
            '/api/device/guide/check',
            data={'device_sn': 'sn005', 'phone': '13900000003'},
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['code'], 0)
        self.assertEqual(res.json()['message'], '不是引导员')

    def test_customer_is_not_guide(self):
        res = self.client.post(
            '/api/device/guide/check',
            data={'device_sn': 'sn005', 'phone': '13900000004'},
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['code'], 0)
        self.assertEqual(res.json()['message'], '不是引导员')

    def test_staff_on_device_without_store(self):
        res = self.client.get(
            f'/api/device/guide/check?device_sn=sn006&phone=13900000002'
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['code'], 1)
        self.assertEqual(res.json()['message'], '是引导员')


class DeviceBatchRefundTests(TestCase):
    def setUp(self):
        from payments.models import PaymentRecord
        from devices.models import DeviceConsumableStock
        from inventory.models import Material
        self.client = Client()
        self.store = Store.objects.create(code='ST_REFUND_01', name='退款测试店')
        self.device = Device.objects.create(device_sn='sn005', device_name='咖啡机05', store=self.store)
        self.user = User.objects.create(username='refund_test_user', openid='wx_test_refund_user')
        
        # 耗材
        self.mat_cup, _ = Material.objects.get_or_create(
            code='paperL',
            defaults={'name': '纸大杯', 'material_type': Material.TYPE_CUP, 'unit': '个'}
        )
        self.consumable_stock, _ = DeviceConsumableStock.objects.get_or_create(
            device=self.device,
            code=self.mat_cup,
            defaults={'quantity': 50, 'init_quantity': 100}
        )

        # 订单1 (用于退款退库存)
        self.order1 = OrderMain.objects.create(
            order_no='ORD_REFUND_001',
            user=self.user,
            store=self.store,
            device=self.device,
            status=OrderMain.STATUS_PAID,
            total_amount=1500,
            pay_amount=1500
        )
        PaymentRecord.objects.create(
            order=self.order1,
            user=self.user,
            out_trade_no='ORD_REFUND_001',
            transaction_id='mock_tx_001',
            amount=1500,
            status=PaymentRecord.STATUS_SUCCESS
        )

        from orders.models import OrderItem
        OrderItem.objects.create(
            order=self.order1,
            item_name='热美式',
            sku_name='大杯',
            quantity=1,
            unit_price=1500,
            subtotal=1500
        )

        # 订单2 (用于退款不退库存)
        self.order2 = OrderMain.objects.create(
            order_no='ORD_REFUND_002',
            user=self.user,
            store=self.store,
            device=self.device,
            status=OrderMain.STATUS_DONE,
            total_amount=2000,
            pay_amount=2000
        )
        PaymentRecord.objects.create(
            order=self.order2,
            user=self.user,
            out_trade_no='ORD_REFUND_002',
            transaction_id='mock_tx_002',
            amount=2000,
            status=PaymentRecord.STATUS_SUCCESS
        )
        OrderItem.objects.create(
            order=self.order2,
            item_name='热美式',
            sku_name='大杯',
            quantity=1,
            unit_price=2000,
            subtotal=2000
        )

    def test_missing_device_sn(self):
        res = self.client.post('/api/device/order/batch_refund', data={'refund_stock': ['ORD_REFUND_001']}, content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['code'], 0)

    def test_device_not_found(self):
        res = self.client.post('/api/device/order/batch_refund', data={'device_sn': 'sn_not_found', 'refund_stock': ['ORD_REFUND_001']}, content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['code'], 0)
        self.assertIn('不存在', res.json()['message'])

    def test_empty_order_lists(self):
        res = self.client.post('/api/device/order/batch_refund', data={'device_sn': 'sn005'}, content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['code'], 0)

    def test_batch_refund_both_lists(self):
        from unittest.mock import patch, MagicMock
        from payments.models import RefundRecord

        with patch('django_redis.get_redis_connection') as mock_get_redis, \
             patch('utils.wechat.WechatPayV3.apply_refund', return_value={'refund_id': 'rf_test_123', 'status': 'SUCCESS'}):
            mock_redis = MagicMock()
            mock_get_redis.return_value = mock_redis

            payload = {
                'device_sn': 'sn005',
                'refund_stock': ['ORD_REFUND_001'],
                'refund_no_stock': ['ORD_REFUND_002'],
                'reason': '测试批量退款'
            }
            res = self.client.post('/api/device/order/batch_refund', data=payload, content_type='application/json')
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data['code'], 1)
            self.assertEqual(data['data']['success'], True)
            self.assertEqual(data['data']['success_orders'], ['ORD_REFUND_001', 'ORD_REFUND_002'])

            # 检查订单状态与退款记录
            self.order1.refresh_from_db()
            self.order2.refresh_from_db()
            self.assertEqual(self.order1.status, OrderMain.STATUS_REFUNDED)
            self.assertEqual(self.order2.status, OrderMain.STATUS_REFUNDED)

            self.assertTrue(RefundRecord.objects.filter(order=self.order1, status=RefundRecord.STATUS_SUCCESS).exists())
            self.assertTrue(RefundRecord.objects.filter(order=self.order2, status=RefundRecord.STATUS_SUCCESS).exists())

            # 检查库存恢复（order1 退库存，增加了 1 个纸大杯；order2 不退库存，没有继续增加）
            self.consumable_stock.refresh_from_db()
            self.assertEqual(self.consumable_stock.quantity, 51)

    def test_batch_refund_partial_success(self):
        from unittest.mock import patch, MagicMock

        with patch('django_redis.get_redis_connection') as mock_get_redis, \
             patch('utils.wechat.WechatPayV3.apply_refund', return_value={'refund_id': 'rf_test_123', 'status': 'SUCCESS'}):
            mock_redis = MagicMock()
            mock_get_redis.return_value = mock_redis

            payload = {
                'device_sn': 'sn005',
                'refund_stock': ['ORD_REFUND_001', 'NON_EXISTENT_ORDER_999'],
                'reason': '测试部分退款'
            }
            res = self.client.post('/api/device/order/batch_refund', data=payload, content_type='application/json')
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data['code'], 0)
            self.assertEqual(data['data']['success'], False)
            self.assertEqual(data['data']['success_orders'], ['ORD_REFUND_001'])
            self.assertEqual(data['message'], '部分退款成功')


class DeviceConf1Tests(TestCase):
    def setUp(self):
        from devices.models import DeviceConf1
        self.client = Client()
        self.device_sn = 'sn_conf_test_01'
        
        # 创建两条历史配置，验证最新配置返回
        self.conf_v1 = DeviceConf1.objects.create(
            device_sn=self.device_sn,
            config={'motor_speed': 100, 'temp_limit': 90},
            version='1.0.0'
        )
        self.conf_v2 = DeviceConf1.objects.create(
            device_sn=self.device_sn,
            config={'motor_speed': 120, 'temp_limit': 95, 'auto_clean': True},
            version='2.0.0'
        )

    def test_missing_device_sn(self):
        res = self.client.get('/api/device/conf1')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['code'], 6001)

    def test_device_no_config(self):
        res = self.client.get('/api/device/conf1?device_sn=sn_non_existent')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['code'], 0)
        self.assertEqual(data['data']['config'], {})
        self.assertEqual(data['data']['version'], '')

    def test_get_latest_config(self):
        # 验证返回的是最新创建的 v2 配置
        res = self.client.get(f'/api/device/conf1?device_sn={self.device_sn}')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['code'], 0)
        self.assertEqual(data['data']['device_sn'], self.device_sn)
        self.assertEqual(data['data']['version'], '2.0.0')
        self.assertEqual(data['data']['config']['motor_speed'], 120)
        self.assertTrue(data['data']['config']['auto_clean'])

    def test_get_by_path_param(self):
        res = self.client.get(f'/api/device/conf1/{self.device_sn}')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['data']['version'], '2.0.0')

    def test_post_query_and_create_config(self):
        # POST 查询最新配置
        res = self.client.post('/api/device/conf1', data={'device_sn': self.device_sn}, content_type='application/json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['data']['version'], '2.0.0')

        # POST 保存新配置 v3
        new_payload = {
            'device_sn': self.device_sn,
            'config': {'motor_speed': 150, 'mode': 'turbo'},
            'version': '3.0.0'
        }
        res_post = self.client.post('/api/device/conf1', data=new_payload, content_type='application/json')
        self.assertEqual(res_post.status_code, 200)
        self.assertEqual(res_post.json()['data']['version'], '3.0.0')
        self.assertEqual(res_post.json()['data']['config']['mode'], 'turbo')

        # 再次 GET 确认最新配置为 v3
        res_get = self.client.get(f'/api/device/conf1?device_sn={self.device_sn}')
        self.assertEqual(res_get.json()['data']['version'], '3.0.0')
        self.assertEqual(res_get.json()['data']['config']['mode'], 'turbo')


class DeviceUnifiedConfigTests(TestCase):
    def setUp(self):
        from devices.models import Device, DeviceConf1, DevicePoster
        from stores.models import Store
        from global_config.models import DeviceModel, GlobalMenuCategory, GlobalMenuItem, GlobalSkuTemplate, GlobalSkuTemplateIngredient, GlobalMenuSku
        from menus.models import MenuItem, MenuSku
        from inventory.models import Material

        self.client = Client()
        self.store = Store.objects.create(name='测试统一配置门店', code='STORE_CONF_01')
        self.device_model = DeviceModel.objects.create(name='MODEL_CONF_01', code='MCONF01')
        self.device = Device.objects.create(
            device_sn='sn_unified_01',
            store=self.store,
            device_model=self.device_model,
            device_name='统一测试设备01'
        )

        # 1. 准备 conf1
        self.conf1 = DeviceConf1.objects.create(
            device_sn='sn_unified_01',
            config={'heater': 95, 'pump_rate': 2.5},
            version='1.2.0'
        )

        # 2. 准备 conf2 (菜单与物料配方)
        self.category = GlobalMenuCategory.objects.create(device_model=self.device_model, name='热咖啡', label='Hot Coffee', sort_order=1)
        self.global_item = GlobalMenuItem.objects.create(category=self.category, name='拿铁咖啡', sort_order=1)
        self.template = GlobalSkuTemplate.objects.create(category='杯型', name='大杯/热')
        
        self.mat_bean = Material.objects.create(code='coffee_bean_test', name='咖啡豆', unit='g')
        GlobalSkuTemplateIngredient.objects.create(template=self.template, material=self.mat_bean, quantity=18.0)
        
        self.global_sku = GlobalMenuSku.objects.create(item=self.global_item, template=self.template)

        self.menu_item = MenuItem.objects.create(
            store=self.store,
            device_model=self.device_model,
            global_item=self.global_item,
            base_price=1500
        )
        self.menu_sku = MenuSku.objects.create(
            item=self.menu_item,
            global_sku=self.global_sku,
            price_delta=200
        )

        # 3. 准备 conf3 (海报)
        self.poster = DevicePoster.objects.create(
            title='冬季热饮海报',
            version=5,
            is_active=True
        )
        self.poster.devices.add(self.device)

    def test_missing_device_sn(self):
        res = self.client.get('/api/device/config?data=conf1')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['code'], 6001)

    def test_missing_data_type(self):
        res = self.client.get('/api/device/config?device_sn=sn_unified_01')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['code'], 6002)

    def test_invalid_data_type(self):
        res = self.client.get('/api/device/config?device_sn=sn_unified_01&data=conf999')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['code'], 6004)

    def test_query_conf1_get_and_post(self):
        # GET
        res_get = self.client.get('/api/device/config?device_sn=sn_unified_01&data=conf1')
        self.assertEqual(res_get.status_code, 200)
        data_get = res_get.json()
        self.assertEqual(data_get['code'], 0)
        self.assertEqual(data_get['data']['device_sn'], 'sn_unified_01')
        self.assertEqual(data_get['data']['version'], '1.2.0')
        self.assertEqual(data_get['data']['config']['heater'], 95)

        # POST
        res_post = self.client.post('/api/device/config', data={'device_sn': 'sn_unified_01', 'data': 'conf1'}, content_type='application/json')
        self.assertEqual(res_post.status_code, 200)
        self.assertEqual(res_post.json()['data']['version'], '1.2.0')

    def test_query_conf2_menu_get_and_post(self):
        # GET
        res_get = self.client.get('/api/device/config?device_sn=sn_unified_01&data=conf2')
        self.assertEqual(res_get.status_code, 200)
        data_get = res_get.json()
        self.assertEqual(data_get['code'], 0)
        self.assertEqual(data_get['data']['store_name'], '测试统一配置门店')
        categories = data_get['data']['categories']
        self.assertTrue(len(categories) >= 1)
        self.assertEqual(categories[0]['name'], '热咖啡')
        self.assertEqual(categories[0]['items'][0]['name'], '拿铁咖啡')
        self.assertEqual(categories[0]['items'][0]['skus'][0]['name'], '大杯/热')

        # POST
        res_post = self.client.post('/api/device/config', data={'device_sn': 'sn_unified_01', 'data': 'conf2'}, content_type='application/json')
        self.assertEqual(res_post.status_code, 200)
        self.assertEqual(res_post.json()['data']['categories'][0]['items'][0]['name'], '拿铁咖啡')

    def test_query_conf3_poster_get_and_post(self):
        # GET
        res_get = self.client.get('/api/device/config?device_sn=sn_unified_01&data=conf3')
        self.assertEqual(res_get.status_code, 200)
        data_get = res_get.json()
        self.assertEqual(data_get['code'], 0)
        self.assertEqual(data_get['data']['properties']['version'], 5)
        self.assertIn('poster', data_get['data'])

        # POST
        res_post = self.client.post('/api/device/config', data={'device_sn': 'sn_unified_01', 'data': 'conf3'}, content_type='application/json')
        self.assertEqual(res_post.status_code, 200)
        self.assertEqual(res_post.json()['data']['properties']['version'], 5)

    def test_query_conf2_non_existent_device(self):
        res = self.client.get('/api/device/config?device_sn=sn_not_found&data=conf2')
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()['code'], 3001)

    def test_receive_device_status_guard_refunded_order(self):
        """测试已退款/已取消的订单防硬件状态回调覆盖"""
        from orders.models import OrderMain
        from devices.views import receive_device_status

        user = User.objects.create(username='guard_test_user_1', role='user')
        order = OrderMain.objects.create(
            order_no='TEST_GUARD_REFUND_001',
            user=user,
            store=self.store,
            device=self.device,
            status=OrderMain.STATUS_REFUNDED
        )
        # 硬件上报 done
        payload = {
            'order_no': 'TEST_GUARD_REFUND_001',
            'status': 'done'
        }
        receive_device_status(self.device.device_sn, payload)
        order.refresh_from_db()
        # 验证：状态依然是 STATUS_REFUNDED，绝不会被覆写为 done
        self.assertEqual(order.status, OrderMain.STATUS_REFUNDED)

    def test_deduct_order_redis_ingredients(self):
        """测试出杯完成主动扣减 Redis 食材基准值 (防幽灵库存)"""
        from orders.models import OrderMain, OrderItem
        from orders.services import deduct_order_redis_ingredients, get_redis_stock_key
        from django_redis import get_redis_connection

        r = get_redis_connection('default')
        bean_key = get_redis_stock_key(self.device.device_sn, 'coffee_bean_test')
        r.set(bean_key, 1000)

        user = User.objects.create(username='guard_test_user_2', role='user')
        order = OrderMain.objects.create(
            order_no='TEST_PHANTOM_STOCK_001',
            user=user,
            store=self.store,
            device=self.device,
            status=OrderMain.STATUS_MAKING
        )
        item = OrderItem.objects.create(
            order=order,
            item=self.menu_item,
            item_name='拿铁咖啡',
            quantity=1,
            unit_price=1500,
            subtotal=1500
        )
        item.skus.add(self.menu_sku)

        deduct_order_redis_ingredients(order)

        # 单杯用量: 18g coffee_bean_test
        # 验证扣减: 1000 - 18 = 982
        self.assertEqual(int(r.get(bean_key)), 982)



