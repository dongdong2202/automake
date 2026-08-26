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
        self.assertFalse(dev_closed_data['is_in_business_hours'])
        self.assertEqual(dev_closed_data['business_status'], '今日休息')
        self.assertEqual(dev_closed_data['business_status_text'], '今日休息')

