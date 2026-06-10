"""
订单模型模块

订单是业务核心主线，连接用户、门店、设备、支付。

表结构：
  OrderMain（订单主表）← OrderItem（订单明细）
  OrderMain → OrderStatusLog（状态流水）
  OrderMain → ProductionTask（生产任务）
"""

from django.conf import settings
from django.db import models
from django.utils import timezone
import uuid


def generate_order_no():
    """
    生成订单号
    格式：YYYYMMDDHHMMSS + 6位随机字符
    保证在同一秒内不重复（UUID 补足随机性）
    """
    import random
    import string
    now_str = timezone.now().strftime('%Y%m%d%H%M%S')
    suffix = ''.join(random.choices(string.digits, k=6))
    return f'{now_str}{suffix}'


class OrderMain(models.Model):
    """
    订单主表

    存储订单的核心信息和当前状态。
    历史状态变化存入 OrderStatusLog，不在此表重复。
    """

    # ---- 订单状态枚举 ----
    STATUS_PENDING_PAY = 'pending_pay'       # 待支付
    STATUS_PAID = 'paid'                     # 已支付，待生产
    STATUS_MAKING = 'making'                 # 制作中
    STATUS_DONE = 'done'                     # 已完成（出杯）
    STATUS_CANCELLED = 'cancelled'           # 已取消
    STATUS_REFUNDING = 'refunding'           # 退款中
    STATUS_REFUNDED = 'refunded'             # 已退款
    STATUS_EXCEPTION = 'exception'           # 异常

    STATUS_CHOICES = [
        (STATUS_PENDING_PAY, '待支付'),
        (STATUS_PAID, '已支付'),
        (STATUS_MAKING, '制作中'),
        (STATUS_DONE, '已完成'),
        (STATUS_CANCELLED, '已取消'),
        (STATUS_REFUNDING, '退款中'),
        (STATUS_REFUNDED, '已退款'),
        (STATUS_EXCEPTION, '异常'),
    ]

    # 订单号（对外展示用，全局唯一）
    order_no = models.CharField(
        max_length=32, unique=True, default=generate_order_no,
        db_index=True, verbose_name='订单号'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='orders', verbose_name='下单用户'
    )
    store = models.ForeignKey(
        'stores.Store', on_delete=models.PROTECT,
        related_name='orders', verbose_name='下单门店'
    )
    # 制作该订单的设备（支付确认后分配）
    device = models.ForeignKey(
        'devices.Device', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='orders', verbose_name='制作设备'
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default=STATUS_PENDING_PAY, db_index=True, verbose_name='订单状态'
    )
    # 实付金额（分）
    total_amount = models.IntegerField(default=0, verbose_name='总金额（分）')
    # 优惠金额（分，预留）
    discount_amount = models.IntegerField(default=0, verbose_name='优惠金额（分）')
    # 实付金额 = total_amount - discount_amount
    pay_amount = models.IntegerField(default=0, verbose_name='实付金额（分）')
    # 备注（用户下单时填写）
    remark = models.CharField(max_length=256, blank=True, verbose_name='备注')
    # 支付时间
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name='支付时间')
    # 完成时间（出杯完成）
    done_at = models.DateTimeField(null=True, blank=True, verbose_name='完成时间')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'order_main'
        verbose_name = '订单'
        verbose_name_plural = '订单列表'
        ordering = ['-created_at']

    def __str__(self):
        return f'订单 {self.order_no}'

    @property
    def can_pay(self):
        """判断订单是否可以支付"""
        return self.status == self.STATUS_PENDING_PAY

    @property
    def can_cancel(self):
        """判断订单是否可以取消（只有待支付或已支付可取消）"""
        return self.status in (self.STATUS_PENDING_PAY, self.STATUS_PAID)


class OrderItem(models.Model):
    """
    订单明细表

    每条记录对应一个 SKU 的购买行为。
    单价和总价在下单时快照，防止后续改价导致数据不一致。
    """
    order = models.ForeignKey(
        OrderMain, on_delete=models.CASCADE,
        related_name='items', verbose_name='所属订单'
    )
    # 商品快照（防止菜单修改后影响历史订单）
    item = models.ForeignKey(
        'menus.MenuItem', on_delete=models.PROTECT,
        null=True, related_name='order_items', verbose_name='商品'
    )
    sku = models.ForeignKey(
        'menus.MenuSku', on_delete=models.PROTECT,
        null=True, blank=True, related_name='order_items', verbose_name='规格'
    )
    # 下单时快照的商品名和规格名（防止菜单修改后历史订单展示异常）
    item_name = models.CharField(max_length=128, verbose_name='商品名称快照')
    sku_name = models.CharField(max_length=64, blank=True, verbose_name='规格名称快照')
    # 单价（分，下单时快照）
    unit_price = models.IntegerField(verbose_name='单价（分）')
    quantity = models.IntegerField(default=1, verbose_name='数量')
    # 小计 = unit_price × quantity（下单时计算并固化）
    subtotal = models.IntegerField(verbose_name='小计（分）')

    class Meta:
        db_table = 'order_item'
        verbose_name = '订单明细'
        verbose_name_plural = '订单明细列表'

    def __str__(self):
        return f'{self.order.order_no} - {self.item_name}'


class OrderStatusLog(models.Model):
    """
    订单状态变更日志

    每次订单状态变化都在此记录一条，用于追溯订单完整生命周期。
    order_main 存当前状态，此表存历史轨迹，两者互补，不重复。
    """
    order = models.ForeignKey(
        OrderMain, on_delete=models.CASCADE,
        related_name='status_logs', verbose_name='订单'
    )
    from_status = models.CharField(max_length=20, blank=True, verbose_name='原状态')
    to_status = models.CharField(max_length=20, verbose_name='新状态')
    operator = models.CharField(max_length=64, blank=True, verbose_name='操作方')  # 如：system、user、device
    remark = models.CharField(max_length=256, blank=True, verbose_name='备注')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='发生时间')

    class Meta:
        db_table = 'order_status_log'
        verbose_name = '订单状态日志'
        verbose_name_plural = '订单状态日志'
        ordering = ['created_at']

    def __str__(self):
        return f'{self.order.order_no}: {self.from_status} → {self.to_status}'


class ProductionTask(models.Model):
    """
    生产任务表

    订单支付成功后，从订单域进入生产域，创建此记录。
    是云端命令与上位机执行之间的桥梁。
    """

    TASK_PENDING = 'pending'      # 待下发
    TASK_SENT = 'sent'            # 已下发给设备
    TASK_MAKING = 'making'        # 制作中
    TASK_DONE = 'done'            # 制作完成
    TASK_FAILED = 'failed'        # 制作失败

    TASK_STATUS_CHOICES = [
        (TASK_PENDING, '待下发'),
        (TASK_SENT, '已下发'),
        (TASK_MAKING, '制作中'),
        (TASK_DONE, '制作完成'),
        (TASK_FAILED, '制作失败'),
    ]

    order = models.OneToOneField(
        OrderMain, on_delete=models.CASCADE,
        related_name='production_task', verbose_name='关联订单'
    )
    device = models.ForeignKey(
        'devices.Device', on_delete=models.SET_NULL,
        null=True, related_name='production_tasks', verbose_name='执行设备'
    )
    status = models.CharField(
        max_length=20, choices=TASK_STATUS_CHOICES,
        default=TASK_PENDING, db_index=True, verbose_name='任务状态'
    )
    # 下发给设备的完整命令包
    command_payload = models.JSONField(default=dict, verbose_name='命令数据')
    # 失败原因（设备回传）
    failure_reason = models.CharField(max_length=256, blank=True, verbose_name='失败原因')
    sent_at = models.DateTimeField(null=True, blank=True, verbose_name='下发时间')
    done_at = models.DateTimeField(null=True, blank=True, verbose_name='完成时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'production_task'
        verbose_name = '生产任务'
        verbose_name_plural = '生产任务列表'
        ordering = ['-created_at']

    def __str__(self):
        return f'生产任务 {self.order.order_no}'
