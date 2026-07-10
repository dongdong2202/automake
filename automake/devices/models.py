"""
设备模型模块

设备（Device）是连接云端与实体制作机器的核心实体。
云端通过 MQTT 向设备下发命令，设备通过 HTTP 上报状态。
"""

from django.db import models


class Device(models.Model):
    """
    设备主表

    每台上位机/制作机器对应一条记录。
    device_sn 是设备唯一序列号，由硬件出厂时固化，用于注册时鉴别身份。
    """

    STATUS_ONLINE = 'online'      # 在线
    STATUS_OFFLINE = 'offline'    # 离线
    STATUS_FAULT = 'fault'        # 故障

    STATUS_CHOICES = [
        (STATUS_ONLINE, '在线'),
        (STATUS_OFFLINE, '离线'),
        (STATUS_FAULT, '故障'),
    ]

    store = models.ForeignKey(
        'stores.Store', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='devices', verbose_name='所属门店'
    )
    device_sn = models.CharField(
        max_length=128, unique=True, db_index=True, verbose_name='设备序列号'
    )
    key_code = models.CharField(
        max_length=32,   null=True, blank=True, verbose_name='门店注册码')
    device_name = models.CharField(max_length=128, blank=True, verbose_name='设备名称')
    # 设备型号
    device_model = models.ForeignKey(
        'global_config.DeviceModel', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='devices', verbose_name='设备型号'
    )

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default=STATUS_OFFLINE, db_index=True, verbose_name='设备状态'
    )
    # 设备当前固件版本
    firmware_version = models.CharField(max_length=64, blank=True, verbose_name='固件版本')
    # 云端分配给设备的资源包版本号（用于云边同步判断）
    resource_version = models.IntegerField(default=0, verbose_name='资源版本号')
    # 最后心跳时间
    last_heartbeat_at = models.DateTimeField(null=True, blank=True, verbose_name='最后心跳时间')
    # MQTT Topic 前缀（设备订阅/发布用）
    mqtt_topic_prefix = models.CharField(max_length=256, blank=True, verbose_name='MQTT Topic 前缀')
    # 额外配置（JSON 格式，如设备参数、能力列表等）
    extra_config = models.JSONField(default=dict, blank=True, verbose_name='扩展配置')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='注册时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'device'
        verbose_name = '设备'
        verbose_name_plural = '设备列表'

    def __str__(self):
        return f'{self.device_sn} ({self.get_status_display()})'


class DeviceStatusLog(models.Model):
    """
    设备状态变更日志

    记录设备的每次状态变化（上线/离线/故障），
    用于统计设备在线率、故障率等看板指标。
    """
    device = models.ForeignKey(
        Device, on_delete=models.CASCADE,
        related_name='status_logs', verbose_name='设备'
    )
    status = models.CharField(max_length=20, verbose_name='状态')
    remark = models.CharField(max_length=256, blank=True, verbose_name='备注')
    # 上位机上报的原始数据（便于排错）
    raw_payload = models.JSONField(default=dict, blank=True, verbose_name='原始上报数据')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='发生时间')

    class Meta:
        db_table = 'device_status_log'
        verbose_name = '设备状态日志'
        verbose_name_plural = '设备状态日志'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.device.device_sn} → {self.status}'


class DeviceCommand(models.Model):
    """
    设备命令表

    云端向上位机下发的命令记录。
    命令发出后，通过 MQTT 发送；上位机执行后，通过状态回传确认。
    """

    CMD_MAKE = 'make'           # 制作出杯命令
    CMD_CANCEL = 'cancel'       # 取消制作
    CMD_RESET = 'reset'         # 设备复位
    CMD_SYNC = 'sync_resource'  # 同步资源

    CMD_CHOICES = [
        (CMD_MAKE, '制作命令'),
        (CMD_CANCEL, '取消命令'),
        (CMD_RESET, '复位命令'),
        (CMD_SYNC, '资源同步'),
    ]

    PENDING = 'pending'       # 待发送
    SENT = 'sent'             # 已发送
    CONFIRMED = 'confirmed'   # 上位机已确认
    FAILED = 'failed'         # 发送失败

    STATUS_CHOICES = [
        (PENDING, '待发送'),
        (SENT, '已发送'),
        (CONFIRMED, '已确认'),
        (FAILED, '失败'),
    ]

    device = models.ForeignKey(
        Device, on_delete=models.CASCADE,
        related_name='commands', verbose_name='目标设备'
    )
    order = models.ForeignKey(
        'orders.OrderMain', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='device_commands', verbose_name='关联订单'
    )
    command_type = models.CharField(
        max_length=32, choices=CMD_CHOICES, verbose_name='命令类型'
    )
    # 命令内容（JSON 格式，包含具体参数）
    payload = models.JSONField(default=dict, verbose_name='命令内容')
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default=PENDING, db_index=True, verbose_name='发送状态'
    )
    sent_at = models.DateTimeField(null=True, blank=True, verbose_name='发送时间')
    confirmed_at = models.DateTimeField(null=True, blank=True, verbose_name='确认时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'device_command'
        verbose_name = '设备命令'
        verbose_name_plural = '设备命令列表'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.device.device_sn} - {self.command_type} ({self.status})'


class DeviceAlarm(models.Model):
    """
    设备告警表

    当设备出现故障、物料不足等异常时生成告警记录。
    """
    ALARM_FAULT = 'fault'              # 设备故障
    ALARM_LOW_MATERIAL = 'low_material'  # 物料不足
    ALARM_OFFLINE = 'offline'          # 设备离线

    ALARM_CHOICES = [
        (ALARM_FAULT, '设备故障'),
        (ALARM_LOW_MATERIAL, '物料不足'),
        (ALARM_OFFLINE, '设备离线'),
    ]

    device = models.ForeignKey(
        Device, on_delete=models.CASCADE,
        related_name='alarms', verbose_name='设备'
    )
    alarm_type = models.CharField(
        max_length=32, choices=ALARM_CHOICES, verbose_name='告警类型'
    )
    detail = models.TextField(blank=True, verbose_name='告警详情')
    is_resolved = models.BooleanField(default=False, db_index=True, verbose_name='是否已处理')
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name='处理时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='告警时间')

    class Meta:
        db_table = 'device_alarm'
        verbose_name = '设备告警'
        verbose_name_plural = '设备告警列表'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.device.device_sn} - {self.get_alarm_type_display()}'


class DeviceMaterialStock(models.Model):
    """
    设备物料库存表 (DB_Book_Stock)
    
    """
    device = models.ForeignKey(
        'devices.Device', on_delete=models.CASCADE,
        related_name='material_stocks', verbose_name='设备'
    )
    
    name = models.ForeignKey(
        'inventory.Material', to_field='name',
        on_delete=models.CASCADE, db_column='name', verbose_name='物料名称'
    )
    initHight = models.IntegerField(default=100, verbose_name='满料高度')
    code = models.CharField(max_length=64, unique=True, verbose_name='物料编码')
    unit = models.CharField(max_length=16, default='cm', verbose_name='标准单位')
    warn_level = models.DecimalField(max_digits=5, decimal_places=2, default=10.00, verbose_name='预警高度')
    warn_level_1 = models.DecimalField(max_digits=10, decimal_places=2, default=10.00, verbose_name='预警高度1')
    warn_level_2 = models.DecimalField(max_digits=20, decimal_places=2, default=5.00, verbose_name='预警高度2')
    warn_level_3 = models.DecimalField(max_digits=30, decimal_places=2, default=2.00, verbose_name='预警高度3')
    current_remaining_height = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name='当前剩余高度')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'device_material_stock'
        unique_together = ('device', 'code')
        verbose_name = '设备物料库存'
        verbose_name_plural = '设备物料库存列表'

    def __str__(self):
        return f"{self.device.device_sn} - {self.name_id} ({self.code})"


class DeviceConsumableStock(models.Model):
    """
    设备耗材库存表 (杯子、封口膜、杯盖等)

    由于耗材无法通过上位机进行实时更新剩余数量，只能依赖服务器在订单完成后进行计算扣减。
    """
    CONSUMABLE_CHOICES = [
        ('paperL', '大号纸杯'),
        ('paperM', '中号纸杯'),
        ('plasticL', '大号塑料杯'),
        ('plasticM', '中号塑料杯'),
        ('membrane', '封口膜'),
        ('lid', '杯盖'),
    ]

    device = models.ForeignKey(
        'devices.Device', on_delete=models.CASCADE,
        related_name='consumable_stocks', verbose_name='设备'
    )
    code = models.ForeignKey(
        'inventory.Material', to_field='code',
        on_delete=models.CASCADE, db_column='code',
        limit_choices_to={'material_type': 'consumable'}, verbose_name='耗材编码'
    )
    init_quantity = models.IntegerField(default=100, verbose_name='满载数量')
    quantity = models.IntegerField(default=100, verbose_name='当前剩余数量')
    unit = models.CharField(max_length=16, default='个', verbose_name='标准单位')
    warn_level = models.IntegerField(default=10, verbose_name='预警数量')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'device_consumable_stock'
        unique_together = ('device', 'code')
        verbose_name = '设备耗材库存'
        verbose_name_plural = '设备耗材库存列表'

    def __str__(self):
        return f"{self.device.device_sn} - {self.code_id}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # 自动同步更新 Redis 虚拟库存
        try:
            from django_redis import get_redis_connection
            redis_conn = get_redis_connection("default")
            key = f"automake:stock:{self.device.device_sn}:{self.code_id}"
            # Redis 库存存储数值为实际数量 * 100
            redis_conn.set(key, int(self.quantity * 100))
        except Exception:
            pass

def default_temperature_config():
    return {}

def default_transfer_config():
    return []

def default_barrel_config():
    return {}


class DeviceConfig(models.Model):
    """设备全局配置 (如转运坐标)"""
    device = models.OneToOneField('devices.Device', on_delete=models.CASCADE, related_name='config', verbose_name='所属设备')
    transfer = models.CharField(
        max_length=512, 
        default="10000,20000,30000,40000,50000,60000,70000,80000,90000,100000,110000,120000,130000,140000",
        verbose_name='转运模块配置(坐标值,用逗号分隔)'
    )
    
    class Meta:
        db_table = 'device_config'
        verbose_name = '设备全局配置'
        verbose_name_plural = '设备全局配置列表'
        
    def __str__(self):
        return f'{self.device.device_sn} 全局配置'

class DeviceTemperature(models.Model):
    """设备温度配置"""
    config = models.ForeignKey('devices.DeviceConfig', on_delete=models.CASCADE, related_name='temperatures', verbose_name='所属配置', null=True)
    device = models.ForeignKey('devices.Device', on_delete=models.CASCADE, related_name='temperatures', verbose_name='所属设备(冗余)', null=True)
    key = models.CharField(max_length=32, verbose_name='温度标识(例如 t1)')
    value = models.IntegerField(verbose_name='设定温度(摄氏度)')
    
    class Meta:
        db_table = 'device_temperature_config'
        unique_together = ('config', 'key')
        verbose_name = '设备温度项'
        verbose_name_plural = '设备温度项列表'
        
class DeviceBarrel(models.Model):
    """设备料筒配置"""
    config = models.ForeignKey('devices.DeviceConfig', on_delete=models.CASCADE, related_name='barrels', verbose_name='所属配置', null=True)
    device = models.ForeignKey('devices.Device', on_delete=models.CASCADE, related_name='barrels', verbose_name='所属设备(冗余)', null=True)
    barrel_id = models.CharField(max_length=32, verbose_name='料筒编号(例如 b01)')
    pump_type = models.CharField(max_length=32, default="thin", verbose_name='泵类型')
    pump_coeff = models.IntegerField(default=100, verbose_name='泵系数')
    max_v = models.IntegerField(default=40000, verbose_name='最大容量')
    base_area = models.IntegerField(default=800, verbose_name='底面积(cm²)')
    
    class Meta:
        db_table = 'device_barrel_config'
        unique_together = ('device', 'barrel_id')
        verbose_name = '设备料筒项'
        verbose_name_plural = '设备料筒项列表'

class DeviceSoftConf(models.Model):
    """设备出餐及软性配置"""
    device = models.OneToOneField('devices.Device', on_delete=models.CASCADE, related_name='soft_conf', verbose_name='所属设备')
    max_vacancies = models.IntegerField(default=3, verbose_name='出餐口数量(maxVacancies)')
    sep_chunk = models.IntegerField(default=2, verbose_name='分单块大小(sepChunk)')
    ice_size = models.IntegerField(default=15, verbose_name='冰块大小(iceSize, ml)')

    class Meta:
        db_table = 'device_soft_conf'
        verbose_name = '设备出餐配置'
        verbose_name_plural = '设备出餐配置列表'
        
    def __str__(self):
        return f'{self.device.device_sn} 出餐配置'

class DeviceCupSize(models.Model):
    """设备杯型容量配置"""
    soft_conf = models.ForeignKey(DeviceSoftConf, on_delete=models.CASCADE, related_name='cup_sizes', verbose_name='所属配置', null=True)
    device = models.ForeignKey('devices.Device', on_delete=models.CASCADE, related_name='cup_sizes', verbose_name='所属设备(冗余)', null=True)
    key = models.CharField(max_length=32, verbose_name='杯型标识(例如 m/l)')
    capacity = models.IntegerField(verbose_name='容量(ml)')

    class Meta:
        db_table = 'device_cup_size_config'
        unique_together = ('soft_conf', 'key')
        verbose_name = '设备杯型容量'
        verbose_name_plural = '设备杯型容量列表'
