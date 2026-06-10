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
        )

    def test_simulator_page_render(self):
        """测试模拟器页面渲染成功"""
        response = self.client.get('/simulator/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '上位机通信模拟器')

    def test_device_register_endpoint(self):
        """测试设备注册 API"""
        payload = {
            'device_sn': 'TEST-SN-001',
            'device_name': '测试设备1',
            'device_version': '1.0.0',
            'device_address': '北京市海淀区',
        }
        response = self.client.post(
            '/api/device/register',
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['code'], 0)
        self.assertTrue(Device.objects.filter(device_sn='TEST-SN-001').exists())

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
            'materials': [
                {'material_code': 'coffee_bean', 'material_name': '咖啡豆', 'quantity': 750.0, 'unit': 'g'},
                {'material_code': 'fresh_milk', 'material_name': '鲜牛奶', 'quantity': 3500.0, 'unit': 'ml'}
            ]
        }
        response = self.client.post(
            '/api/device/inventory/report',
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)

        # 验证物料库存记录是否创建并保存了正确数量
        from menus.models import MaterialStock
        coffee_stock = MaterialStock.objects.get(device=device, material_code='coffee_bean')
        self.assertEqual(coffee_stock.current_quantity, 750.0)
        self.assertEqual(coffee_stock.unit, 'g')

        milk_stock = MaterialStock.objects.get(device=device, material_code='fresh_milk')
        self.assertEqual(milk_stock.current_quantity, 3500.0)
        self.assertEqual(milk_stock.unit, 'ml')

    def test_device_inventory_report_mqtt(self):
        """测试设备通过 MQTT 上报物料库存更新及告警"""
        device = Device.objects.create(
            device_sn='TEST-SN-007',
            store=self.store,
            status=Device.STATUS_ONLINE,
        )
        from devices.views import receive_material_report
        payload = {
            'materials': [
                {'code': 'coffee_bean', 'name': '咖啡豆', 'quantity': 50.0, 'unit': 'g'}, # 低于阈值100
                {'code': 'fresh_milk', 'name': '鲜牛奶', 'quantity': 4000.0, 'unit': 'ml'}
            ]
        }
        receive_material_report('TEST-SN-007', payload)

        # 验证库存更新
        from menus.models import MaterialStock
        coffee_stock = MaterialStock.objects.get(device=device, material_code='coffee_bean')
        self.assertEqual(coffee_stock.current_quantity, 50.0)

        # 验证是否触发了物料过低告警
        from devices.models import DeviceAlarm
        alarm_exists = DeviceAlarm.objects.filter(
            device=device,
            alarm_type=DeviceAlarm.ALARM_LOW_MATERIAL,
            is_resolved=False,
            detail__contains='(coffee_bean)'
        ).exists()
        self.assertTrue(alarm_exists)


