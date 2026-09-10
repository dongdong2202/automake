from rest_framework import serializers
from stores.models import Store
from devices.models import (
    Device, DeviceConfig, DeviceTemperature, DeviceBarrel,
    DeviceSoftConf, DeviceCupSize, DeviceBarrelDict, DevicePoster, DeviceAlarm
)
from global_config.models import (
    DeviceModel, GlobalMenuCategory, GlobalMenuItem, GlobalMenuSku,
    GlobalSkuTemplate, GlobalSkuTemplateIngredient, GlobalSkuIngredient
)
from menus.models import MenuItem, MenuSku
from inventory.models import (
    Material, InventoryRecord, StoreInventory, StoreInventoryRecord, StoreInventoryBatch
)
from orders.models import OrderMain, OrderItem, ProductionTask
from users.models import User, UserProfile
from notifications.models import NotifyEvent


# ============================================================
# 门店 Serializers
# ============================================================
class StoreAdminSerializer(serializers.ModelSerializer):
    device_count = serializers.SerializerMethodField()
    lat = serializers.DecimalField(max_digits=10, decimal_places=6, required=False, allow_null=True)
    lng = serializers.DecimalField(max_digits=10, decimal_places=6, required=False, allow_null=True)

    class Meta:
        model = Store
        fields = [
            'id', 'name', 'description', 'address', 'lat', 'lng',
            'contact_phone', 'code', 'business_hours', 'status',
            'cover_image', 'sort_order', 'device_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_code(self, value):
        if not value:
            return None
        return value

    def get_device_count(self, obj):
        return obj.devices.count()


# ============================================================
# 设备 Serializers
# ============================================================
class DeviceAdminSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    device_model_name = serializers.CharField(source='device_model.name', read_only=True)
    resource_version = serializers.IntegerField(required=False, default=0, allow_null=True)
    key_code = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    extra_config = serializers.JSONField(required=False, default=dict, allow_null=True)
    lat = serializers.DecimalField(max_digits=10, decimal_places=6, required=False, allow_null=True)
    lng = serializers.DecimalField(max_digits=10, decimal_places=6, required=False, allow_null=True)
    is_in_business_hours = serializers.SerializerMethodField()
    business_status = serializers.SerializerMethodField()
    business_status_text = serializers.SerializerMethodField()
    business_hours = serializers.SerializerMethodField()

    class Meta:
        model = Device
        fields = [
            'id', 'device_sn', 'key_code', 'device_name', 'store', 'store_name',
            'device_model', 'device_model_name', 'status', 'firmware_version',
            'resource_version', 'last_heartbeat_at', 'mqtt_topic_prefix',
            'extra_config', 'province', 'city', 'address', 'lat', 'lng', 'gps_coordinate',
            'is_in_business_hours', 'business_status', 'business_status_text', 'business_hours',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_is_in_business_hours(self, obj):
        if not obj.store:
            return False
        return bool(obj.store.is_in_business_hours)

    def get_business_status(self, obj):
        """
        判断设备所在门店是否在营业时间内（北京时间）
        若对应日为 closed 则提示今日休息，不在营业时间提示打烊中，否则提示正在营业中
        """
        if not obj.store:
            return "打烊中"
        text = obj.store.business_status_text
        return "正在营业中" if text == "营业中" else text

    def get_business_status_text(self, obj):
        return self.get_business_status(obj)

    def get_business_hours(self, obj):
        if obj.store and obj.store.business_hours:
            return obj.store.business_hours
        return {}

    def validate_resource_version(self, value):
        if value is None:
            return 0
        return value

    def validate_extra_config(self, value):
        if value is None:
            return {}
        return value

    def validate(self, attrs):
        # 经纬度与 gps_coordinate 自动双向同步
        lat = attrs.get('lat')
        lng = attrs.get('lng')
        gps_coord = attrs.get('gps_coordinate')

        if (lat is not None and lng is not None) and not gps_coord:
            attrs['gps_coordinate'] = f"{lng},{lat}"
        elif gps_coord and (lat is None or lng is None) and ',' in gps_coord:
            try:
                parts = [p.strip() for p in gps_coord.split(',')]
                v1, v2 = float(parts[0]), float(parts[1])
                if v1 > 60:  # 经度在前 (lng, lat)
                    attrs['lng'] = attrs.get('lng') or v1
                    attrs['lat'] = attrs.get('lat') or v2
                else:  # 纬度在前 (lat, lng)
                    attrs['lat'] = attrs.get('lat') or v1
                    attrs['lng'] = attrs.get('lng') or v2
            except Exception:
                pass
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # 保证返回的数据中包含明确的经纬度 (lat/lng)
        lat_val = data.get('lat')
        lng_val = data.get('lng')

        # 1. 尝试从 gps_coordinate 解析
        if (lat_val is None or lng_val is None) and instance.gps_coordinate and ',' in instance.gps_coordinate:
            try:
                parts = [p.strip() for p in instance.gps_coordinate.split(',')]
                v1, v2 = float(parts[0]), float(parts[1])
                if v1 > 60:
                    data['lng'] = lng_val or v1
                    data['lat'] = lat_val or v2
                else:
                    data['lat'] = lat_val or v1
                    data['lng'] = lng_val or v2
            except Exception:
                pass

        # 2. 若依然为空，则自动从绑定的门店继承经纬度
        if (data.get('lat') is None or data.get('lng') is None) and instance.store:
            if instance.store.lat is not None and data.get('lat') is None:
                data['lat'] = float(instance.store.lat)
            if instance.store.lng is not None and data.get('lng') is None:
                data['lng'] = float(instance.store.lng)

        # 3. 确保 gps_coordinate 字段也不为空
        if not data.get('gps_coordinate') and data.get('lat') is not None and data.get('lng') is not None:
            data['gps_coordinate'] = f"{data['lng']},{data['lat']}"

        return data


class DeviceBarrelDictSerializer(serializers.ModelSerializer):
    material_name = serializers.CharField(source='material.name', read_only=True)
    material_type = serializers.CharField(source='material.material_type', read_only=True)
    device_name = serializers.CharField(source='device.device_name', read_only=True)
    device_sn = serializers.CharField(source='device.device_sn', read_only=True)
    store_name = serializers.CharField(source='device.store.name', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = DeviceBarrelDict
        fields = [
            'id', 'barrel_code', 'material', 'material_name', 'material_type',
            'device', 'device_sn', 'device_name', 'store_name', 'created_by_username', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class HybridImageField(serializers.ImageField):
    """
    既支持直接上传二进制文件 (UploadedFile)，
    也支持接收已上传文件的相对路径/URL 字符串 (如 '/media/posters/xxx.png' 或 'posters/xxx.png')。
    """
    def to_internal_value(self, data):
        if data is None or data == '':
            return None
        if isinstance(data, str):
            path = data.strip()
            if path.startswith('/media/'):
                path = path[len('/media/'):]
            elif path.startswith('media/'):
                path = path[len('media/'):]
            elif '/media/' in path:
                path = path.split('/media/')[-1]
            return path
        return super().to_internal_value(data)


class DevicePosterSerializer(serializers.ModelSerializer):
    stores_info = serializers.SerializerMethodField()
    devices_info = serializers.SerializerMethodField()
    version = serializers.IntegerField(required=False, allow_null=True)
    horizontal_image = HybridImageField(required=False, allow_null=True)
    vertical_image = HybridImageField(required=False, allow_null=True)
    banner_image = HybridImageField(required=False, allow_null=True)

    class Meta:
        model = DevicePoster
        fields = [
            'id', 'title', 'horizontal_image', 'vertical_image', 'banner_image',
            'stores', 'devices', 'stores_info', 'devices_info',
            'version', 'remarks', 'sort_order', 'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_stores_info(self, obj):
        return [{'id': s.id, 'name': s.name} for s in obj.stores.all()]

    def get_devices_info(self, obj):
        return [{'id': d.id, 'device_sn': d.device_sn, 'device_name': d.device_name} for d in obj.devices.all()]


# ============================================================
# 物料与进销存 Serializers
# ============================================================
class MaterialSerializer(serializers.ModelSerializer):
    shelf_life = serializers.CharField(required=False, allow_blank=True, default='')
    storage_conditions = serializers.CharField(required=False, allow_blank=True, default='')
    shelf_life_days = serializers.SerializerMethodField()
    default_expiration_date = serializers.SerializerMethodField()

    class Meta:
        model = Material
        fields = [
            'id', 'name', 'code', 'material_type', 'price', 'quantity',
            'unit', 'shelf_life', 'shelf_life_days', 'default_expiration_date',
            'storage_conditions', 'remarks',
            'retrieve_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'shelf_life_days', 'default_expiration_date', 'retrieve_count', 'created_at', 'updated_at']

    def get_shelf_life_days(self, obj):
        from inventory.models import parse_shelf_life_duration_days
        ref_date = obj.created_at.date() if obj.created_at else None
        return parse_shelf_life_duration_days(obj.shelf_life, reference_date=ref_date)

    def get_default_expiration_date(self, obj):
        from inventory.models import calculate_default_expiration_date
        res = calculate_default_expiration_date(obj)
        return str(res) if res else ''

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # 1. 参考价格：取最新入库采购批次的进价
        latest_inbound = instance.records.filter(
            record_type=InventoryRecord.RECORD_TYPE_IN,
            price__isnull=False
        ).order_by('-created_at').first()
        if latest_inbound and latest_inbound.price is not None:
            data['price'] = str(latest_inbound.price)
            data['latest_price'] = str(latest_inbound.price)
        else:
            data['latest_price'] = str(instance.price or '0.00')

        # 2. 有效期：取当前在库批次中最近即将到期的日期 (FEFO 最近到期日)
        from django.utils import timezone
        today = timezone.now().date()
        nearest_batch = instance.records.filter(
            record_type=InventoryRecord.RECORD_TYPE_IN,
            remaining_quantity__gt=0,
            expiration_date__isnull=False
        ).order_by('expiration_date', 'created_at').first()

        if nearest_batch and nearest_batch.expiration_date:
            exp_date = nearest_batch.expiration_date
            days_left = (exp_date - today).days
            data['nearest_expiration_date'] = str(exp_date)
            data['nearest_days_left'] = days_left
            data['nearest_batch_no'] = nearest_batch.batch_no or ''
            if days_left < 0:
                data['nearest_expiration_status'] = 'expired'
            elif days_left <= 30:
                data['nearest_expiration_status'] = 'expiring_soon'
            else:
                data['nearest_expiration_status'] = 'normal'
        else:
            data['nearest_expiration_date'] = None
            data['nearest_days_left'] = None
            data['nearest_batch_no'] = ''
            data['nearest_expiration_status'] = 'permanent'

        return data


class InventoryRecordSerializer(serializers.ModelSerializer):
    material_name = serializers.CharField(source='material.name', read_only=True)
    material_code = serializers.CharField(source='material.code', read_only=True)
    material_unit = serializers.CharField(source='material.unit', read_only=True)
    store_name = serializers.CharField(source='store.name', read_only=True)
    operator_username = serializers.CharField(source='operator.username', read_only=True)
    source_batch_no = serializers.CharField(source='source_batch.batch_no', read_only=True, default='')
    days_until_expiration = serializers.SerializerMethodField()
    expiration_status = serializers.SerializerMethodField()

    class Meta:
        model = InventoryRecord
        fields = [
            'id', 'material', 'material_name', 'material_code', 'material_unit',
            'record_type', 'quantity', 'remaining_quantity', 'batch_no',
            'source_batch', 'source_batch_no', 'price', 'store', 'store_name',
            'operator', 'operator_username', 'expiration_date',
            'days_until_expiration', 'expiration_status',
            'remarks', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']
    def get_days_until_expiration(self, obj):
        if obj.expiration_date:
            from django.utils import timezone
            today = timezone.now().date()
            return (obj.expiration_date - today).days
        return None

    def get_expiration_status(self, obj):
        if not obj.expiration_date:
            return 'permanent'
        from django.utils import timezone
        today = timezone.now().date()
        days_left = (obj.expiration_date - today).days
        if days_left < 0:
            return 'expired'
        elif days_left <= 30:
            return 'expiring_soon'
        return 'normal'


class StoreInventorySerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    material_name = serializers.CharField(source='material.name', read_only=True)
    material_code = serializers.CharField(source='material.code', read_only=True)
    material_type = serializers.CharField(source='material.material_type', read_only=True)
    material_price = serializers.DecimalField(source='material.price', max_digits=10, decimal_places=2, read_only=True)
    unit = serializers.CharField(source='material.unit', read_only=True)
    shelf_life = serializers.CharField(source='material.shelf_life', read_only=True)
    shelf_life_days = serializers.SerializerMethodField()
    storage_conditions = serializers.CharField(source='material.storage_conditions', read_only=True)

    class Meta:
        model = StoreInventory
        fields = [
            'id', 'store', 'store_name', 'material', 'material_name',
            'material_code', 'material_type', 'material_price', 'quantity',
            'unit', 'shelf_life', 'shelf_life_days', 'storage_conditions',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_shelf_life_days(self, obj):
        from inventory.models import parse_shelf_life_duration_days
        ref_date = obj.material.created_at.date() if obj.material and obj.material.created_at else None
        return parse_shelf_life_duration_days(obj.material.shelf_life, reference_date=ref_date)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # 门店库存有效期显示当前在店有效批次中最近到期的日期 (Nearest Expiration Date)
        from django.utils import timezone
        today = timezone.now().date()
        nearest_batch = instance.store.batches.filter(
            material=instance.material,
            quantity__gt=0,
            expiration_date__isnull=False
        ).order_by('expiration_date', 'created_at').first()

        if nearest_batch and nearest_batch.expiration_date:
            exp_date = nearest_batch.expiration_date
            days_left = (exp_date - today).days
            data['nearest_expiration_date'] = str(exp_date)
            data['nearest_days_left'] = days_left
            data['nearest_batch_no'] = nearest_batch.batch_no or ''
            if days_left < 0:
                data['nearest_expiration_status'] = 'expired'
            elif days_left <= 30:
                data['nearest_expiration_status'] = 'expiring_soon'
            else:
                data['nearest_expiration_status'] = 'normal'
        else:
            data['nearest_expiration_date'] = None
            data['nearest_days_left'] = None
            data['nearest_batch_no'] = ''
            data['nearest_expiration_status'] = 'permanent'

        return data


class StoreInventoryRecordSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    material_name = serializers.CharField(source='material.name', read_only=True)
    material_code = serializers.CharField(source='material.code', read_only=True)
    material_unit = serializers.CharField(source='material.unit', read_only=True)
    device_sn = serializers.CharField(source='device.device_sn', read_only=True, default='')
    device_name = serializers.CharField(source='device.device_name', read_only=True, default='')
    operator_username = serializers.CharField(source='operator.username', read_only=True, default='')
    record_type_display = serializers.CharField(source='get_record_type_display', read_only=True)

    class Meta:
        model = StoreInventoryRecord
        fields = [
            'id', 'store', 'store_name', 'material', 'material_name',
            'material_code', 'material_unit', 'device', 'device_sn',
            'device_name', 'record_type', 'record_type_display',
            'quantity', 'batch_no', 'cost_price', 'expiration_date',
            'operator', 'operator_username', 'remarks',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class StoreInventoryBatchSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    material_name = serializers.CharField(source='material.name', read_only=True)
    material_code = serializers.CharField(source='material.code', read_only=True)
    material_unit = serializers.CharField(source='material.unit', read_only=True)
    days_until_expiration = serializers.SerializerMethodField()
    expiration_status = serializers.SerializerMethodField()

    class Meta:
        model = StoreInventoryBatch
        fields = [
            'id', 'store', 'store_name', 'material', 'material_name',
            'material_code', 'material_unit', 'batch_no', 'quantity',
            'cost_price', 'expiration_date', 'days_until_expiration',
            'expiration_status', 'source_inbound', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_days_until_expiration(self, obj):
        if obj.expiration_date:
            from django.utils import timezone
            today = timezone.now().date()
            return (obj.expiration_date - today).days
        return None

    def get_expiration_status(self, obj):
        if not obj.expiration_date:
            return 'permanent'
        from django.utils import timezone
        today = timezone.now().date()
        days_left = (obj.expiration_date - today).days
        if days_left < 0:
            return 'expired'
        elif days_left <= 30:
            return 'expiring_soon'
        return 'normal'

# ============================================================
# 菜单与规格配方 Serializers
# ============================================================
class GlobalSkuTemplateIngredientSerializer(serializers.ModelSerializer):
    material_name = serializers.CharField(source='material.name', read_only=True)
    material_code = serializers.CharField(source='material.code', read_only=True)
    material = serializers.CharField(source='material_id')

    class Meta:
        model = GlobalSkuTemplateIngredient
        fields = ['id', 'material', 'material_name', 'material_code', 'quantity', 'unit']
        read_only_fields = ['id']


class GlobalSkuTemplateSerializer(serializers.ModelSerializer):
    ingredients = GlobalSkuTemplateIngredientSerializer(many=True, required=False)
    sku_count = serializers.SerializerMethodField()

    class Meta:
        model = GlobalSkuTemplate
        fields = [
            'id', 'category', 'name', 'default_price_delta', 'description',
            'is_active', 'sort_order', 'ingredients', 'sku_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_sku_count(self, obj):
        return obj.menu_skus.count()

    def create(self, validated_data):
        ingredients_data = validated_data.pop('ingredients', [])
        template = GlobalSkuTemplate.objects.create(**validated_data)
        for ing_data in ingredients_data:
            mat_name = ing_data.get('material_id') or ing_data.get('material')
            mat = Material.objects.filter(name=mat_name).first() or Material.objects.filter(code=mat_name).first()
            if mat:
                GlobalSkuTemplateIngredient.objects.create(
                    template=template,
                    material=mat,
                    quantity=ing_data.get('quantity', 0),
                    unit=ing_data.get('unit', '') or mat.unit
                )
        return template

    def update(self, instance, validated_data):
        ingredients_data = validated_data.pop('ingredients', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if ingredients_data is not None:
            instance.ingredients.all().delete()
            for ing_data in ingredients_data:
                mat_name = ing_data.get('material_id') or ing_data.get('material')
                mat = Material.objects.filter(name=mat_name).first() or Material.objects.filter(code=mat_name).first()
                if mat:
                    GlobalSkuTemplateIngredient.objects.create(
                        template=instance,
                        material=mat,
                        quantity=ing_data.get('quantity', 0),
                        unit=ing_data.get('unit', '') or mat.unit
                    )
        return instance


class GlobalSkuIngredientSerializer(serializers.ModelSerializer):
    material_name = serializers.CharField(source='material.name', read_only=True)
    material_code = serializers.CharField(source='material.code', read_only=True)
    material = serializers.CharField(source='material_id')

    class Meta:
        model = GlobalSkuIngredient
        fields = ['id', 'material', 'material_name', 'material_code', 'quantity', 'unit']
        read_only_fields = ['id']


class GlobalMenuSkuSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='item.name', read_only=True)
    item_category_name = serializers.CharField(source='item.category.name', read_only=True)
    item_base_price = serializers.IntegerField(source='item.base_price', read_only=True)
    template_name = serializers.CharField(source='template.name', read_only=True)
    template_category = serializers.CharField(source='template.category', read_only=True)
    default_price_delta = serializers.IntegerField(source='template.default_price_delta', read_only=True)
    final_price = serializers.SerializerMethodField()
    is_custom_recipe = serializers.SerializerMethodField()
    ingredients = GlobalSkuIngredientSerializer(many=True, required=False)
    effective_ingredients = serializers.SerializerMethodField()

    class Meta:
        model = GlobalMenuSku
        fields = [
            'id', 'item', 'item_name', 'item_category_name', 'item_base_price',
            'template', 'template_name', 'template_category',
            'default_price_delta', 'price_delta', 'final_price', 'is_custom_recipe',
            'is_active', 'sort_order', 'ingredients', 'effective_ingredients',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_final_price(self, obj):
        base = obj.item.base_price if obj.item else 0
        return base + obj.price_delta

    def get_is_custom_recipe(self, obj):
        return obj.ingredients.exists()

    def get_effective_ingredients(self, obj):
        eff = obj.get_effective_ingredients()
        res = []
        for ing in eff:
            mat = ing.material
            u = ing.unit if ing.unit else mat.unit
            res.append({
                'material': mat.name,
                'material_code': mat.code,
                'quantity': float(ing.quantity),
                'unit': u,
                'is_custom': isinstance(ing, GlobalSkuIngredient)
            })
        return res

    def create(self, validated_data):
        ingredients_data = validated_data.pop('ingredients', [])
        sku = GlobalMenuSku.objects.create(**validated_data)
        for ing_data in ingredients_data:
            mat_name = ing_data.get('material_id') or ing_data.get('material')
            mat = Material.objects.filter(name=mat_name).first() or Material.objects.filter(code=mat_name).first()
            if mat:
                GlobalSkuIngredient.objects.create(
                    sku=sku,
                    material=mat,
                    quantity=ing_data.get('quantity', 0),
                    unit=ing_data.get('unit', '') or mat.unit
                )
        return sku

    def update(self, instance, validated_data):
        ingredients_data = validated_data.pop('ingredients', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if ingredients_data is not None:
            instance.ingredients.all().delete()
            for ing_data in ingredients_data:
                mat_name = ing_data.get('material_id') or ing_data.get('material')
                mat = Material.objects.filter(name=mat_name).first() or Material.objects.filter(code=mat_name).first()
                if mat:
                    GlobalSkuIngredient.objects.create(
                        sku=instance,
                        material=mat,
                        quantity=ing_data.get('quantity', 0),
                        unit=ing_data.get('unit', '') or mat.unit
                    )
        return instance


class GlobalMenuCategorySerializer(serializers.ModelSerializer):
    device_model_name = serializers.CharField(source='device_model.name', read_only=True)
    icon_url = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=500)
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = GlobalMenuCategory
        fields = [
            'id', 'device_model', 'device_model_name', 'name', 'label',
            'icon_url', 'sort_order', 'is_active', 'item_count', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']

    def get_item_count(self, obj):
        return obj.items.count()


class GlobalMenuItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    device_model_name = serializers.CharField(source='category.device_model.name', read_only=True)
    image_url = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=500)
    detail_page = HybridImageField(required=False, allow_null=True)
    skus = GlobalMenuSkuSerializer(many=True, read_only=True)

    class Meta:
        model = GlobalMenuItem
        fields = [
            'id', 'category', 'category_name', 'device_model_name', 'name', 'description',
            'image_url', 'base_price', 'main_ingredients', 'price_description',
            'detail_page', 'sort_order', 'is_active', 'skus', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def create(self, validated_data):
        item = GlobalMenuItem.objects.create(**validated_data)
        skus_data = self.initial_data.get('skus', [])
        if isinstance(skus_data, list):
            for sku_info in skus_data:
                template_id = sku_info.get('template') or sku_info.get('template_id')
                if template_id:
                    template = GlobalSkuTemplate.objects.filter(pk=template_id).first()
                    if template:
                        price_delta = sku_info.get('price_delta')
                        if price_delta is None:
                            price_delta = template.default_price_delta
                        sku = GlobalMenuSku.objects.create(
                            item=item,
                            template=template,
                            price_delta=price_delta,
                            is_active=sku_info.get('is_active', True),
                            sort_order=sku_info.get('sort_order', 0)
                        )
                        if 'ingredients' in sku_info and isinstance(sku_info['ingredients'], list) and sku_info['ingredients']:
                            for ing_data in sku_info['ingredients']:
                                mat_name = ing_data.get('material_id') or ing_data.get('material')
                                mat = Material.objects.filter(name=mat_name).first() or Material.objects.filter(code=mat_name).first()
                                if mat:
                                    GlobalSkuIngredient.objects.create(
                                        sku=sku,
                                        material=mat,
                                        quantity=ing_data.get('quantity', 0),
                                        unit=ing_data.get('unit', '') or mat.unit
                                    )
        return item

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        skus_data = self.initial_data.get('skus', None)
        if skus_data is not None and isinstance(skus_data, list):
            kept_template_ids = []
            for sku_info in skus_data:
                template_id = sku_info.get('template') or sku_info.get('template_id')
                if template_id:
                    template = GlobalSkuTemplate.objects.filter(pk=template_id).first()
                    if template:
                        kept_template_ids.append(template.id)
                        price_delta = sku_info.get('price_delta')
                        if price_delta is None:
                            price_delta = template.default_price_delta
                        sku, _ = GlobalMenuSku.objects.update_or_create(
                            item=instance,
                            template=template,
                            defaults={
                                'price_delta': price_delta,
                                'is_active': sku_info.get('is_active', True),
                                'sort_order': sku_info.get('sort_order', 0),
                            }
                        )
                        if 'ingredients' in sku_info and isinstance(sku_info['ingredients'], list):
                            sku.ingredients.all().delete()
                            for ing_data in sku_info['ingredients']:
                                mat_name = ing_data.get('material_id') or ing_data.get('material')
                                mat = Material.objects.filter(name=mat_name).first() or Material.objects.filter(code=mat_name).first()
                                if mat:
                                    GlobalSkuIngredient.objects.create(
                                        sku=sku,
                                        material=mat,
                                        quantity=ing_data.get('quantity', 0),
                                        unit=ing_data.get('unit', '') or mat.unit
                                    )
            instance.skus.exclude(template_id__in=kept_template_ids).delete()

        return instance


class StoreMenuSkuSerializer(serializers.ModelSerializer):
    global_sku_id = serializers.IntegerField(source='global_sku.id', read_only=True)
    template_id = serializers.IntegerField(source='global_sku.template.id', read_only=True)
    template_name = serializers.CharField(source='global_sku.template.name', read_only=True)
    template_category = serializers.CharField(source='global_sku.template.category', read_only=True)
    global_sku_is_active = serializers.BooleanField(source='global_sku.is_active', read_only=True)
    global_price_delta = serializers.IntegerField(source='global_sku.price_delta', read_only=True)
    global_final_price = serializers.SerializerMethodField()
    final_price = serializers.SerializerMethodField()
    is_custom_recipe = serializers.SerializerMethodField()
    effective_ingredients = serializers.SerializerMethodField()

    class Meta:
        model = MenuSku
        fields = [
            'id', 'item', 'global_sku', 'global_sku_id', 'template_id',
            'template_name', 'template_category', 'global_sku_is_active',
            'global_price_delta', 'global_final_price', 'price_delta',
            'final_price', 'is_custom_recipe', 'effective_ingredients',
            'is_active', 'sort_order'
        ]

    def get_global_final_price(self, obj):
        if obj.item and obj.item.global_item and obj.global_sku:
            return obj.item.global_item.base_price + obj.global_sku.price_delta
        return 0

    def get_final_price(self, obj):
        if obj.item:
            return obj.item.base_price + (obj.price_delta or 0)
        return 0

    def get_is_custom_recipe(self, obj):
        if obj.global_sku:
            return obj.global_sku.ingredients.exists()
        return False

    def get_effective_ingredients(self, obj):
        if obj.global_sku:
            eff = obj.global_sku.get_effective_ingredients()
            res = []
            for ing in eff:
                mat = ing.material
                u = ing.unit if ing.unit else mat.unit
                res.append({
                    'material': mat.name,
                    'material_code': mat.code,
                    'quantity': float(ing.quantity),
                    'unit': u,
                    'is_custom': isinstance(ing, GlobalSkuIngredient)
                })
            return res
        return []


class StoreMenuItemSerializer(serializers.ModelSerializer):
    global_item_name = serializers.CharField(source='global_item.name', read_only=True)
    global_base_price = serializers.IntegerField(source='global_item.base_price', read_only=True)
    category_name = serializers.CharField(source='global_item.category.name', read_only=True)
    store_name = serializers.CharField(source='store.name', read_only=True)
    image_url = serializers.CharField(source='global_item.image_url', read_only=True)
    detail_page = serializers.CharField(source='global_item.detail_page', read_only=True)
    device_model_name = serializers.CharField(source='device_model.name', read_only=True)
    skus = StoreMenuSkuSerializer(many=True, read_only=True)

    class Meta:
        model = MenuItem
        fields = [
            'id', 'store', 'store_name', 'device_model', 'device_model_name', 'global_item',
            'global_item_name', 'category_name', 'global_base_price',
            'image_url', 'detail_page',
            'base_price', 'is_active', 'sort_order', 'skus', 'created_at', 'updated_at'
        ]


# ============================================================
# 订单 Serializers
# ============================================================
class OrderItemAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ['id', 'item_name', 'sku_name', 'unit_price', 'quantity', 'subtotal']


class OrderAdminSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    device_sn = serializers.CharField(source='device.device_sn', read_only=True)
    items = OrderItemAdminSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    pickup_code = serializers.SerializerMethodField()

    class Meta:
        model = OrderMain
        fields = [
            'id', 'order_no', 'order_token', 'user', 'store', 'store_name',
            'device', 'device_sn', 'status', 'status_display',
            'total_amount', 'discount_amount', 'pay_amount', 'remark',
            'paid_at', 'done_at', 'created_at', 'items', 'pickup_code'
        ]

    def get_pickup_code(self, obj):
        if hasattr(obj, 'pickup_code'):
            return obj.pickup_code.code
        return None


# ============================================================
# 告警与通知 Serializers
# ============================================================
class NotifyEventAdminSerializer(serializers.ModelSerializer):
    device_sn = serializers.CharField(source='device.device_sn', read_only=True)
    order_no = serializers.CharField(source='order.order_no', read_only=True)
    handled_by_username = serializers.CharField(source='handled_by.username', read_only=True)
    level_display = serializers.CharField(source='get_level_display', read_only=True)
    event_type_display = serializers.CharField(source='get_event_type_display', read_only=True)

    class Meta:
        model = NotifyEvent
        fields = [
            'id', 'level', 'level_display', 'event_type', 'event_type_display',
            'title', 'content', 'extra_data', 'device', 'device_sn',
            'order', 'order_no', 'is_handled', 'handled_at', 'handled_by',
            'handled_by_username', 'created_at'
        ]


# ============================================================
# 用户 Serializers
# ============================================================
class UserAdminSerializer(serializers.ModelSerializer):
    stores_info = serializers.SerializerMethodField()
    role_display = serializers.CharField(source='get_role_display', read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'phone', 'role', 'role_display', 'stores',
            'stores_info', 'is_active', 'is_staff', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_stores_info(self, obj):
        return [{'id': s.id, 'name': s.name} for s in obj.stores.all()]


class DeviceModelSerializer(serializers.ModelSerializer):
    device_count = serializers.SerializerMethodField()

    class Meta:
        model = DeviceModel
        fields = ['id', 'name', 'code', 'description', 'device_count', 'created_at']
        read_only_fields = ['id', 'created_at']

    def get_device_count(self, obj):
        return obj.devices.count()
