import json
from unittest.mock import patch, MagicMock
from decimal import Decimal
from django.test import TestCase, Client
from django.utils import timezone
from django_redis import get_redis_connection

from stores.models import Store
from devices.models import Device, DeviceBarrelDict, DeviceMaterialStock, DeviceAlarm
from inventory.models import Material
from monitor.models import DeviceMonitorSnapshot
from monitor.services import process_device_status_report, parse_device_status_payload


class MonitorAndDeviceStatusTests(TestCase):
    def setUp(self):
        self.client = Client()
        redis_conn = get_redis_connection("default")
        redis_conn.flushdb()
        self.store = Store.objects.create(
            name="中关村智慧门店",
            address="北京市海淀区中关村大街1号",
            contact_phone="13911112222",
            code="STORE-ZGC-01",
            status=Store.STATUS_OPEN
        )
        self.device = Device.objects.create(
            store=self.store,
            device_sn="SN-TEST-ZGC-01",
            device_name="智能咖啡机1号",
            status=Device.STATUS_ONLINE,
            key_code="STORE-ZGC-01"
        )

        # 创建基础物料
        self.mat_milk, _ = Material.objects.get_or_create(
            code="fresh_milk", defaults={"name": "鲜牛奶", "unit": "ml", "material_type": "thin"}
        )
        self.mat_syrup, _ = Material.objects.get_or_create(
            code="vanilla_syrup", defaults={"name": "香草糖浆", "unit": "ml", "material_type": "thick"}
        )
        self.mat_cup, _ = Material.objects.get_or_create(
            code="paperL", defaults={"name": "纸大杯", "unit": "个", "material_type": "cup"}
        )

        # 配置料桶字典：b01 和 b02 均存放同一物料 fresh_milk (相同code多桶存放)
        DeviceBarrelDict.objects.create(
            device=self.device, barrel_code="b01", material=self.mat_milk
        )
        DeviceBarrelDict.objects.create(
            device=self.device, barrel_code="b02", material=self.mat_milk
        )
        # b09 存放香草糖浆
        DeviceBarrelDict.objects.create(
            device=self.device, barrel_code="b09", material=self.mat_syrup
        )

        # 配置预警阈值
        DeviceMaterialStock.objects.create(
            device=self.device, name=self.mat_milk, code="fresh_milk", warn_level=50.0
        )

    def test_multi_barrel_material_aggregation(self):
        """测试多料桶相同物料 code 的合并累加及 Redis 存储"""
        raw_payload = {
            "healthy": 1,
            "disconnected": 0,
            "free": {"master": 1024, "slave": 64},
            "temperature": {"t1": 4, "t2": 175},
            "ice": {"a1": 0, "a2": 0, "a3": 0},
            "transfer": {"a1": 0},
            "cup": {
                "plasticL": {"a1": 0, "a2": 0},
                "plasticM": {"a1": 0, "a2": 0},
                "paperL": {"a1": 0, "a2": 0},
                "paperM": {"a1": 0, "a2": 0},
                "membrane": {"a1": 0, "a2": 0},
                "lid": {"a1": 0, "a2": 0}
            },
            "thinP": {
                "b01": {"v": 20000, "a1": 0},
                "b02": {"v": 15000, "a1": 0},
                "b03": {"v": 10000, "a1": 0}
            },
            "thickP": {
                "b09": {"v": 4500, "a1": 0}
            },
            "solidP": {
                "b32": {"v": 3000, "a1": 0}
            },
            "press": {"a1": 0},
            "heat": {"a1": 0, "a2": 0, "a3": 0},
            "arm": {"a1": 0},
            "take": {"a1": 0, "a2": 0, "a3": 0},
            "spray": {"a1": 0},
            "ticket": {"a1": 0, "a2": 0, "a3": 0, "a4": 0, "a5": 0}
        }

        parsed = process_device_status_report("SN-TEST-ZGC-01", raw_payload)

        # 1. 验证多桶聚合结果：b01 (20000) + b02 (15000) = 35000
        materials = parsed["materials"]
        self.assertIn("fresh_milk", materials)
        self.assertEqual(materials["fresh_milk"]["total_volume"], 35000)
        self.assertEqual(len(materials["fresh_milk"]["barrels"]), 2)

        # 2. 验证香草糖浆结果
        self.assertIn("vanilla_syrup", materials)
        self.assertEqual(materials["vanilla_syrup"]["total_volume"], 4500)

        # 3. 验证整机健康与展示状态
        self.assertTrue(parsed["healthy"])
        self.assertFalse(parsed["disconnected"])
        self.assertEqual(parsed["display_status"], "normal")

        # 4. 验证 Redis 中的存储
        redis_conn = get_redis_connection("default")
        stock_milk = redis_conn.get("automake:stock:SN-TEST-ZGC-01:fresh_milk")
        self.assertIsNotNone(stock_milk)
        self.assertEqual(int(stock_milk), 35000)

        snapshot_cached = redis_conn.get("automake:monitor:snapshot:SN-TEST-ZGC-01")
        self.assertIsNotNone(snapshot_cached)

    @patch('monitor.services.send_sms_notify')
    def test_hardware_abnormality_and_sms_alert(self, mock_send_sms):
        """测试硬件故障/料桶损坏上报时，生成告警记录并触发短信通知（带防抖）"""
        mock_send_sms.return_value = {'ok': True}

        raw_payload_fault = {
            "healthy": 0,
            "disconnected": 0,
            "temperature": {"t1": 4, "t2": 175},
            "ice": {"a1": 0, "a2": 0, "a3": 0},
            "transfer": {"a1": 1},  # 转运模块损坏
            "cup": {
                "paperL": {"a1": 0, "a2": 1},  # 纸大杯用尽
                "lid": {"a1": 0, "a2": 0}
            },
            "thinP": {
                "b01": {"v": 0, "a1": 1}  # b01损坏且空
            },
            "thickP": {},
            "solidP": {},
            "ticket": {"a1": 0, "a2": 1, "a3": 0, "a4": 0, "a5": 0}  # 小票缺纸
        }

        parsed = process_device_status_report("SN-TEST-ZGC-01", raw_payload_fault)

        # 1. 验证状态被标记为异常与故障
        self.assertFalse(parsed["healthy"])
        self.assertEqual(parsed["display_status"], "fault")
        self.assertIn("transfer.a1", parsed["abnormalities"])
        self.assertIn("cup.paperL.a2", parsed["abnormalities"])
        self.assertIn("ticket.a2", parsed["abnormalities"])

        # 2. 验证 DeviceAlarm 告警表写入
        alarms = DeviceAlarm.objects.filter(device=self.device, is_resolved=False)
        self.assertTrue(alarms.exists())

        # 3. 验证短信服务被调用
        self.assertTrue(mock_send_sms.called)
        first_call_count = mock_send_sms.call_count

        # 4. 再次上报相同故障，验证 1 小时防抖机制生效（不重复发送相同告警短信）
        process_device_status_report("SN-TEST-ZGC-01", raw_payload_fault)
        self.assertEqual(mock_send_sms.call_count, first_call_count)

    def test_monitor_api_endpoints(self):
        """测试监控 REST API 接口快速从 Redis 读取数据"""
        raw_payload = {
            "healthy": 1,
            "disconnected": 0,
            "temperature": {"t1": 4, "t2": 175},
            "thinP": {"b01": {"v": 20000, "a1": 0}},
            "thickP": {},
            "solidP": {}
        }
        process_device_status_report("SN-TEST-ZGC-01", raw_payload)

        # 1. 列表接口
        res_list = self.client.get('/api/monitor/devices/')
        self.assertEqual(res_list.status_code, 200)
        json_list = res_list.json()
        self.assertIn(json_list.get('code'), (0, 200))
        self.assertTrue(len(json_list.get('data', [])) >= 1)

        # 2. 详情接口
        res_detail = self.client.get('/api/monitor/devices/SN-TEST-ZGC-01/')
        self.assertEqual(res_detail.status_code, 200)
        json_detail = res_detail.json()
        self.assertIn(json_detail.get('code'), (0, 200))
        self.assertEqual(json_detail['data']['device_sn'], 'SN-TEST-ZGC-01')
        self.assertEqual(json_detail['data']['display_status'], 'normal')

    @patch('monitor.services.send_sms_notify')
    def test_material_shortage_triggers_alert_but_not_offline(self, mock_send_sms):
        """测试缺少物料时可正常告警并短信通知，但绝不将设备置为 offline 或 fault (保持 online)"""
        mock_send_sms.return_value = {'ok': True}

        # 鲜牛奶仅剩 30ml (<= 预警水位 50ml)，无硬件故障
        raw_payload_low_mat = {
            "healthy": 1,
            "disconnected": 0,
            "temperature": {"t1": 4, "t2": 175},
            "thinP": {"b01": {"v": 30, "a1": 0}, "b02": {"v": 0, "a1": 0}},
            "thickP": {"b09": {"v": 4500, "a1": 0}},
            "solidP": {}
        }

        parsed = process_device_status_report("SN-TEST-ZGC-01", raw_payload_low_mat)

        # 1. 验证产生了物料低余量报警
        self.assertIn("material.fresh_milk.low", parsed["abnormalities"])
        # 2. 验证大屏展示为 warning 预警状态（非 fault）
        self.assertEqual(parsed["display_status"], "warning")
        # 3. 验证硬件健康度依然为 True (缺料不代表硬件损坏)
        self.assertTrue(parsed["healthy"])
        self.assertFalse(parsed["disconnected"])

        # 4. 验证 MySQL 中设备状态保持为 online (绝不置为 offline 或 fault)
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, Device.STATUS_ONLINE)

        # 5. 验证短信告警正常发送通知给物料员
        self.assertTrue(mock_send_sms.called)

    def test_store_list_omits_offline_and_fault_devices(self):
        """测试微信小程序 /api/store/list 接口直接过滤掉 offline 和 fault 的设备，不展示在列表中"""
        # 创建一个离线设备和故障设备
        dev_offline = Device.objects.create(
            store=self.store,
            device_sn="SN-OFFLINE-01",
            device_name="离线咖啡机",
            status=Device.STATUS_OFFLINE,
            key_code="DEV-OFF-1"
        )
        dev_fault = Device.objects.create(
            store=self.store,
            device_sn="SN-FAULT-01",
            device_name="故障咖啡机",
            status=Device.STATUS_FAULT,
            key_code="DEV-FLT-1"
        )

        res = self.client.get('/api/store/list')
        self.assertEqual(res.status_code, 200)
        data = res.json().get('data', [])

        returned_sns = [item.get('device_sn') for item in data]
        # 在线设备必须在列表中
        self.assertIn("SN-TEST-ZGC-01", returned_sns)
        # 离线与故障设备直接不展示在列表中
        self.assertNotIn("SN-OFFLINE-01", returned_sns)
        self.assertNotIn("SN-FAULT-01", returned_sns)

    def test_70s_timeout_persistence_to_mysql(self):
        """测试上位机超过 70s 未上报时将料桶信息持久化到 MySQL"""
        from monitor.services import check_and_persist_barrels_on_timeout, persist_device_barrels_to_mysql
        redis_conn = get_redis_connection("default")

        # 写入 Redis 物料与心跳 (心跳设置为 100 秒前)
        redis_conn.set("automake:stock:SN-TEST-ZGC-01:fresh_milk", "3500")
        redis_conn.set("automake:stock:SN-TEST-ZGC-01:vanilla_syrup", "1200")
        redis_conn.set("automake:heartbeat:SN-TEST-ZGC-01", timezone.now().timestamp() - 100)

        # 检查并触发持久化
        triggered = check_and_persist_barrels_on_timeout("SN-TEST-ZGC-01", timeout_seconds=70)
        self.assertTrue(triggered)

        # 验证 MySQL 中的 DeviceMaterialStock 数据已同步
        milk_stock = DeviceMaterialStock.objects.filter(device=self.device, code="fresh_milk").first()
        self.assertIsNotNone(milk_stock)
        self.assertEqual(float(milk_stock.current_remaining_height), 3500.0)
