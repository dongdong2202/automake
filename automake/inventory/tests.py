"""
物料进销存与库房管理模块测试用例
"""

from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from stores.models import Store
from .models import Material, InventoryRecord

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
            unit="kg",
            shelf_life="6个月",
            storage_conditions="常温避光",
            precautions="开封后请密封冷藏"
        )

    def test_material_initial_state(self):
        """测试物料初始创建状态"""
        self.assertEqual(self.material.quantity, 0)
        self.assertEqual(self.material.retrieve_count, 0)
        self.assertEqual(str(self.material), "咖啡豆 (MAT-001)")

    def test_inventory_inbound_success(self):
        """测试正常的进货/入库操作，验证库存增加"""
        record = InventoryRecord.objects.create(
            material=self.material,
            record_type=InventoryRecord.RECORD_TYPE_IN,
            quantity=100.50,
            operator=self.operator,
            remarks="第一批进货"
        )
        
        # 刷新物料数据
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, 100.50)
        self.assertEqual(self.material.retrieve_count, 0)  # 进货不增加取走次数
        self.assertEqual(record.operator, self.operator)

    def test_inventory_outbound_success(self):
        """测试正常的出货给门店，验证库存扣减及取走次数递增"""
        # 先入库 10 kg
        InventoryRecord.objects.create(
            material=self.material,
            record_type=InventoryRecord.RECORD_TYPE_IN,
            quantity=10.00,
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
