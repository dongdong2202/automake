import json
from decimal import Decimal
from django.test import TestCase, Client
from django_redis import get_redis_connection

from stores.models import Store
from devices.models import Device, DeviceBarrelDict, DeviceMaterialStock
from inventory.models import Material
from global_config.models import DeviceModel, GlobalMenuCategory, GlobalMenuItem, GlobalSkuTemplate, GlobalMenuSku, GlobalSkuIngredient
from menus.models import MenuItem, MenuSku
from menus.services import calculate_device_sold_out_items


class MenuSoldOutServiceAndApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.redis_conn = get_redis_connection("default")
        self.redis_conn.flushdb()

        # 1. 创建门店与设备
        self.store = Store.objects.create(
            name="售罄测试旗舰店",
            address="北京市朝阳区酒仙桥路10号",
            status=Store.STATUS_OPEN,
            code="STORE-SOLDOUT-01"
        )
        self.dev_model, _ = DeviceModel.objects.get_or_create(name="全自动多料桶咖啡机", code="coffee_robot_v2")
        self.device = Device.objects.create(
            store=self.store,
            device_sn="sn_soldout_001",
            device_name="智能茶饮机1号",
            device_model=self.dev_model,
            status=Device.STATUS_ONLINE,
            key_code="DEV-SOLDOUT-01"
        )

        # 2. 创建物料
        self.mat_bean, _ = Material.objects.get_or_create(code="coffee_bean", defaults={"name": "咖啡豆", "unit": "g", "material_type": "solid"})
        self.mat_milk, _ = Material.objects.get_or_create(code="fresh_milk", defaults={"name": "鲜牛奶", "unit": "ml", "material_type": "thin"})
        self.mat_matcha, _ = Material.objects.get_or_create(code="matcha", defaults={"name": "抹茶粉", "unit": "g", "material_type": "solid"})
        self.mat_cup, _ = Material.objects.get_or_create(code="paperL", defaults={"name": "纸大杯", "unit": "个", "material_type": "cup"})

        # 3. 创建多料桶字典映射：
        # b01: 咖啡豆
        # b02: 鲜牛奶 (桶1)
        # b03: 鲜牛奶 (桶2) —— 多料桶存放同种物料
        # b04: 抹茶粉
        DeviceBarrelDict.objects.create(device=self.device, barrel_code="b01", material=self.mat_bean)
        DeviceBarrelDict.objects.create(device=self.device, barrel_code="b02", material=self.mat_milk)
        DeviceBarrelDict.objects.create(device=self.device, barrel_code="b03", material=self.mat_milk)
        DeviceBarrelDict.objects.create(device=self.device, barrel_code="b04", material=self.mat_matcha)

        # 4. 创建耗材库存 (MySQL)
        from devices.models import DeviceConsumableStock
        self.consumable_cup = DeviceConsumableStock.objects.create(
            device=self.device,
            code=self.mat_cup,
            init_quantity=100,
            quantity=100,
            warn_level=15
        )

        # 5. 创建菜单商品与配料
        self.category = GlobalMenuCategory.objects.create(device_model=self.dev_model, name="现磨现制", sort_order=1, is_active=True)
        
        # 商品 1: 大师拿铁 (需要 咖啡豆 15g + 鲜牛奶 150ml + 大纸杯 1个)
        self.g_latte = GlobalMenuItem.objects.create(category=self.category, name="大师拿铁", base_price=1800, is_active=True)
        self.tpl_l = GlobalSkuTemplate.objects.create(name="大杯/热", category="规格", default_price_delta=0, is_active=True)
        self.sku_latte = GlobalMenuSku.objects.create(item=self.g_latte, template=self.tpl_l, price_delta=0, is_active=True)
        GlobalSkuIngredient.objects.create(sku=self.sku_latte, material=self.mat_bean, quantity=15)
        GlobalSkuIngredient.objects.create(sku=self.sku_latte, material=self.mat_milk, quantity=150)
        GlobalSkuIngredient.objects.create(sku=self.sku_latte, material=self.mat_cup, quantity=1)

        # 商品 2: 经典美式 (需要 咖啡豆 18g + 大纸杯 1个)
        self.g_americano = GlobalMenuItem.objects.create(category=self.category, name="经典美式", base_price=1200, is_active=True)
        self.sku_americano = GlobalMenuSku.objects.create(item=self.g_americano, template=self.tpl_l, price_delta=0, is_active=True)
        GlobalSkuIngredient.objects.create(sku=self.sku_americano, material=self.mat_bean, quantity=18)
        GlobalSkuIngredient.objects.create(sku=self.sku_americano, material=self.mat_cup, quantity=1)

        # 商品 3: 宇治抹茶拿铁 (需要 抹茶粉 12g + 鲜牛奶 200ml + 大纸杯 1个)
        self.g_matcha = GlobalMenuItem.objects.create(category=self.category, name="宇治抹茶拿铁", base_price=2200, is_active=True)
        self.sku_matcha = GlobalMenuSku.objects.create(item=self.g_matcha, template=self.tpl_l, price_delta=0, is_active=True)
        GlobalSkuIngredient.objects.create(sku=self.sku_matcha, material=self.mat_matcha, quantity=12)
        GlobalSkuIngredient.objects.create(sku=self.sku_matcha, material=self.mat_milk, quantity=200)
        GlobalSkuIngredient.objects.create(sku=self.sku_matcha, material=self.mat_cup, quantity=1)

        # 同步门店菜单
        MenuItem.sync_store_menu(self.store)
        self.item_latte = MenuItem.objects.get(store=self.store, global_item=self.g_latte)
        self.item_americano = MenuItem.objects.get(store=self.store, global_item=self.g_americano)
        self.item_matcha = MenuItem.objects.get(store=self.store, global_item=self.g_matcha)

    def test_single_material_shortage_causes_drink_sold_out(self):
        """测试单料桶抹茶粉不足 500ml/g 时，抹茶拿铁售罄，拿铁与美式正常"""
        # 设置 Redis 库存：咖啡豆 1000g, 鲜牛奶 5000ml, 抹茶粉 450g (< 500)
        self.redis_conn.set("automake:stock:sn_soldout_001:coffee_bean", "1000")
        self.redis_conn.set("automake:stock:sn_soldout_001:fresh_milk", "5000")
        self.redis_conn.set("automake:stock:sn_soldout_001:matcha", "450")  # < 500

        res = calculate_device_sold_out_items("sn_soldout_001")
        sold_out_ids = res["sold_out_item_ids"]

        self.assertEqual(res["device_sn"], "sn_soldout_001")
        # 抹茶拿铁必须售罄
        self.assertIn(self.item_matcha.id, sold_out_ids)
        # 美式和拿铁物料充足，绝不能判定售罄
        self.assertNotIn(self.item_latte.id, sold_out_ids)
        self.assertNotIn(self.item_americano.id, sold_out_ids)

    def test_multi_barrel_aggregation_for_same_material(self):
        """测试多桶装相同物料 (b02 与 b03 鲜牛奶) 聚合计算售罄（以 500ml 为界）"""
        # 场景 A: b02 剩 300ml, b03 剩 300ml -> 总量 600ml >= 500 -> 拿铁不售罄
        mock_snapshot_sufficient = {
            "materials": {
                "coffee_bean": {"total_volume": 1000},
                "fresh_milk": {"total_volume": 600},  # 300 + 300 = 600 >= 500
                "matcha": {"total_volume": 1500}
            }
        }
        self.redis_conn.set("automake:monitor:snapshot:sn_soldout_001", json.dumps(mock_snapshot_sufficient))
        # 删除独立 key 确保走快照多桶聚合
        self.redis_conn.delete("automake:stock:sn_soldout_001:fresh_milk")

        res_a = calculate_device_sold_out_items("sn_soldout_001")
        self.assertNotIn(self.item_latte.id, res_a["sold_out_item_ids"])

        # 场景 B: b02 剩 200ml, b03 剩 250ml -> 总量 450ml < 500 -> 拿铁与抹茶拿铁售罄，美式不售罄
        mock_snapshot_shortage = {
            "materials": {
                "coffee_bean": {"total_volume": 1000},
                "fresh_milk": {"total_volume": 450},   # 200 + 250 = 450 < 500
                "matcha": {"total_volume": 1500}
            }
        }
        self.redis_conn.set("automake:monitor:snapshot:sn_soldout_001", json.dumps(mock_snapshot_shortage))

        res_b = calculate_device_sold_out_items("sn_soldout_001")
        self.assertIn(self.item_latte.id, res_b["sold_out_item_ids"])
        self.assertIn(self.item_matcha.id, res_b["sold_out_item_ids"])
        self.assertNotIn(self.item_americano.id, res_b["sold_out_item_ids"])

    def test_cup_consumable_sold_out_via_mysql(self):
        """测试杯型耗材通过 MySQL quantity <= 0 触发售罄"""
        self.redis_conn.set("automake:stock:sn_soldout_001:coffee_bean", "1000")
        self.redis_conn.set("automake:stock:sn_soldout_001:fresh_milk", "5000")
        self.redis_conn.set("automake:stock:sn_soldout_001:matcha", "1000")

        # 将 MySQL 中的纸杯数量设为 0
        self.consumable_cup.quantity = 0
        self.consumable_cup.save()

        res = calculate_device_sold_out_items("sn_soldout_001")
        # 所有使用纸大杯的商品均售罄
        self.assertIn(self.item_latte.id, res["sold_out_item_ids"])
        self.assertIn(self.item_americano.id, res["sold_out_item_ids"])
        self.assertIn(self.item_matcha.id, res["sold_out_item_ids"])

    def test_sold_out_api_endpoints(self):
        """测试饮品售罄专有接口 /api/menu/sold-out/{device_sn} 与菜单综合接口"""
        self.redis_conn.set("automake:stock:sn_soldout_001:coffee_bean", "1000")
        self.redis_conn.set("automake:stock:sn_soldout_001:fresh_milk", "5000")
        self.redis_conn.set("automake:stock:sn_soldout_001:matcha", "450")  # < 500

        # 1. 测试专有售罄接口 GET /api/menu/sold-out/{device_sn}
        res = self.client.get('/api/menu/sold-out/sn_soldout_001')
        self.assertEqual(res.status_code, 200)
        data = res.json().get('data', {})
        self.assertEqual(data.get('device_sn'), 'sn_soldout_001')
        self.assertIn(self.item_matcha.id, data.get('sold_out_item_ids', []))

        # 2. 测试查询参数形式 GET /api/menu/sold-out?device_sn=sn_soldout_001
        res_query = self.client.get('/api/menu/sold-out?device_sn=sn_soldout_001')
        self.assertEqual(res_query.status_code, 200)
        data_query = res_query.json().get('data', {})
        self.assertIn(self.item_matcha.id, data_query.get('sold_out_item_ids', []))

        # 3. 测试完整菜单接口 GET /api/menu/store/sn_soldout_001 中直接标记 is_sold_out
        res_menu = self.client.get('/api/menu/store/sn_soldout_001')
        self.assertEqual(res_menu.status_code, 200)
        menu_data = res_menu.json().get('data', {})
        self.assertIn(self.item_matcha.id, menu_data.get('sold_out_item_ids', []))
        
        categories = menu_data.get('categories', [])
        self.assertTrue(len(categories) > 0)
        all_items = []
        for cat in categories:
            all_items.extend(cat.get('items', []))

        matcha_item = next(i for i in all_items if i['id'] == self.item_matcha.id)
        americano_item = next(i for i in all_items if i['id'] == self.item_americano.id)
        
        self.assertTrue(matcha_item.get('is_sold_out'))
        self.assertFalse(americano_item.get('is_sold_out'))

    def test_issue_empty_command(self):
        """测试向上位机下发缺货通知 (MQTT issue_empty_command)"""
        from unittest.mock import patch
        from mqtt import issue_empty_command

        # 模拟 MQTT 发送测试 issue_empty_command
        with patch('mqtt.get_mqtt_client') as mock_get_client:
            mock_client = mock_get_client.return_value
            mock_client.publish.return_value.rc = 0

            # 显式指定缺货 menu_ids=[1, 3, 5]
            success = issue_empty_command(
                device_sn="sn_soldout_001",
                menu_ids=[1, 3, 5],
                reason="物料不足"
            )
            self.assertTrue(success)
            mock_client.publish.assert_called()

            # 验证发布的主题与载荷格式
            call_args = mock_client.publish.call_args
            topic = call_args[0][0]
            payload = json.loads(call_args[0][1])

            self.assertEqual(topic, "s2c/shop/sn_soldout_001/state/command")
            self.assertEqual(payload.get("code"), 0)
            self.assertEqual(payload.get("message"), "缺货通知已下发给上位机")
            self.assertEqual(payload.get("data", {}).get("type"), "empty")
            self.assertEqual(payload.get("data", {}).get("menu_ids"), [1, 3, 5])
            self.assertEqual(payload.get("data", {}).get("reason"), "物料不足")
