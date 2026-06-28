from django.test import TestCase, Client
from unittest.mock import patch, MagicMock
from django.utils import timezone
from devices.models import Device, DeviceCommand, DeviceStatusLog
from orders.models import OrderMain, OrderStatusLog, ProductionTask
from stores.models import Store
from users.models import User
from mqtt import issue_make_command, issue_device_command
import json

class SimulatorIntegrationTests(TestCase):
    def setUp(self):
        self.client = Client()
        # 创建一个测试用户和门店
        self.user = User.objects.create_user(openid='test-user-openid')
        self.store = Store.objects.create(
            name='测试门店',
            address='北京市海淀区',
            contact_phone='13800000000',
            status=Store.STATUS_OPEN,
            code='TEST-KEY-001',
        )

    def test_simulator_page_render(self):
        """测试模拟器页面渲染成功"""
        response = self.client.get('/simulator/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '上位机通信模拟器')

    def test_device_register_endpoint(self):
        """测试设备注册 API (包含自动创建、更新与注册码校验)"""
        # 预先录入测试机器
        Device.objects.create(device_sn='NEW-TEST-SN-999', status=Device.STATUS_ONLINE)
        Device.objects.create(device_sn='NEW-TEST-SN-888', status=Device.STATUS_ONLINE)

        # Scenario 1: 注册一个已录入系统的机器，注册码有效
        payload_create = {
            'device_sn': 'NEW-TEST-SN-999',
            'key_code': 'TEST-KEY-001',
            'store_id': self.store.id,
            'device_name': '新建测试咖啡机',
            'device_version': '1.0.0',
            'device_address': '北京市海淀区',
        }
        res_create = self.client.post(
            '/api/device/register',
            data=json.dumps(payload_create),
            content_type='application/json',
        )
        self.assertEqual(res_create.status_code, 200)
        self.assertEqual(res_create.json()['code'], 0)
        
        device = Device.objects.get(device_sn='NEW-TEST-SN-999')
        self.assertEqual(device.status, Device.STATUS_ONLINE)
        self.assertEqual(device.device_name, '新建测试咖啡机')
        self.assertEqual(device.store, self.store)
        self.assertEqual(device.key_code, 'TEST-KEY-001')

        # Scenario 2: 注册码不存在或无效，应当返回 400 (或者自定义业务 code 错误)
        payload_invalid_key = {
            'device_sn': 'NEW-TEST-SN-888',
            'key_code': 'INVALID-KEY-XYZ',
            'store_id': self.store.id,
            'device_name': '无效注册码咖啡机',
            'device_version': '1.0.0',
        }
        res_invalid = self.client.post(
            '/api/device/register',
            data=json.dumps(payload_invalid_key),
            content_type='application/json',
        )
        self.assertEqual(res_invalid.json()['code'], 6002)

        # Scenario 3: 更新已存在的设备（SN 与 key_code 匹配）完整数据项
        payload_update = {
            'device_sn': 'NEW-TEST-SN-999',
            'key_code': 'TEST-KEY-001',
            'store_id': self.store.id,
            'device_name': '已更新名称咖啡机',
            'device_version': '2.0.0',
            'device_address': '北京市朝阳区',
        }
        res_update = self.client.post(
            '/api/device/register',
            data=json.dumps(payload_update),
            content_type='application/json',
        )
        self.assertEqual(res_update.status_code, 200)
        self.assertEqual(res_update.json()['code'], 0)
        
        device.refresh_from_db()
        self.assertEqual(device.device_name, '已更新名称咖啡机')
        self.assertEqual(device.firmware_version, '2.0.0')
        self.assertEqual(device.extra_config.get('device_address'), '北京市朝阳区')

        # Scenario 4: 更新已存在的设备，但使用的 key_code 与数据库中不一致
        # 首先需要在 DB 里有另一个有效的门店和 code，避免触发 6002 Store 不存在
        other_store = Store.objects.create(
            name='另一个门店',
            code='ANOTHER-KEY-CODE',
            status=Store.STATUS_OPEN
        )
        payload_mismatch = {
            'device_sn': 'NEW-TEST-SN-999',
            'key_code': 'ANOTHER-KEY-CODE',
            'store_id': other_store.id,
            'device_name': '越权咖啡机',
            'device_version': '2.0.0',
        }
        res_mismatch = self.client.post(
            '/api/device/register',
            data=json.dumps(payload_mismatch),
            content_type='application/json',
        )
        self.assertEqual(res_mismatch.json()['code'], 6003)

        # Scenario 5: 注册一个未在数据库预先录入的全新机器，应当返回 6004 错误码
        payload_not_pre_recorded = {
            'device_sn': 'NOT-EXIST-SN-000',
            'key_code': 'TEST-KEY-001',
            'store_id': self.store.id,
            'device_name': '未录入咖啡机',
        }
        res_not_pre = self.client.post(
            '/api/device/register',
            data=json.dumps(payload_not_pre_recorded),
            content_type='application/json',
        )
        self.assertEqual(res_not_pre.json()['code'], 6004)

    def test_device_heartbeat_endpoint(self):
        """测试设备心跳 API 被禁止，必须走 MQTT"""
        # 先创建设备
        device = Device.objects.create(
            device_sn='TEST-SN-002',
            store=self.store,
            status=Device.STATUS_ONLINE,
        )
        payload = {
            'device_sn': 'TEST-SN-002',
            'status': 'fault',
        }
        
        # 1. 验证 HTTP POST 接口返回 400 错误（已禁用）
        response = self.client.post(
            '/api/device/status/report',
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        
        # 2. 验证通过 MQTT 处理函数上报心跳可以正常更新状态
        from devices.views import receive_device_status
        mqtt_payload = {
            'type': 'heartbeat',
            'status': 'fault',
        }
        receive_device_status('TEST-SN-002', mqtt_payload)
        device.refresh_from_db()
        self.assertEqual(device.status, 'fault')

    @patch('mqtt.get_mqtt_client')
    def test_issue_make_command(self, mock_get_client):
        """测试云端向下位机下发制作指令"""
        # Mock MQTT client
        mock_client = MagicMock()
        mock_publish_result = MagicMock()
        mock_publish_result.rc = 0  # MQTT_ERR_SUCCESS
        mock_client.publish.return_value = mock_publish_result
        mock_get_client.return_value = mock_client

        # 创建设备和订单
        device = Device.objects.create(device_sn='TEST-SN-003', store=self.store, status=Device.STATUS_ONLINE)
        order = OrderMain.objects.create(
            order_no='202606090001',
            store=self.store,
            user=self.user,
            status=OrderMain.STATUS_PAID,
            total_amount=100,
            discount_amount=0,
            pay_amount=100,
        )
        task = ProductionTask.objects.create(
            order=order,
            device=device,
            status=ProductionTask.TASK_PENDING,
            command_payload={'items': []},
        )

        # 执行下发指令
        success = issue_make_command(
            order_no=order.order_no,
            device_sn=device.device_sn,
            command_payload=task.command_payload,
        )

        self.assertTrue(success)
        mock_client.publish.assert_called_once()

        # 检查数据库中的 DeviceCommand 记录
        cmd = DeviceCommand.objects.get(order=order)
        self.assertEqual(cmd.command_type, DeviceCommand.CMD_MAKE)
        self.assertEqual(cmd.status, DeviceCommand.SENT)

        # 检查 ProductionTask 状态更新为已发送
        task.refresh_from_db()
        self.assertEqual(task.status, ProductionTask.TASK_SENT)
        self.assertIsNotNone(task.sent_at)

    @patch('mqtt.get_mqtt_client')
    def test_issue_device_command(self, mock_get_client):
        """测试云端下发通用命令"""
        mock_client = MagicMock()
        mock_publish_result = MagicMock()
        mock_publish_result.rc = 0  # MQTT_ERR_SUCCESS
        mock_client.publish.return_value = mock_publish_result
        mock_get_client.return_value = mock_client

        device = Device.objects.create(device_sn='TEST-SN-003-GEN', store=self.store, status=Device.STATUS_ONLINE)

        # 1. 测试下发 cancel 命令
        success = issue_device_command(
            device_sn=device.device_sn,
            command_type=DeviceCommand.CMD_CANCEL,
            payload={'reason': 'user_cancelled'}
        )
        self.assertTrue(success)
        cmd = DeviceCommand.objects.get(device=device, command_type=DeviceCommand.CMD_CANCEL)
        self.assertEqual(cmd.status, DeviceCommand.SENT)

        # 2. 测试下发 reset 命令
        success = issue_device_command(
            device_sn=device.device_sn,
            command_type=DeviceCommand.CMD_RESET
        )
        self.assertTrue(success)
        self.assertTrue(DeviceCommand.objects.filter(device=device, command_type=DeviceCommand.CMD_RESET).exists())

    def test_receive_device_status_report(self):
        """测试接收设备状态回报（HTTP被禁，必须走 MQTT）"""
        device = Device.objects.create(device_sn='TEST-SN-004', store=self.store, status=Device.STATUS_ONLINE)
        order = OrderMain.objects.create(
            order_no='202606090002',
            store=self.store,
            user=self.user,
            status=OrderMain.STATUS_PAID,
            total_amount=100,
            discount_amount=0,
            pay_amount=100,
        )
        task = ProductionTask.objects.create(
            order=order,
            device=device,
            status=ProductionTask.TASK_SENT,
            command_payload={'items': []},
        )

        # 1. 验证 HTTP POST 接口被禁用（返回 400）
        http_payload = {
            'device_sn': 'TEST-SN-004',
            'order_no': '202606090002',
            'status': 'making',
            'message': '开始磨豆',
        }
        response = self.client.post(
            '/api/device/order/status/report',
            data=json.dumps(http_payload),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

        # 2. 模拟设备通过 MQTT 回传 status = 'making'
        from devices.views import receive_device_status
        mqtt_payload = {
            'type': 'order_status',
            'order_no': '202606090002',
            'status': 'making',
            'message': '开始磨豆',
        }
        receive_device_status('TEST-SN-004', mqtt_payload)

        # 检查订单状态更新为制作中
        order.refresh_from_db()
        self.assertEqual(order.status, OrderMain.STATUS_MAKING)

        # 检查生产任务状态同步为制作中
        task.refresh_from_db()
        self.assertEqual(task.status, ProductionTask.TASK_MAKING)

        # 3. 模拟设备通过 MQTT 回传 status = 'done'
        mqtt_payload['status'] = 'done'
        mqtt_payload['message'] = '制作完成'
        receive_device_status('TEST-SN-004', mqtt_payload)

        # 检查订单状态更新为已完成
        order.refresh_from_db()
        self.assertEqual(order.status, OrderMain.STATUS_DONE)

        # 检查生产任务状态同步为制作完成
        task.refresh_from_db()
        self.assertEqual(task.status, ProductionTask.TASK_DONE)
        self.assertIsNotNone(task.done_at)

    def test_device_heartbeat_mqtt(self):
        """测试设备通过 MQTT 上报心跳"""
        device = Device.objects.create(
            device_sn='TEST-SN-005',
            store=self.store,
            status=Device.STATUS_OFFLINE,
        )
        from devices.views import receive_device_status
        payload = {
            'type': 'heartbeat',
            'status': 'online',
        }
        receive_device_status('TEST-SN-005', payload)
        device.refresh_from_db()
        self.assertEqual(device.status, 'online')

    def test_device_inventory_report_http(self):
        """测试设备通过 HTTPS POST 上报当前库存"""
        device = Device.objects.create(
            device_sn='TEST-SN-006',
            store=self.store,
            status=Device.STATUS_ONLINE,
        )
        payload = {
            'device_sn': 'TEST-SN-006',
            'raw': {
                'coffee_bean': 750.0,
                'fresh_milk': 3500.0
            },
            'cup': {
                'paperL': 100,
                'lid': 100
            }
        }
        response = self.client.post(
            '/api/device/inventory/report',
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)

    def test_device_inventory_report_mqtt(self):
        """测试设备通过 MQTT 上报物料库存"""
        device = Device.objects.create(
            device_sn='TEST-SN-007',
            store=self.store,
            status=Device.STATUS_ONLINE,
        )
        from devices.views import receive_material_report
        from devices.models import DeviceMaterialStock, DeviceConsumableStock
        from django_redis import get_redis_connection
        from inventory.models import Material
        from orders.services import get_consumable_name_by_code
        from decimal import Decimal

        # 预先创建通用物料及该设备的耗材库存记录
        for m_code in ['paperL', 'lid']:
            mat, _ = Material.objects.get_or_create(
                code=m_code,
                defaults={
                    'name': get_consumable_name_by_code(m_code),
                    'material_type': Material.TYPE_CONSUMABLE,
                    'unit': '个',
                    'shelf_life': '永久',
                    'storage_conditions': '常温干燥'
                }
            )
            DeviceConsumableStock.objects.create(
                device=device,
                code=mat,
                init_quantity=100,
                quantity=100,
                unit='个',
                warn_level=20
            )

        # 预先创建通用食材物料及该设备的食材库存配置，用于触发报警函数
        mat_raw, _ = Material.objects.get_or_create(
            code='coffee_bean',
            defaults={
                'name': '咖啡豆',
                'material_type': Material.TYPE_INGREDIENT,
                'unit': 'g',
                'shelf_life': '永久',
                'storage_conditions': '常温干燥'
            }
        )
        DeviceMaterialStock.objects.create(
            device=device,
            code='coffee_bean',
            name=mat_raw,
            initHight=100,
            unit='cm',
            warn_level=Decimal('10.00'),
            warn_level_3=Decimal('2.00')
        )

        # 测试新格式上报 (raw & cup)
        redis_conn = get_redis_connection("default")
        redis_conn.delete(f"automake:stock:TEST-SN-007:coffee_bean")
        redis_conn.delete(f"automake:stock:TEST-SN-007:fresh_milk")
        redis_conn.delete(f"automake:stock:TEST-SN-007:paperL")
        redis_conn.delete(f"automake:stock:TEST-SN-007:lid")

        # 第一次上报
        payload_new = {
            'raw': {
                'coffee_bean': 85.0,
                'fresh_milk': 2500.0
            },
            'cup': {
                'paperL': 80,
                'lid': 75
            }
        }
        receive_material_report('TEST-SN-007', payload_new)

        self.assertEqual(DeviceConsumableStock.objects.filter(device=device).count(), 2)
        self.assertEqual(DeviceConsumableStock.objects.get(device=device, code__code='paperL').quantity, 80)
        self.assertEqual(DeviceConsumableStock.objects.get(device=device, code__code='lid').quantity, 75)

        # 第二次上报（报告较多已消耗余量，触发预警）
        payload_update = {
            'raw': {
                'coffee_bean': 95.0,  # initHight=100，所以 height_val = 5.0，低于 warn_level=10.0
                'fresh_milk': 2400.0
            },
            'cup': {
                'paperL': 78,
                'lid': 72
            }
        }
        receive_material_report('TEST-SN-007', payload_update)

        # 验证：
        # - cup 消耗品保存到了 MySQL (DeviceConsumableStock)
        self.assertEqual(DeviceConsumableStock.objects.filter(device=device).count(), 2)
        self.assertEqual(DeviceConsumableStock.objects.get(device=device, code__code='paperL').quantity, 78)
        self.assertEqual(DeviceConsumableStock.objects.get(device=device, code__code='lid').quantity, 72)

        # - raw 食材不保存到 MySQL (DeviceMaterialStock)
        self.assertEqual(DeviceMaterialStock.objects.filter(device=device).count(), 1)

        # - Redis 中的库存都更新了
        self.assertEqual(int(redis_conn.get(f"automake:stock:TEST-SN-007:coffee_bean")), 9500)
        self.assertEqual(int(redis_conn.get(f"automake:stock:TEST-SN-007:fresh_milk")), 240000)
        self.assertEqual(int(redis_conn.get(f"automake:stock:TEST-SN-007:paperL")), 7800)
        self.assertEqual(int(redis_conn.get(f"automake:stock:TEST-SN-007:lid")), 7200)

    @patch('simulator.views.get_mqtt_client')
    def test_simulator_status_api(self, mock_get_client):
        """测试模拟器连接状态 API"""
        mock_client = MagicMock()
        mock_client.is_connected.return_value = True
        mock_get_client.return_value = mock_client
        
        response = self.client.get('/simulator/api/status/?sn=TEST-SN-100')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['code'], 0)
        self.assertTrue(response.json()['data']['mqtt_connected'])

    def test_simulator_logs_api(self):
        """测试模拟器日志查询与清除 API"""
        from django.core.cache import cache
        # 1. 模拟写入缓存日志
        key = "simulator:logs:TEST-SN-200"
        cache.set(key, [{"timestamp": 123456.0, "type": "recv", "topic": "test", "payload": {}}])
        
        # 2. 查询日志
        response = self.client.get('/simulator/api/logs/?sn=TEST-SN-200')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['data']['logs']), 1)
        
        # 3. 清除日志
        res_clear = self.client.post('/simulator/api/clear_logs/?sn=TEST-SN-200')
        self.assertEqual(res_clear.status_code, 200)
        self.assertEqual(cache.get(key), None)

    @patch('simulator.views.get_mqtt_client')
    def test_simulator_report_api(self, mock_get_client):
        """测试模拟器状态上报 API (REST -> MQTT)"""
        mock_client = MagicMock()
        mock_client.is_connected.return_value = True
        mock_publish_result = MagicMock()
        mock_publish_result.rc = 0
        mock_client.publish.return_value = mock_publish_result
        mock_get_client.return_value = mock_client

        payload = {
            'device_sn': 'TEST-SN-300',
            'topic_type': 'status',
            'payload': {
                'type': 'order_status',
                'order_no': '202606090001',
                'status': 'making',
                'message': '开始制作'
            }
        }
        response = self.client.post(
            '/simulator/api/report/',
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['code'], 0)
        mock_client.publish.assert_called_once()

    @patch('mqtt.get_mqtt_client')
    def test_simulator_create_test_order_api(self, mock_get_client):
        """测试一键创建测试订单 API"""
        mock_client = MagicMock()
        mock_client.is_connected.return_value = True
        mock_publish_result = MagicMock()
        mock_publish_result.rc = 0
        mock_client.publish.return_value = mock_publish_result
        mock_get_client.return_value = mock_client

        payload = {'device_sn': 'SN-DIAG-TEST'}
        response = self.client.post(
            '/simulator/api/create_test_order/',
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['code'], 0)
        self.assertIn('order_no', response.json()['data'])

    def test_simulator_diagnostics_api(self):
        """测试模拟器诊断数据监测 API"""
        # 1. 注册一个测试设备
        device = Device.objects.create(
            device_sn='SN-DIAG-TEST2',
            status=Device.STATUS_ONLINE,
        )
        # 2. 查询诊断数据
        response = self.client.get('/simulator/api/diagnostics/?sn=SN-DIAG-TEST2')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['code'], 0)
        self.assertTrue(response.json()['data']['device_exists'])


