from django.test import TestCase, RequestFactory, Client
from django.utils import timezone
from stores.models import Store
from devices.models import Device
from .models import DeviceModel, GlobalMenuCategory, GlobalMenuItem, GlobalMenuSku, GlobalSkuIngredient
from menus.models import MenuItem


class DummyStorage:
    def __init__(self):
        self.messages = []

    def add(self, level, message, extra_tags=''):
        self.messages.append(message)


class GlobalMenuInheritanceTests(TestCase):
    def setUp(self):
        self.store = Store.objects.create(name="测试门店", status=Store.STATUS_OPEN)
        self.dev_type = DeviceModel.objects.create(name="测试设备类型", code="test_dev_type")
        
        # Link the store to a device of this type
        self.device = Device.objects.create(
            store=self.store,
            device_sn="TEST-SN-9999",
            device_name="测试设备",
            device_model=self.dev_type,
            status=Device.STATUS_ONLINE
        )
        
        from inventory.models import Material
        self.inv_material = Material.objects.create(
            name="浓缩咖啡液", code="espresso", unit="ml"
        )
        self.g_cat = GlobalMenuCategory.objects.create(
            device_model=self.dev_type, name="全局咖啡", sort_order=1, is_active=True
        )
        self.g_item = GlobalMenuItem.objects.create(
            category=self.g_cat, name="全局美式", base_price=1500, is_active=True
        )
        self.g_sku = GlobalMenuSku.objects.create(
            item=self.g_item, name="大杯/热", category="杯型", attributes={"size": "大", "temperature": "热"},
            price_delta=300, is_active=True
        )
        self.ingredient = GlobalSkuIngredient.objects.create(
            sku=self.g_sku, material=self.inv_material, quantity=60
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
        self.assertEqual(l_item.device_model, self.dev_type)

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
        self.assertEqual(len(skus), 2)
        sku_names = [s['name'] for s in skus]
        self.assertIn("标准", sku_names)
        self.assertIn("大杯/热", sku_names)

    def test_sync_with_unmatched_device_type(self):
        # Create a store with NO devices
        empty_store = Store.objects.create(name="空设备门店", status=Store.STATUS_OPEN)

        # Create a store with a DIFFERENT device type
        other_dev_type = DeviceModel.objects.create(name="别样设备类型", code="other_type")
        other_store = Store.objects.create(name="其他设备门店", status=Store.STATUS_OPEN)
        Device.objects.create(
            store=other_store,
            device_sn="TEST-SN-8888",
            device_name="其他测试设备",
            device_model=other_dev_type,
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
            device_model=self.dev_type,
            global_item=self.g_item,
            base_price=1000
        )
        with self.assertRaises(ValidationError):
            item_too_low.full_clean()

        # 验证价格过高 (2000) 会引发 ValidationError
        item_too_high = MenuItem(
            store=self.store,
            device_model=self.dev_type,
            global_item=self.g_item,
            base_price=2000
        )
        with self.assertRaises(ValidationError):
            item_too_high.full_clean()

        # 2. 设备类型一致性校验：MenuItem.device_model 必须与 global_item.category.device_model 一致
        other_dev_type = DeviceModel.objects.create(name="其他设备类型", code="other_dev_type")
        item_mismatch_type = MenuItem(
            store=self.store,
            device_model=other_dev_type,
            global_item=self.g_item,
            base_price=1500
        )
        with self.assertRaises(ValidationError):
            item_mismatch_type.full_clean()

        # 3. 验证价格和类型正确的 MenuItem 可以成功保存并校验通过
        valid_item = MenuItem.objects.create(
            store=self.store,
            device_model=self.dev_type,
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


class GlobalMenuItemTests(TestCase):
    def test_auto_insert_standard_sku(self):
        dev_type = DeviceModel.objects.create(name="设备类型", code="test_dev_type_unique")
        cat = GlobalMenuCategory.objects.create(device_model=dev_type, name="分类")
        
        # 创建一个没有 sku 的 GlobalMenuItem
        item = GlobalMenuItem.objects.create(
            category=cat,
            name="新品咖啡",
            base_price=1000
        )
        
        # 验证自动创建了“标准”规格
        self.assertTrue(item.skus.filter(name='标准').exists())
        standard_sku = item.skus.get(name='标准')
        self.assertEqual(standard_sku.category, 'default')
        self.assertEqual(standard_sku.price_delta, 0)


from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError

class ValidateDetailImageTests(TestCase):
    def test_image_size_validator(self):
        from .models import validate_detail_image
        # 1. 模拟超过 1M 的图片文件 (1.1 MB)
        large_file = SimpleUploadedFile("detail.png", b"x" * (1024 * 1024 + 100), content_type="image/png")
        with self.assertRaises(ValidationError) as ctx:
            validate_detail_image(large_file)
        self.assertIn("图片文件大小不能超过 1MB", str(ctx.exception))

    def test_png_width_validator(self):
        from .models import validate_detail_image
        from io import BytesIO
        from PIL import Image
        
        # 2. 模拟一个非 750px 宽度的 PNG (800x600)
        f_bad = BytesIO()
        Image.new('RGB', (800, 600)).save(f_bad, format='PNG')
        bad_png = SimpleUploadedFile("bad.png", f_bad.getvalue(), content_type="image/png")
        with self.assertRaises(ValidationError) as ctx:
            validate_detail_image(bad_png)
        self.assertIn("详情页图片宽度必须为 750 像素", str(ctx.exception))

        # 3. 模拟一个 750x1000 的 PNG (应该验证通过)
        f_good = BytesIO()
        Image.new('RGB', (750, 1000)).save(f_good, format='PNG')
        good_png = SimpleUploadedFile("good.png", f_good.getvalue(), content_type="image/png")
        # 应该不报错
        validate_detail_image(good_png)





from unittest.mock import patch
import datetime

class StoreBusinessHoursTests(TestCase):
    def test_store_service_without_business_hours(self):
        # 无营业时间，默认可提供服务
        store = Store.objects.create(name="全天营业店", status=Store.STATUS_OPEN)
        self.assertTrue(store.is_in_business_hours)
        self.assertTrue(store.can_provide_service)

    def test_store_service_not_open_status(self):
        # 即使在营业时间内，如果营业状态不是 STATUS_OPEN，就不能提供服务
        store = Store.objects.create(
            name="关闭门店",
            status=Store.STATUS_CLOSED,
            business_hours={"mon": "08:00-22:00", "tue": "08:00-22:00", "wed": "08:00-22:00", "thu": "08:00-22:00", "fri": "08:00-22:00", "sat": "08:00-22:00", "sun": "08:00-22:00"}
        )
        self.assertFalse(store.can_provide_service)

    @patch('django.utils.timezone.localtime')
    def test_store_service_in_and_out_of_hours(self, mock_localtime):
        # 设定当前为星期一的 10:00 (2026-06-22 是星期一)
        # now.weekday() == 0 (Mon), now.time() == 10:00
        mock_localtime.return_value = timezone.make_aware(datetime.datetime(2026, 6, 22, 10, 0, 0))
        
        store = Store.objects.create(
            name="周一早八晚十",
            status=Store.STATUS_OPEN,
            business_hours={"mon": "08:00-22:00"}
        )
        self.assertTrue(store.is_in_business_hours)
        self.assertTrue(store.can_provide_service)

        # 设定当前为星期一的 23:00 (超出营业时间)
        mock_localtime.return_value = timezone.make_aware(datetime.datetime(2026, 6, 22, 23, 0, 0))
        self.assertFalse(store.is_in_business_hours)
        self.assertFalse(store.can_provide_service)

    @patch('django.utils.timezone.localtime')
    def test_store_service_cross_day(self, mock_localtime):
        # 设定当前为周一晚上 23:00，营业时间为 22:00 到次日 02:00
        store = Store.objects.create(
            name="跨天夜宵店",
            status=Store.STATUS_OPEN,
            business_hours={"mon": "22:00-02:00"}
        )
        mock_localtime.return_value = timezone.make_aware(datetime.datetime(2026, 6, 22, 23, 0, 0))
        self.assertTrue(store.is_in_business_hours)
        self.assertTrue(store.can_provide_service)

        # 设定当前为周一凌晨 01:00 (这属于周一跨天的营业时间)
        mock_localtime.return_value = timezone.make_aware(datetime.datetime(2026, 6, 22, 1, 0, 0))
        self.assertTrue(store.is_in_business_hours)
        self.assertTrue(store.can_provide_service)

        # 设定当前为周一早上 08:00 (不在营业时间内)
        mock_localtime.return_value = timezone.make_aware(datetime.datetime(2026, 6, 22, 8, 0, 0))
        self.assertFalse(store.is_in_business_hours)
        self.assertFalse(store.can_provide_service)


class CxdPermissionsAndSyncTests(TestCase):
    def setUp(self):
        from users.models import User
        from stores.models import Store
        from devices.models import Device
        from global_config.models import DeviceModel, GlobalMenuCategory, GlobalMenuItem

        self.cxd_user = User.objects.create_superuser(username='cxd', password='password123')
        self.closed_store = Store.objects.create(name="未营业店", status=Store.STATUS_CLOSED)
        
        self.dev_type = DeviceModel.objects.create(name="咖啡机", code="coffee_maker")
        self.device = Device.objects.create(
            store=self.closed_store,
            device_sn="TEST-CLOSED-SN",
            device_name="设备",
            device_model=self.dev_type,
            status=Device.STATUS_ONLINE
        )
        self.g_cat = GlobalMenuCategory.objects.create(
            device_model=self.dev_type, name="咖啡", sort_order=1, is_active=True
        )
        self.g_item = GlobalMenuItem.objects.create(
            category=self.g_cat, name="美式", base_price=1000, is_active=True
        )

    def test_cxd_can_view_closed_store_menu(self):
        from rest_framework.test import APIClient
        
        client = APIClient()
        
        # Test anonymous or normal user: closed store returns 400
        response = client.get(f'/api/menu/store/{self.closed_store.id}')
        self.assertEqual(response.status_code, 400)
        
        # Log in as cxd
        client.force_authenticate(user=self.cxd_user)
        response = client.get(f'/api/menu/store/{self.closed_store.id}')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['code'], 0)
        self.assertEqual(data['data']['store_name'], "未营业店")

    def test_dashboard_callback(self):
        from global_config.dashboard import dashboard_callback
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get('/admin/')
        context = {}
        
        updated_context = dashboard_callback(request, context)
        self.assertIn("store_count", updated_context)
        self.assertIn("online_device_count", updated_context)
        self.assertIn("today_order_count", updated_context)
        self.assertIn("today_task_count", updated_context)
        self.assertEqual(updated_context["store_count"], 1)

