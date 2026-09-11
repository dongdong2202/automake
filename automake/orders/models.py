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
    STATUS_PENDING_PAY = 'created'           # 待支付 / 已创建 (CREATED)
    STATUS_PAID = 'pending_dispense'         # 预扣成功 / 等待出货 (PENDING_DISPENSE)
    STATUS_MAKING = 'making'                 # 制作中 (MAKING)
    STATUS_DONE = 'success'                  # 已完成 / 出货成功 (SUCCESS)
    STATUS_CANCELLED = 'cancelled'           # 已取消 (CANCELLED)
    STATUS_REFUNDING = 'refunding'           # 退款中
    STATUS_REFUNDED = 'refunded'             # 已退款
    STATUS_EXCEPTION = 'failed'              # 异常 / 出货失败 (FAILED)

    STATUS_CHOICES = [
        (STATUS_PENDING_PAY, '已创建'),
        (STATUS_PAID, '待出货'),
        (STATUS_MAKING, '制作中'),
        (STATUS_DONE, '已完成'),
        (STATUS_CANCELLED, '已取消'),
        (STATUS_REFUNDING, '退款中'),
        (STATUS_REFUNDED, '已退款'),
        (STATUS_EXCEPTION, '已失败'),
    ]

    # 订单号（对外展示用，全局唯一）
    order_no = models.CharField(
        max_length=32, unique=True, default=generate_order_no,
        db_index=True, verbose_name='订单号'
    )
    # 订单Token（全局唯一，防重/幂等校验）
    order_token = models.CharField(
        max_length=64, unique=True, db_index=True, null=True, blank=True,
        verbose_name='订单Token'
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
    # 耗材库存是否已扣减 (事务级持久化防二次扣减标记)
    stock_deducted = models.BooleanField(default=False, db_index=True, verbose_name='耗材库存是否已扣减')
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
        'menus.MenuItem', on_delete=models.SET_NULL,
        null=True, related_name='order_items', verbose_name='商品'
    )
    sku = models.ForeignKey(
        'menus.MenuSku', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='order_items', verbose_name='规格'
    )
    # 支持多规格选项选择
    skus = models.ManyToManyField(
        'menus.MenuSku', blank=True, related_name='order_item_list', verbose_name='规格列表'
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
    订单状态变更日志 / 履约流转时间线

    每次订单状态变化都在此记录一条，用于追溯订单完整生命周期。
    order_main 存当前状态，此表存历史轨迹，两者互补，不重复。
    """
    # 动作/事件枚举
    ACTION_CREATE = 'create'                  # 订单创建
    ACTION_WAIT_PAY = 'wait_pay'              # 进入待支付
    ACTION_PAY_SUCCESS = 'pay_success'        # 支付成功
    ACTION_TASK_SENT = 'task_sent'            # 任务下发设备
    ACTION_MAKING_START = 'making_start'      # 设备开始制作
    ACTION_MAKING_DONE = 'making_done'        # 制作完成
    ACTION_PICKUP_GEN = 'pickup_gen'          # 生成取餐码
    ACTION_PICKUP_VERIFIED = 'pickup_verified'# 取餐核销完成
    ACTION_REFUND_APPLIED = 'refund_applied'  # 发起退款 / 退款中
    ACTION_REFUND_SUCCESS = 'refund_success'  # 退款成功
    ACTION_REFUND_FAILED = 'refund_failed'    # 退款失败
    ACTION_CANCELLED = 'cancelled'            # 订单取消
    ACTION_FAILED = 'failed'                  # 制作异常 / 出库失败

    # 操作方类型枚举
    OP_USER = 'user'        # C端顾客
    OP_DEVICE = 'device'    # 咖啡机上位机/硬件
    OP_ADMIN = 'admin'      # 后台管理员
    OP_SYSTEM = 'system'    # 系统内核/定时任务
    OP_WECHAT = 'wechat'    # 微信支付网关/回调

    order = models.ForeignKey(
        OrderMain, on_delete=models.CASCADE,
        related_name='status_logs', verbose_name='订单'
    )
    action = models.CharField(max_length=32, blank=True, default='', db_index=True, verbose_name='事件动作')
    action_name = models.CharField(max_length=64, blank=True, default='', verbose_name='动作名称')
    from_status = models.CharField(max_length=20, blank=True, verbose_name='原状态')
    to_status = models.CharField(max_length=20, verbose_name='新状态')
    operator_type = models.CharField(max_length=20, default=OP_SYSTEM, verbose_name='操作主体类型')
    operator = models.CharField(max_length=64, blank=True, verbose_name='操作方')  # 如：system、user、device
    remark = models.CharField(max_length=256, blank=True, verbose_name='备注')
    payload = models.JSONField(default=dict, blank=True, verbose_name='流转上下文快照')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='发生时间')

    class Meta:
        db_table = 'order_status_log'
        verbose_name = '订单状态日志'
        verbose_name_plural = '订单状态日志'
        ordering = ['created_at']

    @property
    def from_status_display(self):
        status_map = dict(OrderMain.STATUS_CHOICES)
        return status_map.get(self.from_status, self.from_status)

    @property
    def to_status_display(self):
        status_map = dict(OrderMain.STATUS_CHOICES)
        return status_map.get(self.to_status, self.to_status)

    @property
    def status_flow_display(self):
        return f"{self.from_status_display} ➔ {self.to_status_display}"

    def __str__(self):
        return f'{self.order.order_no}: {self.from_status_display} → {self.to_status_display} ({self.action_name or self.action or "update"})'


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


class OrderInvoice(models.Model):
    """
    电子发票记录表
    """
    TYPE_PERSONAL = 'personal'
    TYPE_COMPANY = 'company'
    TYPE_CHOICES = [
        (TYPE_PERSONAL, '个人/非企业单位'),
        (TYPE_COMPANY, '企业单位'),
    ]

    STATUS_SUBMITTED = 'submitted'
    STATUS_ISSUED = 'issued'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_SUBMITTED, '已申请'),
        (STATUS_ISSUED, '已开具'),
        (STATUS_FAILED, '开票失败'),
    ]

    order = models.OneToOneField(
        OrderMain, on_delete=models.CASCADE,
        related_name='invoice', verbose_name='关联订单'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='invoices', verbose_name='申请用户'
    )
    invoice_type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default=TYPE_PERSONAL, verbose_name='发票类型'
    )
    title = models.CharField(max_length=128, verbose_name='发票抬头')
    tax_no = models.CharField(max_length=64, blank=True, default='', verbose_name='企业税号')
    email = models.EmailField(verbose_name='接收邮箱')
    amount = models.IntegerField(verbose_name='开票金额（分）')
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ISSUED, db_index=True, verbose_name='开票状态'
    )
    invoice_url = models.URLField(max_length=512, blank=True, default='', verbose_name='电子发票下载链接')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='申请时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'order_invoice'
        verbose_name = '电子发票'
        verbose_name_plural = '电子发票列表'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.order.order_no} - {self.title} ({self.get_status_display()})"

