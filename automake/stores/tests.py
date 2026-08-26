from django.test import TestCase
from .models import Store

class StoreModelTests(TestCase):
    def test_create_store_with_code(self):
        """测试使用 code 成功新增/添加门店"""
        store = Store.objects.create(
            name='西二旗智能旗舰店',
            code='STORE_XEQ_001',
            address='北京市海淀区',
            lat=40.056,
            lng=116.307,
            contact_phone='13812345678',
            status=Store.STATUS_OPEN
        )
        self.assertEqual(store.name, '西二旗智能旗舰店')
        self.assertEqual(store.code, 'STORE_XEQ_001')
        self.assertEqual(store.status, 'open')
        self.assertTrue(Store.objects.filter(code='STORE_XEQ_001').exists())

