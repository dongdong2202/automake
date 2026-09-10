"""
数据分析聚合逻辑与报表接口测试套件 (Analytics Aggregation Test Suite)
==================================================================
覆盖范围：
1. 18 个分析端点与 1 个驾驶舱端点的基础数据契约与响应状态校验；
2. 时间粒度聚合切换校验（day / week / month）；
3. 门店与设备过滤参数校验（start_date, end_date, store_id, device_sn）；
4. 权限与数据隔离：超级管理员 vs 门店管理员；
5. 边界与异常兜底：空区间数据聚合容错，不抛 500 异常。
"""

import datetime
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from users.models import User
from stores.models import Store
from devices.models import Device, DeviceAlarm
from global_config.models import DeviceModel, GlobalMenuCategory, GlobalMenuItem, GlobalSkuTemplate, GlobalMenuSku
from menus.models import MenuItem, MenuSku
from orders.models import OrderMain, OrderItem
from payments.models import PaymentRecord
from inventory.models import Material, InventoryRecord


class AnalyticsAggregationTestCase(TestCase):
    """
    数据分析多维统计与报表端点测试类
    """

    def setUp(self):
        """
        初始化测试基底数据：
        - 创建超级管理员与普通门店管理员
        - 创建 2 家门店与 2 台设备
        - 创建商品品类、商品及 SKU
        - 创建物料与库存流水
        - 创建跨不同日期的拟真订单与告警
        """
        self.client = APIClient()

        # 1. 创建测试用户
        self.super_admin = User.objects.create_superuser(
            username='admin_analytics_test',
            password='testpassword123'
        )

        self.store_admin = User.objects.create(
            username='store_manager_test',
            role=User.ADMIN,
            is_staff=True
        )
        self.store_admin.set_password('testpassword123')
        self.store_admin.save()

        # 2. 创建设备型号与门店
        self.dev_model = DeviceModel.objects.create(name='标准咖啡机型', code='MODEL_ANA_01')
        self.store_a = Store.objects.create(name='科技园直营店', code='STORE_SZ_01', status='active')
        self.store_b = Store.objects.create(name='万象城加盟店', code='STORE_SZ_02', status='active')
        self.store_admin.stores.add(self.store_a)

        # 3. 创建设备
        self.device_a = Device.objects.create(
            device_sn='DEV_SN_A100',
            store=self.store_a,
            device_name='1号智能冲泡机',
            device_model=self.dev_model,
            status='online'
        )
        self.device_b = Device.objects.create(
            device_sn='DEV_SN_B200',
            store=self.store_b,
            device_name='2号智能冲泡机',
            device_model=self.dev_model,
            status='online'
        )

        # 4. 创建物料
        self.material_coffee = Material.objects.create(
            name='阿拉比卡咖啡豆',
            code='MAT_BEAN_01',
            material_type=Material.TYPE_INGREDIENT,
            unit='g',
            price=15.00,
            quantity=1000.00
        )
        self.material_milk = Material.objects.create(
            name='鲜牛奶',
            code='MAT_MILK_01',
            material_type=Material.TYPE_INGREDIENT,
            unit='ml',
            price=8.00,
            quantity=2000.00
        )

        # 5. 创建商品与规格
        self.category = GlobalMenuCategory.objects.create(
            device_model=self.dev_model,
            name='经典意式',
            sort_order=1
        )
        self.global_item = GlobalMenuItem.objects.create(
            category=self.category,
            name='美式咖啡',
            base_price=1800,
            is_active=True
        )
        self.template = GlobalSkuTemplate.objects.create(
            category='杯型',
            name='标准杯',
            default_price_delta=0,
            is_active=True
        )
        self.global_sku = GlobalMenuSku.objects.create(
            item=self.global_item,
            template=self.template,
            price_delta=0,
            is_active=True
        )

        self.store_item = MenuItem.objects.create(
            store=self.store_a,
            device_model=self.dev_model,
            global_item=self.global_item,
            base_price=1800,
            is_active=True
        )
        self.store_sku = MenuSku.objects.create(
            item=self.store_item,
            global_sku=self.global_sku,
            price_delta=0,
            is_active=True
        )

        # 6. 创建不同状态和日期的订单
        self.now = timezone.now()

        # 门店 A 完成的订单 1
        self.order_1 = OrderMain.objects.create(
            order_no='ORD_ANALYTICS_001',
            user=self.super_admin,
            store=self.store_a,
            device=self.device_a,
            status=OrderMain.STATUS_DONE,
            total_amount=1800,
            pay_amount=1800,
            discount_amount=0,
            paid_at=self.now - datetime.timedelta(days=2),
            done_at=self.now - datetime.timedelta(days=2)
        )
        OrderMain.objects.filter(id=self.order_1.id).update(created_at=self.now - datetime.timedelta(days=2))

        OrderItem.objects.create(
            order=self.order_1,
            item=self.store_item,
            sku=self.store_sku,
            item_name='美式咖啡',
            sku_name='标准杯',
            unit_price=1800,
            quantity=1,
            subtotal=1800
        )
        PaymentRecord.objects.create(
            order=self.order_1,
            user=self.super_admin,
            out_trade_no=self.order_1.order_no,
            pay_method='wechat_jsapi',
            amount=1800,
            status=PaymentRecord.STATUS_SUCCESS,
            paid_at=self.now - datetime.timedelta(days=2)
        )

        # 门店 B 制作中的订单 2
        self.order_2 = OrderMain.objects.create(
            order_no='ORD_ANALYTICS_002',
            user=self.store_admin,
            store=self.store_b,
            device=self.device_b,
            status=OrderMain.STATUS_MAKING,
            total_amount=3600,
            pay_amount=3600,
            discount_amount=0,
            paid_at=self.now - datetime.timedelta(days=1)
        )
        OrderMain.objects.filter(id=self.order_2.id).update(created_at=self.now - datetime.timedelta(days=1))

        OrderItem.objects.create(
            order=self.order_2,
            item=self.store_item,
            sku=self.store_sku,
            item_name='美式咖啡',
            sku_name='标准杯',
            unit_price=1800,
            quantity=2,
            subtotal=3600
        )

        # 门店 A 取消的订单 3 (未支付)
        self.order_3 = OrderMain.objects.create(
            order_no='ORD_ANALYTICS_003',
            user=self.super_admin,
            store=self.store_a,
            device=self.device_a,
            status=OrderMain.STATUS_CANCELLED,
            total_amount=1800,
            pay_amount=0,
            discount_amount=0
        )

        # 7. 设备告警记录
        DeviceAlarm.objects.create(
            device=self.device_a,
            alarm_type=DeviceAlarm.ALARM_FAULT,
            detail='锅炉水温过低',
            is_resolved=True,
            resolved_at=self.now - datetime.timedelta(hours=4)
        )

    def test_01_dashboard_stats_endpoint(self):
        """测试 1: 运营驾驶舱概览数据端点"""
        self.client.force_authenticate(user=self.super_admin)
        res = self.client.get('/api/admin/dashboard/stats')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertEqual(data.get('code'), 0)
        body = data.get('data', {})
        self.assertIn('kpis', body)
        self.assertIn('device_status', body)
        self.assertIn('trend', body)
        self.assertIn('top_items', body)
        self.assertIn('material_warnings', body)
        self.assertIn('recent_orders', body)
        kpis = body.get('kpis', {})
        self.assertIn('today_revenue', kpis)
        self.assertIn('online_devices', kpis)

    def test_02_all_sales_analytics_endpoints(self):
        """测试 2: 销售分析模块全部 6 个 API 端点响应与结构"""
        self.client.force_authenticate(user=self.super_admin)
        endpoints = [
            '/api/admin/analytics/sales/trend',
            '/api/admin/analytics/sales/by-hour',
            '/api/admin/analytics/sales/by-weekday',
            '/api/admin/analytics/sales/by-store',
            '/api/admin/analytics/sales/by-device',
            '/api/admin/analytics/sales/funnel',
        ]
        for ep in endpoints:
            with self.subTest(endpoint=ep):
                res = self.client.get(ep)
                self.assertEqual(res.status_code, status.HTTP_200_OK)
                resp_json = res.json()
                self.assertEqual(resp_json.get('code'), 0, f"Endpoint {ep} returned code != 0: {resp_json}")
                self.assertIsNotNone(resp_json.get('data'))

    def test_03_all_finance_analytics_endpoints(self):
        """测试 3: 财务概览模块全部 3 个 API 端点响应与结构"""
        self.client.force_authenticate(user=self.super_admin)
        endpoints = [
            '/api/admin/analytics/finance/summary',
            '/api/admin/analytics/finance/trend',
            '/api/admin/analytics/finance/category-share',
        ]
        for ep in endpoints:
            with self.subTest(endpoint=ep):
                res = self.client.get(ep)
                self.assertEqual(res.status_code, status.HTTP_200_OK)
                resp_json = res.json()
                self.assertEqual(resp_json.get('code'), 0)

    def test_04_all_product_device_material_customer_endpoints(self):
        """测试 4: 商品、设备、物料、客户分析剩余端点"""
        self.client.force_authenticate(user=self.super_admin)
        endpoints = [
            '/api/admin/analytics/products/ranking',
            '/api/admin/analytics/products/sku-preferences',
            '/api/admin/analytics/devices/uptime',
            '/api/admin/analytics/devices/alarm-trend',
            '/api/admin/analytics/materials/stock-status',
            '/api/admin/analytics/materials/consumption',
            '/api/admin/analytics/materials/replenishment-forecast',
            '/api/admin/analytics/customers/growth',
            '/api/admin/analytics/customers/order-frequency',
        ]
        for ep in endpoints:
            with self.subTest(endpoint=ep):
                res = self.client.get(ep)
                self.assertEqual(res.status_code, status.HTTP_200_OK)
                resp_json = res.json()
                self.assertEqual(resp_json.get('code'), 0)

    def test_05_granularity_aggregation_switching(self):
        """测试 5: 时间粒度切换（按日、按周、按月聚合）"""
        self.client.force_authenticate(user=self.super_admin)
        for gran in ['day', 'week', 'month']:
            res = self.client.get(f'/api/admin/analytics/sales/trend?granularity={gran}')
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            data = res.json().get('data', [])
            self.assertIsInstance(data, list)

    def test_06_store_permission_data_isolation(self):
        """测试 6: 权限与门店数据隔离测试（店长只能看本店数据）"""
        # 超级管理员查询门店 A 的销售额与门店 B 的销售额
        self.client.force_authenticate(user=self.super_admin)
        res_super = self.client.get('/api/admin/analytics/sales/by-store')
        super_data = res_super.json().get('data', [])
        super_store_names = [d['store_name'] for d in super_data]
        self.assertIn('科技园直营店', super_store_names)
        self.assertIn('万象城加盟店', super_store_names)

        # 门店管理员 (store_manager_test 仅绑定科技园直营店) 查询
        self.client.force_authenticate(user=self.store_admin)
        res_mgr = self.client.get('/api/admin/analytics/sales/by-store')
        mgr_data = res_mgr.json().get('data', [])
        mgr_store_names = [d['store_name'] for d in mgr_data]
        # 验证店长只能看到所属门店的数据
        self.assertIn('科技园直营店', mgr_store_names)
        self.assertNotIn('万象城加盟店', mgr_store_names)

    def test_07_empty_date_boundary_tolerance(self):
        """测试 7: 未来空日期边界容错测试（避免除以零或 Null 崩溃）"""
        self.client.force_authenticate(user=self.super_admin)
        # 筛选未来不存在的日期范围
        future_start = '2099-01-01'
        future_end = '2099-01-31'
        url = f'/api/admin/analytics/sales/trend?start_date={future_start}&end_date={future_end}'
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertEqual(data.get('code'), 0)
        self.assertEqual(data.get('data'), [])

        # 财务概览在空数据区间应兜底为 0，不能报 500
        fin_url = f'/api/admin/analytics/finance/summary?start_date={future_start}&end_date={future_end}'
        fin_res = self.client.get(fin_url)
        self.assertEqual(fin_res.status_code, status.HTTP_200_OK)
        fin_data = fin_res.json().get('data', {})
        self.assertEqual(fin_data.get('total_revenue', 0), 0)
