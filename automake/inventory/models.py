"""
物料进销存与库房管理模型
"""

from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.conf import settings
from django.utils import timezone


class Material(models.Model):
    """
    物料基本信息表
    
    记录仓库中所有原材料/物资的属性，并保存当前的库存余量及被取走的次数。
    """
    name = models.CharField(max_length=128, verbose_name="物料名称")
    code = models.CharField(max_length=64, unique=True, verbose_name="物料编号", db_index=True)
    quantity = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0.00, 
        verbose_name="当前剩余数量"
    )
    unit = models.CharField(max_length=32, verbose_name="计量单位", help_text="如：kg, 升, 包, 箱")
    shelf_life = models.CharField(
        max_length=64, 
        verbose_name="保质期", 
        help_text="如：12个月, 3天"
    )
    storage_conditions = models.CharField(
        max_length=128, 
        verbose_name="储存条件", 
        help_text="如：常温避光, 冷藏(2-8℃), 冷冻"
    )
    precautions = models.TextField(blank=True, verbose_name="注意事项", help_text="安全使用或储存的特殊说明")
    remarks = models.TextField(blank=True, verbose_name="备注")
    
    retrieve_count = models.IntegerField(
        default=0, 
        verbose_name="取走（出库）次数", 
        help_text="统计该物料累计出库分拨的次数"
    )
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "inventory_material"
        verbose_name = "物料信息"
        verbose_name_plural = "物料库房"
        ordering = ["code"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class InventoryRecord(models.Model):
    """
    物料进出库记录表
    
    用于记录物料的动态变化（进货/出库），并关联具体的门店和操作员。
    """
    RECORD_TYPE_IN = "in"
    RECORD_TYPE_OUT = "out"
    RECORD_TYPE_CHOICES = [
        (RECORD_TYPE_IN, "进货/入库"),
        (RECORD_TYPE_OUT, "出货/出库"),
    ]

    material = models.ForeignKey(
        Material, 
        on_delete=models.CASCADE, 
        related_name="records", 
        verbose_name="物料"
    )
    record_type = models.CharField(
        max_length=10, 
        choices=RECORD_TYPE_CHOICES, 
        verbose_name="记录类型", 
        db_index=True
    )
    quantity = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        verbose_name="变更数量", 
        help_text="必须为大于 0 的数值"
    )
    store = models.ForeignKey(
        "stores.Store", 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="material_records",
        verbose_name="出库目标门店", 
        help_text="仅在“出货/出库”时需要选择对应的门店"
    )
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        verbose_name="经办操作员"
    )
    expiration_date = models.DateField(
        null=True, 
        blank=True, 
        verbose_name="批次过期时间", 
        help_text="进货时，记录该批物料的具体过期日期"
    )
    remarks = models.TextField(blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="操作时间")

    class Meta:
        db_table = "inventory_record"
        verbose_name = "进出库记录"
        verbose_name_plural = "物料动态变化"
        ordering = ["-created_at"]

    def __str__(self):
        type_str = dict(self.RECORD_TYPE_CHOICES).get(self.record_type, "未知")
        return f"{self.material.name} - {type_str} {self.quantity} {self.material.unit}"

    def clean(self):
        """
        验证逻辑：
        1. 变更数量必须大于0；
        2. 如果是出库操作，必须指定目标门店；
        3. 如果是出库操作，出库量不能多于当前库存剩余（若为新增记录）；
        """
        super().clean()
        
        if self.quantity is None or self.quantity <= 0:
            raise ValidationError({"quantity": "变更数量必须为大于 0.00 的数值。"})

        if self.record_type == self.RECORD_TYPE_OUT:
            if not self.store:
                raise ValidationError({"store": "出货/出库给门店时，必须选择对应的目标门店。"})
            
            # 校验库存是否足够 (如果是新纪录，直接校验；若是编辑，在 save 中通过差值计算更准确)
            if not self.pk:
                # 获取数据库中最新的库存量，防止使用 stale 内存缓存
                current_quantity = Material.objects.get(pk=self.material_id).quantity
                if current_quantity < self.quantity:
                    raise ValidationError(
                        {"quantity": f"出库数量 {self.quantity} 超过了物料的当前剩余库存量 {current_quantity}。"}
                    )
        elif self.record_type == self.RECORD_TYPE_IN:
            if self.store:
                raise ValidationError({"store": "进货/入库操作无需指定出库目标门店。"})

    def save(self, *args, **kwargs):
        """
        保存时通过数据库事务原子地更新 Material 主表的 quantity 和 retrieve_count。
        """
        from decimal import Decimal
        if self.quantity is not None and not isinstance(self.quantity, Decimal):
            self.quantity = Decimal(str(self.quantity))
            
        self.clean()
        
        with transaction.atomic():
            # 锁定对应的物料记录，避免高并发冲突
            material = Material.objects.select_for_update().get(pk=self.material_id)
            
            if self.pk:
                # 获取数据库中更新前的旧记录以计算差值
                old_record = InventoryRecord.objects.get(pk=self.pk)
                
                # 1. 恢复旧记录对物料数量的影响
                if old_record.record_type == self.RECORD_TYPE_IN:
                    material.quantity -= old_record.quantity
                else:
                    material.quantity += old_record.quantity
                    material.retrieve_count = max(0, material.retrieve_count - 1)
                
                # 2. 应用新记录对物料数量的影响
                if self.record_type == self.RECORD_TYPE_IN:
                    material.quantity += self.quantity
                else:
                    material.quantity -= self.quantity
                    material.retrieve_count += 1
            else:
                # 新增记录直接应用
                if self.record_type == self.RECORD_TYPE_IN:
                    material.quantity += self.quantity
                else:
                    material.quantity -= self.quantity
                    material.retrieve_count += 1

            # 最终安全性验证：防止编辑现有记录时导致库存变成负数
            if material.quantity < 0:
                raise ValidationError(
                    f"更新失败，当前操作会导致物料 {material.name} 的库存数量降为负数（{material.quantity}）。"
                )

            # 保存物料状态
            material.save()
            
            # 执行父类的 save
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """
        删除记录时，回滚对 Material 主表 quantity 和 retrieve_count 的更新。
        """
        from decimal import Decimal
        if self.quantity is not None and not isinstance(self.quantity, Decimal):
            self.quantity = Decimal(str(self.quantity))

        with transaction.atomic():
            material = Material.objects.select_for_update().get(pk=self.material_id)
            
            if self.record_type == self.RECORD_TYPE_IN:
                material.quantity -= self.quantity
            else:
                material.quantity += self.quantity
                material.retrieve_count = max(0, material.retrieve_count - 1)

            # 保存修改后的物料状态
            material.save()
            super().delete(*args, **kwargs)
