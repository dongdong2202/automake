from django.test import TestCase, RequestFactory, Client
from stores.models import Store
from devices.models import Device
from .models import DeviceType, GlobalMaterial, GlobalMenuCategory, GlobalMenuItem, GlobalMenuSku, GlobalSkuIngredient
from menus.models import MenuItem


class DummyStorage:
    def __init__(self):
        self.messages = []

    def add(self, level, message, extra_tags=''):
        self.messages.append(message)


class GlobalMenuInheritanceTests(TestCase):
    def setUp(self):
        self.store = Store.objects.create(name="测试门店", status=Store.STATUS_OPEN)
        self.dev_type = DeviceType.objects.create(name="测试设备类型", code="test_dev_type")
        
        # Link the store to a device of this type
        self.device = Device.objects.create(
            store=self.store,
            device_sn="TEST-SN-9999",
            device_name="测试设备",
            device_type=self.dev_type,
            status=Device.STATUS_ONLINE
        )
        
        self.g_material = GlobalMaterial.objects.create(
            name="浓缩咖啡液", code="espresso", unit="ml"
        )
        self.g_cat = GlobalMenuCategory.objects.create(
            device_type=self.dev_type, name="全局咖啡", sort_order=1, is_active=True
        )
        self.g_item = GlobalMenuItem.objects.create(
            category=self.g_cat, name="全局美式", base_price=1500, is_active=True
        )
        self.g_sku = GlobalMenuSku.objects.create(
            item=self.g_item, name="大杯/热", category="杯型", attributes={"size": "大", "temperature": "热"},
            price_delta=300, is_active=True
        )
        self.ingredient = GlobalSkuIngredient.objects.create(
            sku=self.g_sku, material=self.g_material, quantity=60
        )

    def test_sync_global_menu_action(self):
        # Trigger the sync logic
        from stores.admin import StoreAdmin
        from django.contrib.admin.sites import AdminSite
        
        site = AdminSite()
        admin = StoreAdmin(Store, site)
        
        # Create a mock request and attach the message storage dummy
        factory = RequestFactory()
        request = factory.get('/admin/stores/store/')
        request._messages = DummyStorage()
        
        # Call the sync action directly
        admin.sync_global_menu(request, Store.objects.all())
        
        # Verify MenuItem exists locally and is linked correctly
        self.assertTrue(MenuItem.objects.filter(store=self.store, global_item=self.g_item).exists())
        l_item = MenuItem.objects.get(store=self.store, global_item=self.g_item)
        self.assertEqual(l_item.base_price, 1500)
        self.assertEqual(l_item.device_type, self.dev_type)

        # Verify store menu API serializes the dynamic tree correctly
        client = Client()
        response = client.get(f'/api/menu/store/{self.store.id}')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['code'], 0)
        
        # Verify categories grouping
        categories = data['data']['categories']
        self.assertEqual(len(categories), 1)
        self.assertEqual(categories[0]['name'], "全局咖啡")
        
        # Verify items
        items = categories[0]['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['name'], "全局美式")
        self.assertEqual(items[0]['base_price'], 1500)
        
        # Verify SKUs
        skus = items[0]['skus']
        self.assertEqual(len(skus), 1)
        self.assertEqual(skus[0]['name'], "大杯/热")
        self.assertEqual(skus[0]['category'], "杯型")
        self.assertEqual(skus[0]['price_delta'], 300)

    def test_sync_with_unmatched_device_type(self):
        # Create a store with NO devices
        empty_store = Store.objects.create(name="空设备门店", status=Store.STATUS_OPEN)

        # Create a store with a DIFFERENT device type
        other_dev_type = DeviceType.objects.create(name="别样设备类型", code="other_type")
        other_store = Store.objects.create(name="其他设备门店", status=Store.STATUS_OPEN)
        Device.objects.create(
            store=other_store,
            device_sn="TEST-SN-8888",
            device_name="其他测试设备",
            device_type=other_dev_type,
            status=Device.STATUS_ONLINE
        )

        # Trigger sync action
        from stores.admin import StoreAdmin
        from django.contrib.admin.sites import AdminSite
        site = AdminSite()
        admin = StoreAdmin(Store, site)
        factory = RequestFactory()
        request = factory.get('/admin/stores/store/')
        request._messages = DummyStorage()

        admin.sync_global_menu(request, Store.objects.filter(id__in=[empty_store.id, other_store.id]))

        # Verify neither store inherits the global item because their device types do not match/exist
        self.assertFalse(MenuItem.objects.filter(store=empty_store, global_item=self.g_item).exists())
        self.assertFalse(MenuItem.objects.filter(store=other_store, global_item=self.g_item).exists())

    def test_local_menu_integrity_constraints(self):
        from django.core.exceptions import ValidationError

        # 1. 价格区间验证：全局价格为 1500 分，微调下限为 1200 分，微调上限为 1800 分
        
        # 验证价格过低 (1000) 会引发 ValidationError
        item_too_low = MenuItem(
            store=self.store,
            device_type=self.dev_type,
            global_item=self.g_item,
            base_price=1000
        )
        with self.assertRaises(ValidationError):
            item_too_low.full_clean()

        # 验证价格过高 (2000) 会引发 ValidationError
        item_too_high = MenuItem(
            store=self.store,
            device_type=self.dev_type,
            global_item=self.g_item,
            base_price=2000
        )
        with self.assertRaises(ValidationError):
            item_too_high.full_clean()

        # 2. 设备类型一致性校验：MenuItem.device_type 必须与 global_item.category.device_type 一致
        other_dev_type = DeviceType.objects.create(name="其他设备类型", code="other_dev_type")
        item_mismatch_type = MenuItem(
            store=self.store,
            device_type=other_dev_type,
            global_item=self.g_item,
            base_price=1500
        )
        with self.assertRaises(ValidationError):
            item_mismatch_type.full_clean()

        # 3. 验证价格和类型正确的 MenuItem 可以成功保存并校验通过
        valid_item = MenuItem.objects.create(
            store=self.store,
            device_type=self.dev_type,
            global_item=self.g_item,
            base_price=1500
        )
        valid_item.full_clean()  # should not raise

        # 4. MenuSku 校验：价格增量 & 最终价格在全局最终售价的 ±20% 范围内
        from menus.models import MenuSku
        # 全局最终售价为 1500 + 300 = 1800，允许的范围为 1440 ~ 2160
        
        # 最终售价过低 (1500 + (-100) = 1400) -> 失败
        sku_too_low = MenuSku(
            item=valid_item,
            global_sku=self.g_sku,
            price_delta=-100
        )
        with self.assertRaises(ValidationError):
            sku_too_low.full_clean()

        # 最终售价过高 (1500 + 700 = 2200) -> 失败
        sku_too_high = MenuSku(
            item=valid_item,
            global_sku=self.g_sku,
            price_delta=700
        )
        with self.assertRaises(ValidationError):
            sku_too_high.full_clean()

        # 最终售价在范围内 (1500 + 0 = 1500) -> 成功
        sku_valid = MenuSku(
            item=valid_item,
            global_sku=self.g_sku,
            price_delta=0
        )
        sku_valid.full_clean()  # should not raise

        # 5. MenuSku 校验：global_sku 必须与 MenuItem 的 global_item 对应
        other_item = GlobalMenuItem.objects.create(
            category=self.g_cat, name="其他全局商品", base_price=1000, is_active=True
        )
        other_sku = GlobalMenuSku.objects.create(
            item=other_item, name="规格", price_delta=0, is_active=True
        )
        sku_mismatch = MenuSku(
            item=valid_item,
            global_sku=other_sku,
            price_delta=0
        )
        with self.assertRaises(ValidationError):
            sku_mismatch.full_clean()
