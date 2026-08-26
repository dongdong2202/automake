"""
支付模型模块

记录支付请求、微信回调日志，以及退款记录。
支付是订单进入生产链路的分界点。
"""

from django.conf import settings
from django.db import models


class PaymentRecord(models.Model):
    """
    支付记录主表

    每次发起支付对应一条记录。
    同一订单理论上只有一条有效支付记录（幂等控制），但允许重试场景下有多条。
    """

    STATUS_PENDING = 'pending'     # 待支付
    STATUS_SUCCESS = 'success'     # 支付成功
    STATUS_FAILED = 'failed'       # 支付失败
    STATUS_CLOSED = 'closed'       # 已关闭（超时未付）

    STATUS_CHOICES = [
        (STATUS_PENDING, '待支付'),
        (STATUS_SUCCESS, '支付成功'),
        (STATUS_FAILED, '支付失败'),
        (STATUS_CLOSED, '已关闭'),
    ]

    order = models.ForeignKey(
        'orders.OrderMain', on_delete=models.PROTECT,
        related_name='payment_records', verbose_name='关联订单'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='payment_records', verbose_name='支付用户'
    )
    # 微信支付交易号（由微信返回，唯一）
    transaction_id = models.CharField(
        max_length=64, null=True, blank=True,
        unique=True, db_index=True, verbose_name='微信交易号'
    )
    # 商户订单号（传给微信的，与我们的 order_no 对应）
    out_trade_no = models.CharField(
        max_length=64, unique=True, db_index=True, verbose_name='商户订单号'
    )
    # 支付金额（分）
    amount = models.IntegerField(verbose_name='支付金额（分）')
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default=STATUS_PENDING, db_index=True, verbose_name='支付状态'
    )
    # 微信 JSAPI 调起支付的参数（JSON，返回给小程序用）
    pay_params = models.JSONField(default=dict, blank=True, verbose_name='支付参数')
    # 支付完成时间（微信回调中的 success_time）
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name='支付时间')
    # 支付方式（预留，当前仅微信小程序支付）
    pay_method = models.CharField(max_length=32, default='wechat_jsapi', verbose_name='支付方式')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'payment_record'
        verbose_name = '支付记录'
        verbose_name_plural = '支付记录列表'
        ordering = ['-created_at']

    def __str__(self):
        return f'支付 {self.out_trade_no} ({self.get_status_display()})'


class PaymentCallbackLog(models.Model):
    """
    微信支付回调日志

    微信异步通知到达时，先将原始报文落库，再进行业务处理。
    这是幂等和审计的关键记录，业务处理失败时可从此处重放。
    """
    # 商户订单号（用于关联支付记录）
    out_trade_no = models.CharField(
        max_length=64, db_index=True, verbose_name='商户订单号'
    )
    # 微信交易号
    transaction_id = models.CharField(
        max_length=64, blank=True, db_index=True, verbose_name='微信交易号'
    )
    # 原始回调报文（JSON 字符串，原样存储）
    raw_body = models.TextField(verbose_name='原始回调报文')
    # 解密后的资源数据
    decrypted_data = models.JSONField(default=dict, blank=True, verbose_name='解密后数据')
    # 回调处理结果：success / failed
    process_result = models.CharField(max_length=20, default='pending', verbose_name='处理结果')
    process_error = models.TextField(blank=True, verbose_name='处理错误信息')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='接收时间')

    class Meta:
        db_table = 'payment_callback_log'
        verbose_name = '支付回调日志'
        verbose_name_plural = '支付回调日志'
        ordering = ['-created_at']

    def __str__(self):
        return f'回调 {self.out_trade_no}'


class RefundRecord(models.Model):
    """
    退款记录表

    退款与订单解耦存放，方便独立统计退款数据。
    """

    STATUS_PENDING = 'pending'      # 退款申请中
    STATUS_SUCCESS = 'success'      # 退款成功
    STATUS_FAILED = 'failed'        # 退款失败

    STATUS_CHOICES = [
        (STATUS_PENDING, '申请中'),
        (STATUS_SUCCESS, '成功'),
        (STATUS_FAILED, '失败'),
    ]

    order = models.ForeignKey(
        'orders.OrderMain', on_delete=models.PROTECT,
        related_name='refund_records', verbose_name='关联订单'
    )
    payment = models.ForeignKey(
        PaymentRecord, on_delete=models.PROTECT,
        related_name='refund_records', verbose_name='关联支付'
    )
    # 微信退款单号
    refund_id = models.CharField(
        max_length=64, null=True, blank=True,
        db_index=True, verbose_name='微信退款单号'
    )
    out_refund_no = models.CharField(
        max_length=64, unique=True, db_index=True, verbose_name='商户退款单号'
    )
    refund_amount = models.IntegerField(verbose_name='退款金额（分）')
    reason = models.CharField(max_length=256, blank=True, verbose_name='退款原因')
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default=STATUS_PENDING, verbose_name='退款状态'
    )
    refunded_at = models.DateTimeField(null=True, blank=True, verbose_name='退款完成时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='申请时间')

    class Meta:
        db_table = 'refund_record'
        verbose_name = '退款记录'
        verbose_name_plural = '退款记录列表'
        ordering = ['-created_at']

    def __str__(self):
        return f'退款 {self.out_refund_no}'
