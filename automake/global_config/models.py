import struct
from django.db import models
from django.core.exceptions import ValidationError

def validate_detail_image(image):
    """
    验证详情页图片：
    1. 图片大小必须小于 1MB
    2. 图片宽度必须为 750px
    支持常见 Web 格式（PNG, JPEG, WebP）的无 Pillow 高速流式解析验证。
    """
    # 1. 检查大小
    limit = 1 * 1024 * 1024
    if image.size > limit:
        raise ValidationError('图片文件大小不能超过 1MB。')

    # 2. 解析并检查宽度
    try:
        image.seek(0)
        head = image.read(30)
        width = None

        if head.startswith(b'\x89PNG\r\n\x1a\n'):
            # PNG: IHDR 块在 offset 12，宽度在 16-20
            width, _ = struct.unpack('>ii', head[16:24])
        elif head.startswith(b'RIFF') and head[8:12] == b'WEBP':
            # WebP
            chunk_type = head[12:16]
            if chunk_type == b'VP8 ':
                image.seek(23)
                sof = image.read(10)
                if sof[3:6] == b'\x9d\x01\x2a':
                    width = struct.unpack('<H', sof[6:8])[0] & 0x3fff
            elif chunk_type == b'VP8L':
                image.seek(21)
                b = image.read(5)
                width = 1 + (((b[1] & 0x3F) << 8) | b[0])
            elif chunk_type == b'VP8X':
                image.seek(24)
                b = image.read(6)
                width = 1 + (b[0] | (b[1] << 8) | (b[2] << 16))
        elif head.startswith(b'\xff\xd8'):
            # JPEG: 扫描段查找 SOF0 标记
            image.seek(0)
            image.read(2)  # SOI
            while True:
                marker = image.read(2)
                if not marker or marker[0] != 0xff:
                    break
                while marker[1] == 0xff:
                    marker = b'\xff' + image.read(1)
                if 0xc0 <= marker[1] <= 0xcf and marker[1] not in (0xc4, 0xc8, 0xcc):
                    image.read(2)  # length
                    image.read(1)  # precision
                    h, w = struct.unpack('>HH', image.read(4))
                    width = w
                    break
                else:
                    len_bytes = image.read(2)
                    if len(len_bytes) < 2:
                        break
                    length = struct.unpack('>H', len_bytes)[0]
                    image.seek(length - 2, 1)

        if width is not None:
            if width != 750:
                raise ValidationError(f'详情页图片宽度必须为 750 像素（当前上传图片宽度为 {width} 像素）。')
        else:
            raise ValidationError('无法读取或识别图片尺寸，请上传标准的 PNG、JPG、JPEG 或 WebP 格式图片。')

    except ValidationError as ve:
        raise ve
    except Exception as e:
        raise ValidationError(f'详情页图片尺寸验证失败: {str(e)}')
    finally:
        image.seek(0)


class DeviceModel(models.Model):
    """
    设备型号定义
    不同型号的设备（如单头、双头咖啡机，是否支持制冰功能等）
    """
    name = models.CharField(max_length=128, verbose_name='设备型号名称')
    code = models.CharField(max_length=64, unique=True, verbose_name='型号编码')
    description = models.TextField(blank=True, verbose_name='型号描述')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'global_device_model'
        verbose_name = '全局设备型号'
        verbose_name_plural = '全局设备型号列表'

    def __str__(self):
        return f"{self.name} ({self.code})"





class GlobalMenuCategory(models.Model):
    """
    全局菜单分类 (必须依赖设备型号)
    """
    device_model = models.ForeignKey(
        DeviceModel, on_delete=models.PROTECT,
        related_name='categories', verbose_name='设备型号'
    )
    name = models.CharField(max_length=64, verbose_name='分类名称')
    icon_url = models.FileField(upload_to='global_category_icons/', max_length=512, blank=True, verbose_name='分类图标')
    sort_order = models.IntegerField(default=0, verbose_name='排序权重')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'global_menu_category'
        verbose_name = '全局菜单分类'
        verbose_name_plural = '全局菜单分类列表'
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f"{self.name} ({self.device_model.name})"


class GlobalMenuItem(models.Model):
    """
    全局菜单商品
    """
    category = models.ForeignKey(
        GlobalMenuCategory, on_delete=models.CASCADE,
        related_name='items', verbose_name='全局分类'
    )
    name = models.CharField(max_length=128, verbose_name='商品名称')
    description = models.TextField(blank=True, verbose_name='商品描述')
    image_url = models.URLField(max_length=512, blank=True, verbose_name='商品图片')
    base_price = models.IntegerField(default=0, verbose_name='基础价格（分）')
    
    # 新增字段：主要原料、价格说明、详情页图片
    main_ingredients = models.CharField(max_length=256, blank=True, verbose_name='主要原料')
    price_description = models.CharField(max_length=256, blank=True, verbose_name='价格说明')
    detail_page = models.FileField(
        upload_to='menu_details/',
        blank=True,
        null=True,
        verbose_name='商品详情页图',
        validators=[validate_detail_image]
    )

    is_active = models.BooleanField(default=True, db_index=True, verbose_name='是否启用')
    sort_order = models.IntegerField(default=0, verbose_name='排序权重')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        # 自动关联插入一条 GlobalMenuSku 记录，name='标准'，category='default'
        from django.apps import apps
        GlobalMenuSkuModel = apps.get_model('global_config', 'GlobalMenuSku')
        if is_new or not self.skus.filter(name='标准').exists():
            GlobalMenuSkuModel.objects.get_or_create(
                item=self,
                name='标准',
                defaults={
                    'category': 'default',
                    'price_delta': 0,
                    'is_active': True,
                    'sort_order': 0
                }
            )

    class Meta:
        db_table = 'global_menu_item'
        verbose_name = '全局菜单商品'
        verbose_name_plural = '全局菜单商品列表'
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f"{self.name} ({self.category.name})"


class GlobalMenuSku(models.Model):
    """
    全局商品规格 / SKU (如杯型：大中小，温度：热/冷等)
    每个 SKU 都是独立的，拥有自己的价格增量和配方用量
    """
    item = models.ForeignKey(
        GlobalMenuItem, on_delete=models.CASCADE,
        related_name='skus', verbose_name='全局商品'
    )
    name = models.CharField(max_length=128, verbose_name='规格名称')
    category = models.CharField(max_length=64, blank=True, default='', verbose_name='分类')
    attributes = models.JSONField(default=dict, blank=True, verbose_name='规格属性')
    price_delta = models.IntegerField(default=0, verbose_name='价格增量（分）')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    sort_order = models.IntegerField(default=0, verbose_name='排序权重')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'global_menu_sku'
        verbose_name = '全局商品规格'
        verbose_name_plural = '全局商品规格列表'
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f"{self.item.name} - {self.name}"


class GlobalSkuIngredient(models.Model):
    """
    全局规格配料用量 (即配方详情)
    直接定义该 SKU 所需要的各种原料的具体用量
    """
    sku = models.ForeignKey(
        GlobalMenuSku, on_delete=models.CASCADE,
        related_name='ingredients', verbose_name='全局规格(SKU)'
    )
    material = models.ForeignKey(
        'inventory.Material', to_field='name', on_delete=models.CASCADE,
        db_column='material_name', related_name='ingredients', verbose_name='物料'
    )
    quantity = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name='用量'
    )
    unit = models.CharField(max_length=16, blank=True, verbose_name='单位(留空使用物料默认单位)')

    class Meta:
        db_table = 'global_sku_ingredient'
        verbose_name = '全局规格配料'
        verbose_name_plural = '全局规格配料列表'

    def __str__(self):
        u = self.unit if self.unit else self.material.unit
        return f"{self.material_id} ({self.quantity}{u})"

    @property
    def material_name(self):
        return self.material_id

    @property
    def material_code(self):
        return self.material.code


class GlobalConsumable(models.Model):
    """
    全局包装耗材定义表
    用于定义杯子、杯盖、打包袋等包装耗材的规格及初始化数据
    """
    code = models.CharField(max_length=64, unique=True, verbose_name='耗材编号', db_index=True)
    name = models.CharField(max_length=128, verbose_name='耗材名称')
    initQuantity = models.IntegerField(default=0, verbose_name='初始化数量')
    deviceSN = models.CharField(max_length=128, default='1', verbose_name='设备编号')
    
    description = models.TextField(blank=True, verbose_name='耗材描述')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'global_consumable'
        verbose_name = '全局包装耗材'
        verbose_name_plural = '全局包装耗材列表'

    def __str__(self):
        return f"{self.name} ({self.code})"




