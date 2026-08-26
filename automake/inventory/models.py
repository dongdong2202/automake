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
    TYPE_INGREDIENT = 'ingredient'  # 食材
    TYPE_CONSUMABLE = 'consumable'  # 耗材
    TYPE_CUP = 'cup'                # 杯/包装耗材
    TYPE_ICE = 'ice'                # 冰块
    TYPE_THIN = 'thin'              # 稀液料
    TYPE_THICK = 'thick'            # 稠液料
    TYPE_SOLID = 'solid'            # 固体料

    TYPE_CHOICES = [
        (TYPE_INGREDIENT, '食材'),
        (TYPE_CONSUMABLE, '耗材'),
        (TYPE_CUP, '杯/耗材(cup)'),
        (TYPE_ICE, '冰块(ice)'),
        (TYPE_THIN, '稀液料(thin)'),
        (TYPE_THICK, '稠液料(thick)'),
        (TYPE_SOLID, '固体料(solid)'),
    ]

    name = models.CharField(max_length=128, unique=True, verbose_name="物料名称", help_text="名称必须规范、一致，直接影响下位机用料统计")
    code = models.CharField(max_length=64, unique=True, verbose_name="物料编号", db_index=True)
    material_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default=TYPE_INGREDIENT,
        verbose_name="物料类别"
    )
    price = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0.00, 
        verbose_name="物料单价/售价", 
        help_text="单位单价（元）"
    )
    quantity = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0.00, 
        verbose_name="当前剩余数量"
    )
    unit = models.CharField(max_length=32, verbose_name="计量单位", help_text="如：kg, 升, 包, 箱, 个, ml, g")
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


def parse_shelf_life_duration_days(shelf_life_str, reference_date=None):
    """
    解析保质期字符串转换为有效天数（时长）：
    - 空值 / '永久有效' / '永久' / '无' / '长期' / 'none' -> 返回 None（代表永久有效，无保质期）
    - 日期格式: '2027-08-23' -> (2027-08-23 - reference_date).days
    - 纯天数格式: '30天', '365天', '30' -> 30, 365
    - 月份格式: '12个月', '6月' -> 12 * 30, 6 * 30
    - 年份格式: '1年', '3年' -> 1 * 365, 3 * 365
    - 范围保护: 1 ~ 3650 天 (最大 10 年)
    """
    import re
    import datetime
    if not shelf_life_str:
        return None

    s = str(shelf_life_str).strip()
    if s in ['永久有效', '永久', '长期', '无', '无保质期', 'permanent', 'none', 'null', '长期有效']:
        return None

    # 1. 尝试匹配 YYYY-MM-DD 日期格式，计算距离基准日期的天数时长
    date_match = re.match(r'^(\d{4}-\d{2}-\d{2})', s)
    if date_match:
        try:
            target_date = datetime.datetime.strptime(date_match.group(1), '%Y-%m-%d').date()
            base = reference_date if reference_date else timezone.now().date()
            diff_days = (target_date - base).days
            return max(1, min(3650, diff_days))
        except Exception:
            pass

    # 2. 尝试匹配 'X年'
    year_match = re.match(r'^(\d{1,2})\s*(?:年|year|years)', s, re.IGNORECASE)
    if year_match:
        return min(3650, int(year_match.group(1)) * 365)

    # 3. 尝试匹配 'X个月' / 'X月'
    month_match = re.match(r'^(\d{1,3})\s*(?:个月|月|month|months)', s, re.IGNORECASE)
    if month_match:
        return min(3650, int(month_match.group(1)) * 30)

    # 4. 尝试匹配 'X天' / 'X日'
    day_match = re.match(r'^(\d{1,4})\s*(?:天|日|day|days)?$', s, re.IGNORECASE)
    if day_match:
        val = int(day_match.group(1))
        if val <= 3650:
            return max(1, val)

    return None


def calculate_default_expiration_date(material, base_date=None):
    """
    计算物料默认批次过期时间：
    入库批次过期日 = 入库日期 (base_date, 默认今日) + 物料保质期时长 (shelf_life_days)
    - 若物料设定为永久有效（'永久有效'/'永久'/'长期'/'无'），返回 None；
    - 若设定了具体保质期时长（如 365 天），按 base_date + 时长推算；
    - 若未设定保质期（空值）：
        * cup类耗材默认 3 年 (365 * 3 天)
        * 普通食材物料默认 180 天 (6 个月)
    """
    import datetime
    if base_date is None:
        base_date = timezone.now().date()

    if material:
        shelf_life = getattr(material, 'shelf_life', None)
        if shelf_life is not None and str(shelf_life).strip() != '':
            s = str(shelf_life).strip()
            if s in ['永久有效', '永久', '长期', '无', '无保质期', 'permanent', 'none', 'null', '长期有效']:
                return None
            ref_date = getattr(material, 'created_at', None)
            ref_date_val = ref_date.date() if ref_date else None
            duration_days = parse_shelf_life_duration_days(s, reference_date=ref_date_val)
            if duration_days is not None:
                duration_days = max(1, min(3650, duration_days))
                return base_date + datetime.timedelta(days=duration_days)
            return None

        # 未显式设定保质期时的默认回退
        if getattr(material, 'material_type', '') == Material.TYPE_CUP:
            return base_date + datetime.timedelta(days=365 * 3)
        return base_date + datetime.timedelta(days=180)

    return None


class InventoryRecord(models.Model):
    """
    物料进出库记录表
    
    用于记录物料的动态变化（进货/出库），并关联具体的门店和操作员。
    """
    RECORD_TYPE_IN = "in"
    RECORD_TYPE_OUT = "out"
    RECORD_TYPE_CHOICES = [
        (RECORD_TYPE_IN, "入库"),
        (RECORD_TYPE_OUT, "出库"),
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
    price = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True, 
        default=0.00, 
        verbose_name="单价/价格", 
        help_text="入库时必填单价（元）"
    )
    store = models.ForeignKey(
        "stores.Store", 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="material_records",
        verbose_name="出库目标门店", 
        help_text="仅在“出库”时需要选择对应的门店"
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
        help_text="进货/入库时若留空，cup类默认3年，其他物料默认6个月"
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
        4. 如果是入库操作，必须填写价格信息，并自动填充默认过期时间；
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
            if self.price is None or self.price < 0:
                raise ValidationError({"price": "入库操作必须填写有效的单价/价格信息。"})
            if not self.expiration_date:
                mat = getattr(self, 'material', None)
                if not mat and self.material_id:
                    mat = Material.objects.filter(pk=self.material_id).first()
                if mat:
                    self.expiration_date = calculate_default_expiration_date(mat)

    def save(self, *args, **kwargs):
        """
        保存时通过数据库事务原子地更新 Material 主表的 quantity 和 retrieve_count。
        """
        from decimal import Decimal
        if self.quantity is not None and not isinstance(self.quantity, Decimal):
            self.quantity = Decimal(str(self.quantity))
            
        if self.record_type == self.RECORD_TYPE_IN and not self.expiration_date:
            mat = getattr(self, 'material', None)
            if not mat and self.material_id:
                mat = Material.objects.filter(pk=self.material_id).first()
            if mat:
                self.expiration_date = calculate_default_expiration_date(mat)

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
                    if self.price is not None:
                        material.price = self.price
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

            # 当总仓出库给具体门店时，自动原子更新/创建门店自身库存并记录分拨流水
            if self.record_type == self.RECORD_TYPE_OUT and self.store:
                store_inv, _ = StoreInventory.objects.get_or_create(
                    store=self.store,
                    material=material,
                    defaults={'quantity': Decimal('0.00')}
                )
                store_inv.quantity += self.quantity
                store_inv.save()

                StoreInventoryRecord.objects.create(
                    store=self.store,
                    material=material,
                    record_type=StoreInventoryRecord.TYPE_IN_FROM_WAREHOUSE,
                    quantity=self.quantity,
                    operator=self.operator,
                    remarks=f"总仓分拨出库入店: {self.remarks or '常规分拨'}"
                )

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

            if self.record_type == self.RECORD_TYPE_OUT and self.store:
                store_inv = StoreInventory.objects.filter(store=self.store, material=material).first()
                if store_inv:
                    store_inv.quantity = max(Decimal('0.00'), store_inv.quantity - self.quantity)
                    store_inv.save()

            super().delete(*args, **kwargs)


class StoreInventory(models.Model):
    """
    门店自身物料库存表
    记录各门店当前所拥有的具体物料库存量。
    - 当总仓出库分拨到某门店时，该门店库存自动增加；
    - 当门店出库加料到设备时，该门店库存相应扣减。
    """
    store = models.ForeignKey(
        'stores.Store', 
        on_delete=models.CASCADE, 
        related_name='store_inventories', 
        verbose_name='所属门店'
    )
    material = models.ForeignKey(
        Material, 
        on_delete=models.CASCADE, 
        related_name='store_inventories', 
        verbose_name='关联物料'
    )
    quantity = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0.00, 
        verbose_name='当前在店库存'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='最后变动时间')

    class Meta:
        db_table = 'store_inventory'
        unique_together = ('store', 'material')
        verbose_name = '门店物料库存'
        verbose_name_plural = '门店物料库存列表'
        ordering = ['store', 'material']

    def __str__(self):
        return f"{self.store.name} - {self.material.name}: {self.quantity} {self.material.unit}"


class StoreInventoryRecord(models.Model):
    """
    门店物料出入库与调拨流水记录表
    - in_from_warehouse: 总仓分拨入店
    - out_to_device: 门店出库加料到设备
    """
    TYPE_IN_FROM_WAREHOUSE = 'in_from_warehouse'
    TYPE_OUT_TO_DEVICE = 'out_to_device'

    RECORD_TYPE_CHOICES = [
        (TYPE_IN_FROM_WAREHOUSE, '总仓分拨入店'),
        (TYPE_OUT_TO_DEVICE, '出库加料到设备'),
    ]

    store = models.ForeignKey(
        'stores.Store', 
        on_delete=models.CASCADE, 
        related_name='store_inventory_records', 
        verbose_name='所属门店'
    )
    material = models.ForeignKey(
        Material, 
        on_delete=models.CASCADE, 
        related_name='store_records', 
        verbose_name='关联物料'
    )
    device = models.ForeignKey(
        'devices.Device', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='store_refill_records', 
        verbose_name='目标设备'
    )
    record_type = models.CharField(
        max_length=32, 
        choices=RECORD_TYPE_CHOICES, 
        verbose_name='流转类型',
        db_index=True
    )
    quantity = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        verbose_name='流转数量'
    )
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        verbose_name='经办操作员'
    )
    remarks = models.TextField(blank=True, verbose_name='备注说明')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='流转发生时间')

    class Meta:
        db_table = 'store_inventory_record'
        verbose_name = '门店调拨流水'
        verbose_name_plural = '门店调拨流水列表'
        ordering = ['-created_at']

    def __str__(self):
        type_str = dict(self.RECORD_TYPE_CHOICES).get(self.record_type, self.record_type)
        return f"[{self.store.name}] {self.material.name} - {type_str} {self.quantity}"
