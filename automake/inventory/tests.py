"""
物料进销存与库房管理模块测试用例
"""

import datetime
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from stores.models import Store
from devices.models import Device
from .models import Material, InventoryRecord, StoreInventory, StoreInventoryBatch, StoreInventoryRecord
from .services import create_inbound_batch, dispatch_outbound_fefo, dispatch_store_to_device_fefo
from .tasks import check_inventory_expiration_task
User = get_user_model()


class InventorySystemTests(TestCase):
    """
    测试进销存和物料库房的核心逻辑
    """

    def setUp(self):
        # 1. 创建测试用的系统操作员
        self.operator = User.objects.create_superuser(
            username="test_inventory_operator", 
            password="password123"
        )
        
        # 2. 创建测试用的门店
        self.store = Store.objects.create(
            name="测试门店A",
            address="测试路123号",
            contact_phone="13800138000"
        )
        
        # 3. 创建基础测试物料
        self.material = Material.objects.create(
            name="咖啡豆",
            code="MAT-001",
            price=20.00,
            unit="kg",
            shelf_life="6个月",
            storage_conditions="常温避光"
        )

    def test_material_initial_state(self):
        """测试物料初始创建状态"""
        self.assertEqual(self.material.quantity, 0)
        self.assertEqual(self.material.retrieve_count, 0)
        self.assertEqual(self.material.price, 20.00)
        self.assertEqual(str(self.material), "咖啡豆 (MAT-001)")

    def test_inventory_inbound_success(self):
        """测试正常的进货/入库操作，验证库存增加及价格同步"""
        record = InventoryRecord.objects.create(
            material=self.material,
            record_type=InventoryRecord.RECORD_TYPE_IN,
            quantity=100.50,
            price=25.00,
            operator=self.operator,
            remarks="第一批进货"
        )
        
        # 刷新物料数据
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, 100.50)
        self.assertEqual(self.material.price, 25.00)
        self.assertEqual(self.material.retrieve_count, 0)  # 进货不增加取走次数
        self.assertEqual(record.operator, self.operator)

    def test_inbound_without_price_fails(self):
        """测试入库时未填写单价，应抛出验证异常"""
        with self.assertRaises(ValidationError):
            record = InventoryRecord(
                material=self.material,
                record_type=InventoryRecord.RECORD_TYPE_IN,
                quantity=10.00,
                price=None,
                operator=self.operator
            )
            record.full_clean()

    def test_inbound_default_expiration_date(self):
        """测试入库时未填写过期时间，自动根据物料类别填充（普通物料默认6个月，cup类默认3年）"""
        import datetime
        from django.utils import timezone
        today = timezone.now().date()

        # 1. 普通物料入库（未填过期时间 -> 默认 180 天 / 6个月）
        record_normal = InventoryRecord.objects.create(
            material=self.material,
            record_type=InventoryRecord.RECORD_TYPE_IN,
            quantity=50.00,
            price=20.00,
            operator=self.operator
        )
        self.assertEqual(record_normal.expiration_date, today + datetime.timedelta(days=180))

        # 2. cup类耗材入库（未填过期时间 -> 默认 3年 / 365*3 天）
        cup_mat, _ = Material.objects.get_or_create(
            code="test_cup",
            defaults={"name": "测试纸杯", "material_type": Material.TYPE_CUP, "unit": "个"}
        )
        record_cup = InventoryRecord.objects.create(
            material=cup_mat,
            record_type=InventoryRecord.RECORD_TYPE_IN,
            quantity=100.00,
            price=30.00,
            operator=self.operator
        )
        self.assertEqual(record_cup.expiration_date, today + datetime.timedelta(days=365 * 3))

    def test_inventory_outbound_success(self):
        """测试正常的出货给门店，验证库存扣减及取走次数递增"""
        # 先入库 10 kg
        InventoryRecord.objects.create(
            material=self.material,
            record_type=InventoryRecord.RECORD_TYPE_IN,
            quantity=10.00,
            price=20.00,
            operator=self.operator
        )
        
        # 出库 3 kg 给 门店A
        record = InventoryRecord.objects.create(
            material=self.material,
            record_type=InventoryRecord.RECORD_TYPE_OUT,
            quantity=3.00,
            store=self.store,
            operator=self.operator,
            remarks="门店分拨"
        )
        
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, 7.00)  # 10 - 3 = 7
        self.assertEqual(self.material.retrieve_count, 1)  # 出库 1 次
        self.assertEqual(record.store, self.store)

    def test_outbound_without_store_fails(self):
        """测试出库时不选择目标门店，应抛出验证异常"""
        with self.assertRaises(ValidationError):
            record = InventoryRecord(
                material=self.material,
                record_type=InventoryRecord.RECORD_TYPE_OUT,
                quantity=2.00,
                store=None,  # 缺失门店
                operator=self.operator
            )
            record.full_clean()

    def test_outbound_exceeding_stock_fails(self):
        """测试出库数量超过当前库存，应抛出验证异常"""
        # 入库 5 kg
        InventoryRecord.objects.create(
            material=self.material,
            record_type=InventoryRecord.RECORD_TYPE_IN,
            quantity=5.00,
            price=20.00,
            operator=self.operator
        )
        
        # 尝试出库 6 kg
        with self.assertRaises(ValidationError):
            record = InventoryRecord(
                material=self.material,
                record_type=InventoryRecord.RECORD_TYPE_OUT,
                quantity=6.00,
                store=self.store,
                operator=self.operator
            )
            record.save()  # 在 save 内触发 atomic 校验

    def test_update_record_adjusts_inventory_correctly(self):
        """测试修改进出库记录的变更数量后，主表库存应该根据变化差值重新正确更新"""
        # 1. 进货 50 kg
        in_record = InventoryRecord.objects.create(
            material=self.material,
            record_type=InventoryRecord.RECORD_TYPE_IN,
            quantity=50.00,
            price=20.00,
            operator=self.operator
        )
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, 50.00)
        
        # 2. 修改进货记录的量为 60 kg (原来是 50)
        in_record.quantity = 60.00
        in_record.save()
        
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, 60.00)  # 更新为 60.00
        
        # 3. 再出库 20 kg
        out_record = InventoryRecord.objects.create(
            material=self.material,
            record_type=InventoryRecord.RECORD_TYPE_OUT,
            quantity=20.00,
            store=self.store,
            operator=self.operator
        )
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, 40.00)  # 60 - 20 = 40
        self.assertEqual(self.material.retrieve_count, 1)
        
        # 4. 修改出库记录为 35 kg
        out_record.quantity = 35.00
        out_record.save()
        
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, 25.00)  # 60 - 35 = 25
        self.assertEqual(self.material.retrieve_count, 1)  # 出库次数保持 1

    def test_delete_record_rolls_back_inventory(self):
        """测试删除进出库记录后，自动滚回对物料库存/取走次数的影响"""
        # 入库 100 kg
        in_record = InventoryRecord.objects.create(
            material=self.material,
            record_type=InventoryRecord.RECORD_TYPE_IN,
            quantity=100.00,
            price=20.00,
            operator=self.operator
        )
        
        # 出库 30 kg
        out_record = InventoryRecord.objects.create(
            material=self.material,
            record_type=InventoryRecord.RECORD_TYPE_OUT,
            quantity=30.00,
            store=self.store,
            operator=self.operator
        )
        
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, 70.00)
        self.assertEqual(self.material.retrieve_count, 1)
        
        # 删除出库记录
        out_record.delete()
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, 100.00)  # 库存回滚到 100
        self.assertEqual(self.material.retrieve_count, 0)  # 取走次数归零
        
        # 删除入库记录
        in_record.delete()
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, 0.00)  # 库存回滚到 0


class BatchFefoConsistencyTests(TestCase):
    """
    多批次采购成本与到期日 FEFO（先到期先出库）一致性流转测试
    """

    def setUp(self):
        self.operator = User.objects.create_superuser(
            username="fefo_operator",
            password="password123"
        )
        self.store = Store.objects.create(
            name="FEFO测试门店",
            address="科技路88号",
            contact_phone="13900139000"
        )
        self.device = Device.objects.create(
            device_sn="DEV-FEFO-001",
            device_name="FEFO测试咖啡机",
            store=self.store,
            status=Device.STATUS_ONLINE
        )
        self.material = Material.objects.create(
            name="阿拉比卡精选豆",
            code="BEAN-ARABICA",
            material_type=Material.TYPE_INGREDIENT,
            unit="kg",
            price=Decimal('10.00'),
            quantity=Decimal('0.00')
        )

    def test_multi_batch_inbound_with_distinct_prices_and_expirations(self):
        """
        测试阶段1验证：多批次不同价格与保质期入库
        - 批次1: 数量50, 单价10.00, 到期日 2026-10-01, 批次号 BAT-001
        - 批次2: 数量100, 单价12.00, 到期日 2026-11-01, 批次号 BAT-002
        - 检查总仓 material.quantity == 150，批次1剩余50，批次2剩余100
        """
        b1 = create_inbound_batch(
            material=self.material,
            quantity=Decimal('50.00'),
            price=Decimal('10.00'),
            expiration_date=datetime.date(2026, 10, 1),
            batch_no="BAT-001",
            operator=self.operator,
            remarks="采购批次1"
        )
        b2 = create_inbound_batch(
            material=self.material,
            quantity=Decimal('100.00'),
            price=Decimal('12.00'),
            expiration_date=datetime.date(2026, 11, 1),
            batch_no="BAT-002",
            operator=self.operator,
            remarks="采购批次2"
        )

        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('150.00'))

        b1.refresh_from_db()
        b2.refresh_from_db()
        self.assertEqual(b1.remaining_quantity, Decimal('50.00'))
        self.assertEqual(b1.batch_no, "BAT-001")
        self.assertEqual(b1.price, Decimal('10.00'))

        self.assertEqual(b2.remaining_quantity, Decimal('100.00'))
        self.assertEqual(b2.batch_no, "BAT-002")
        self.assertEqual(b2.price, Decimal('12.00'))

    def test_cross_batch_dispatch_fefo_and_strict_batch_cost(self):
        """
        测试阶段2验证：跨批次出库 FEFO 与严格批次成本结转
        - 总仓向门店1出库数量 80
        - 自动拆单：消耗批次1全部 50（成本10.00，剩余0），消耗批次2部分 30（成本12.00，剩余70）
        - 检查总仓流水生成两条核销出库单，分别绑定各自批次号与进价
        - 检查门店1生成两条入店批次（BAT-001 50，BAT-002 30），门店聚合库存为 80
        """
        b1 = create_inbound_batch(
            material=self.material,
            quantity=Decimal('50.00'),
            price=Decimal('10.00'),
            expiration_date=datetime.date(2026, 10, 1),
            batch_no="BAT-001",
            operator=self.operator
        )
        b2 = create_inbound_batch(
            material=self.material,
            quantity=Decimal('100.00'),
            price=Decimal('12.00'),
            expiration_date=datetime.date(2026, 11, 1),
            batch_no="BAT-002",
            operator=self.operator
        )

        # 分拨 80 出库到门店
        out_records = dispatch_outbound_fefo(
            material=self.material,
            total_quantity=Decimal('80.00'),
            store=self.store,
            operator=self.operator,
            remarks="8月门店补货"
        )

        # 1. 拆批验证
        self.assertEqual(len(out_records), 2)
        self.assertEqual(out_records[0].quantity, Decimal('50.00'))
        self.assertEqual(out_records[0].batch_no, "BAT-001")
        self.assertEqual(out_records[0].price, Decimal('10.00'))
        self.assertEqual(out_records[0].source_batch_id, b1.id)

        self.assertEqual(out_records[1].quantity, Decimal('30.00'))
        self.assertEqual(out_records[1].batch_no, "BAT-002")
        self.assertEqual(out_records[1].price, Decimal('12.00'))
        self.assertEqual(out_records[1].source_batch_id, b2.id)

        # 2. 总仓批次剩余验证
        b1.refresh_from_db()
        b2.refresh_from_db()
        self.assertEqual(b1.remaining_quantity, Decimal('0.00'))
        self.assertEqual(b2.remaining_quantity, Decimal('70.00'))

        # 3. 总仓主表库存验证
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('70.00'))

        # 4. 门店总库存验证
        store_inv = StoreInventory.objects.get(store=self.store, material=self.material)
        self.assertEqual(store_inv.quantity, Decimal('80.00'))

        # 5. 门店在店批次表验证
        store_batches = list(StoreInventoryBatch.objects.filter(store=self.store, material=self.material).order_by('expiration_date'))
        self.assertEqual(len(store_batches), 2)
        self.assertEqual(store_batches[0].batch_no, "BAT-001")
        self.assertEqual(store_batches[0].quantity, Decimal('50.00'))
        self.assertEqual(store_batches[0].cost_price, Decimal('10.00'))
        self.assertEqual(store_batches[0].expiration_date, datetime.date(2026, 10, 1))

        self.assertEqual(store_batches[1].batch_no, "BAT-002")
        self.assertEqual(store_batches[1].quantity, Decimal('30.00'))
        self.assertEqual(store_batches[1].cost_price, Decimal('12.00'))
        self.assertEqual(store_batches[1].expiration_date, datetime.date(2026, 11, 1))

        # 6. 门店调拨流水记录验证
        store_records = list(StoreInventoryRecord.objects.filter(store=self.store, material=self.material).order_by('created_at'))
        self.assertEqual(len(store_records), 2)
        self.assertEqual(store_records[0].batch_no, "BAT-001")
        self.assertEqual(store_records[0].cost_price, Decimal('10.00'))
        self.assertEqual(store_records[1].batch_no, "BAT-002")
        self.assertEqual(store_records[1].cost_price, Decimal('12.00'))

    def test_store_dispatch_to_device_fefo(self):
        """
        测试阶段3验证：门店出库加料到设备 FEFO
        - 门店当前有 BAT-001 (50, 2026-10-01) 和 BAT-002 (30, 2026-11-01)
        - 门店向设备加料 60
        - 优先扣除 BAT-001 全部 50，再扣除 BAT-002 的 10
        - 验证在店批次余量及流水正确记录批次号、进价与到期日
        """
        create_inbound_batch(
            material=self.material,
            quantity=Decimal('50.00'),
            price=Decimal('10.00'),
            expiration_date=datetime.date(2026, 10, 1),
            batch_no="BAT-001",
            operator=self.operator
        )
        create_inbound_batch(
            material=self.material,
            quantity=Decimal('100.00'),
            price=Decimal('12.00'),
            expiration_date=datetime.date(2026, 11, 1),
            batch_no="BAT-002",
            operator=self.operator
        )
        dispatch_outbound_fefo(
            material=self.material,
            total_quantity=Decimal('80.00'),
            store=self.store,
            operator=self.operator
        )

        # 门店向设备加料 60
        store_inv, created_records = dispatch_store_to_device_fefo(
            store=self.store,
            material=self.material,
            device=self.device,
            quantity=Decimal('60.00'),
            operator=self.operator,
            remarks="早高峰加料"
        )

        # 1. 验证加料流水拆批
        self.assertEqual(len(created_records), 2)
        self.assertEqual(created_records[0].quantity, Decimal('50.00'))
        self.assertEqual(created_records[0].batch_no, "BAT-001")
        self.assertEqual(created_records[0].cost_price, Decimal('10.00'))
        self.assertEqual(created_records[0].expiration_date, datetime.date(2026, 10, 1))
        self.assertEqual(created_records[0].record_type, StoreInventoryRecord.TYPE_OUT_TO_DEVICE)

        self.assertEqual(created_records[1].quantity, Decimal('10.00'))
        self.assertEqual(created_records[1].batch_no, "BAT-002")
        self.assertEqual(created_records[1].cost_price, Decimal('12.00'))
        self.assertEqual(created_records[1].expiration_date, datetime.date(2026, 11, 1))
        self.assertEqual(created_records[1].record_type, StoreInventoryRecord.TYPE_OUT_TO_DEVICE)

        # 2. 验证门店总库存
        store_inv.refresh_from_db()
        self.assertEqual(store_inv.quantity, Decimal('20.00'))  # 80 - 60 = 20

        # 3. 验证门店在店批次余量
        sb1 = StoreInventoryBatch.objects.get(store=self.store, material=self.material, batch_no="BAT-001")
        sb2 = StoreInventoryBatch.objects.get(store=self.store, material=self.material, batch_no="BAT-002")
        self.assertEqual(sb1.quantity, Decimal('0.00'))
        self.assertEqual(sb2.quantity, Decimal('20.00'))  # 30 - 10 = 20

    def test_expiration_check_no_false_positives_for_exhausted_batches(self):
        """
        测试阶段4验证：保质期巡检无误报
        - 批次1已全部出库 (remaining_quantity == 0)
        - 巡检任务对已出库完毕的历史批次不再产生预警/告警
        """
        # 入库一个已过期的批次，但数量出库为 0
        exp_past = datetime.date.today() - datetime.timedelta(days=5)
        b_expired = create_inbound_batch(
            material=self.material,
            quantity=Decimal('20.00'),
            price=Decimal('10.00'),
            expiration_date=exp_past,
            batch_no="BAT-EXPIRED-ZERO",
            operator=self.operator
        )
        # 全部出库给门店
        dispatch_outbound_fefo(
            material=self.material,
            total_quantity=Decimal('20.00'),
            store=self.store,
            operator=self.operator
        )
        b_expired.refresh_from_db()
        self.assertEqual(b_expired.remaining_quantity, Decimal('0.00'))

        # 门店再全部加料给设备
        dispatch_store_to_device_fefo(
            store=self.store,
            material=self.material,
            device=self.device,
            quantity=Decimal('20.00'),
            operator=self.operator
        )
        sb_expired = StoreInventoryBatch.objects.get(store=self.store, material=self.material, batch_no="BAT-EXPIRED-ZERO")
        self.assertEqual(sb_expired.quantity, Decimal('0.00'))

        # 执行保质期巡检任务（force=True）
        res = check_inventory_expiration_task(alert_days=30, force=True)

        # 验证总仓已清零批次未被作为告警批次
        self.assertEqual(res['total_scanned_batches'], 0)
        self.assertEqual(res['expired_batches'], 0)
        self.assertEqual(res['store_scanned_batches'], 0)
        self.assertEqual(res['store_expired_batches'], 0)

    def test_material_serializer_latest_price_and_nearest_expiration(self):
        """
        测试验证：物料序列化器的参考价格必须是最新的采购进价，有效期必须是当前在库批次最近即将到期的日期
        """
        from admin_api.serializers import MaterialSerializer

        # 批次1: 单价10.00, 到期日 2026-10-01
        b1 = create_inbound_batch(
            material=self.material,
            quantity=Decimal('50.00'),
            price=Decimal('10.00'),
            expiration_date=datetime.date(2026, 10, 1),
            batch_no="BAT-EARLY",
            operator=self.operator
        )
        # 批次2: 单价15.50 (最新进价), 到期日 2026-12-01
        b2 = create_inbound_batch(
            material=self.material,
            quantity=Decimal('30.00'),
            price=Decimal('15.50'),
            expiration_date=datetime.date(2026, 12, 1),
            batch_no="BAT-LATEST-PRICE",
            operator=self.operator
        )

        serializer_data = MaterialSerializer(self.material).data
        # 1. 验证参考价格是最新的采购进价 (15.50)
        self.assertEqual(serializer_data['price'], '15.50')
        self.assertEqual(serializer_data['latest_price'], '15.50')

        # 2. 验证有效期是当前在库批次中最近即将到期的日期 (2026-10-01)
        self.assertEqual(serializer_data['nearest_expiration_date'], '2026-10-01')
        self.assertEqual(serializer_data['nearest_batch_no'], 'BAT-EARLY')

        # 3. 当最早批次出库完毕后 (remaining_quantity = 0)，最近到期日自动滚动到下一个在库批次 (2026-12-01)
        b1.remaining_quantity = Decimal('0.00')
        b1.save(update_fields=['remaining_quantity'])

        updated_data = MaterialSerializer(self.material).data
        self.assertEqual(updated_data['nearest_expiration_date'], '2026-12-01')
        self.assertEqual(updated_data['nearest_batch_no'], 'BAT-LATEST-PRICE')

    def test_store_inventory_nearest_expiration_and_owner_alert(self):
        """
        测试验证：
        1. 门店库存的有效期显示当前在店批次中最近到期的日期；
        2. 保质期巡检任务精准识别门店店主并自动触发告警提醒。
        """
        from admin_api.serializers import StoreInventorySerializer
        from unittest.mock import patch

        # 1. 创建店长用户并关联该门店
        store_manager = User.objects.create_user(
            openid="wx_store_manager_01",
            username="store_manager_01",
            password="password123",
            role=User.ADMIN,
            phone="13811112222"
        )

        # 2. 入库两个批次并出库给门店
        from django.utils import timezone
        today = timezone.now().date()
        exp_10 = today + datetime.timedelta(days=10)
        b1 = create_inbound_batch(
            material=self.material,
            quantity=Decimal('20.00'),
            price=Decimal('10.00'),
            expiration_date=exp_10,
            batch_no="BAT-STORE-SOON",
            operator=self.operator
        )
        # 批次2: 到期日为未来 60 天
        exp_60 = today + datetime.timedelta(days=60)
        b2 = create_inbound_batch(
            material=self.material,
            quantity=Decimal('40.00'),
            price=Decimal('12.00'),
            expiration_date=exp_60,
            batch_no="BAT-STORE-LATER",
            operator=self.operator
        )

        # 全部出库给门店
        dispatch_outbound_fefo(
            material=self.material,
            total_quantity=Decimal('60.00'),
            store=self.store,
            operator=self.operator
        )

        store_inv = StoreInventory.objects.get(store=self.store, material=self.material)
        s_data = StoreInventorySerializer(store_inv).data

        # 验证门店库存有效期显示最近的在店批次到期日 (exp_10)
        self.assertEqual(s_data['nearest_expiration_date'], str(exp_10))
        self.assertEqual(s_data['nearest_batch_no'], "BAT-STORE-SOON")
        self.assertEqual(s_data['nearest_days_left'], 10)
        self.assertEqual(s_data['nearest_expiration_status'], 'expiring_soon')

        # 3. 验证定时任务过期自动提醒店主
        with patch('inventory.tasks.send_sms_notify') as mock_sms:
            mock_sms.return_value = {'ok': True}
            res = check_inventory_expiration_task(alert_days=30, force=True)

            # 验证发现门店临期批次
            self.assertGreaterEqual(res['store_scanned_batches'], 1)
            self.assertGreaterEqual(res['store_expiring_soon_batches'], 1)

            # 验证向店长手机号 (13811112222) 发送了提醒短信
            sms_called_phones = [call.kwargs.get('phone_numbers') for call in mock_sms.call_args_list]
            self.assertIn("13811112222", sms_called_phones)

        # 4. 当最近批次在门店被消耗完后，门店有效期自动顺延显示下一个批次
        sb1 = StoreInventoryBatch.objects.get(store=self.store, material=self.material, batch_no="BAT-STORE-SOON")
        sb1.quantity = Decimal('0.00')
        sb1.save(update_fields=['quantity'])

        updated_s_data = StoreInventorySerializer(store_inv).data
        self.assertEqual(updated_s_data['nearest_expiration_date'], str(exp_60))
        self.assertEqual(updated_s_data['nearest_batch_no'], "BAT-STORE-LATER")
        self.assertEqual(updated_s_data['nearest_days_left'], 60)
        self.assertEqual(updated_s_data['nearest_expiration_status'], 'normal')
