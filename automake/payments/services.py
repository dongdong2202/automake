"""
支付业务函数模块

核心函数：
- create_pay_request()      发起支付请求
- verify_pay_callback()     验证并处理微信回调
- process_payment_success() 支付成功后的业务处理链
"""

import json
import logging
import uuid
from django.db import transaction
from django.utils import timezone

from orders.models import OrderMain, OrderStatusLog
from orders.services import create_production_task, update_order_status
from .models import PaymentRecord, PaymentCallbackLog
from utils.wechat import WechatPayV3

logger = logging.getLogger(__name__)


def create_pay_request(order: OrderMain, user) -> dict:
    """
    发起微信 JSAPI 支付请求

    流程：
    1. 检查订单状态（必须为待支付）
    2. 幂等检查（同一订单是否已有未支付记录）
    3. 调用微信支付下单接口
    4. 将支付记录写入数据库
    5. 返回小程序调起支付所需参数

    :param order: 待支付的 OrderMain 对象
    :param user: 支付用户（必须与下单用户一致）
    :return: 小程序 wx.requestPayment() 所需参数字典
    :raises: ValueError 当状态不允许支付或微信接口调用失败时
    """
    # 1. 状态检查
    if not order.can_pay:
        raise ValueError(f'订单状态 [{order.get_status_display()}] 不允许支付')

    # 2. 幂等处理：若已存在 pending 的支付记录，复用其 out_trade_no
    existing = PaymentRecord.objects.filter(
        order=order,
        status=PaymentRecord.STATUS_PENDING
    ).first()

    if existing:
        out_trade_no = existing.out_trade_no
        logger.info(f'复用已有支付记录: out_trade_no={out_trade_no}')
    else:
        # 生成新的商户订单号（微信要求全局唯一）
        out_trade_no = f'{order.order_no}'

    # 3. 调用微信支付下单接口
    try:
        pay_client = WechatPayV3()
        # 商品描述取第一个商品名称
        description = order.items.first().item_name if order.items.exists() else '商品'
        wx_result = pay_client.create_jsapi_order(
            out_trade_no=out_trade_no,
            amount=order.pay_amount,
            openid=user.openid,
            description=description,
        )
    except (ValueError, FileNotFoundError) as e:
        logger.error(f'调用微信支付下单失败: {e}')
        raise ValueError(str(e))

    prepay_id = wx_result.get('prepay_id')
    if not prepay_id:
        raise ValueError('微信支付下单接口返回异常，缺少 prepay_id')

    # 4. 写入支付记录
    with transaction.atomic():
        if existing:
            # 更新 prepay_id（微信下单接口重新调用后 prepay_id 会变）
            existing.pay_params = pay_client.build_pay_params(prepay_id)
            existing.save(update_fields=['pay_params', 'updated_at'])
            payment = existing
        else:
            payment = PaymentRecord.objects.create(
                order=order,
                user=user,
                out_trade_no=out_trade_no,
                amount=order.pay_amount,
                status=PaymentRecord.STATUS_PENDING,
                pay_params=pay_client.build_pay_params(prepay_id),
                pay_method='wechat_jsapi',
            )

    logger.info(f'支付请求创建成功: out_trade_no={out_trade_no}')
    return payment.pay_params


@transaction.atomic
def process_payment_success(order_no: str, transaction_id: str,
                            pay_time: str, wx_amount: int) -> None:
    """
    处理支付成功（由微信回调触发）

    流程：
    1. 查找订单和支付记录（幂等：若已处理则跳过）
    2. 更新 payment_record 状态
    3. 更新 order_main 状态
    4. 写入订单状态日志
    5. 创建生产任务（进入生产链路）
    6. （可选）触发 MQTT 命令下发

    :param order_no: 商户订单号（即 out_trade_no）
    :param transaction_id: 微信交易号
    :param pay_time: 支付完成时间（ISO 格式字符串）
    :param wx_amount: 微信确认的支付金额（分）
    :raises: ValueError 当数据异常时
    """
    # 查找支付记录
    try:
        payment = PaymentRecord.objects.select_related('order', 'user').get(
            out_trade_no=order_no
        )
    except PaymentRecord.DoesNotExist:
        raise ValueError(f'支付记录不存在: out_trade_no={order_no}')

    # 幂等检查：已处理则直接返回
    if payment.status == PaymentRecord.STATUS_SUCCESS:
        logger.info(f'支付回调重复处理，跳过: out_trade_no={order_no}')
        return

    order = payment.order

    # 金额校验（防止金额被篡改）
    if wx_amount != payment.amount:
        logger.error(
            f'支付金额不匹配！订单金额={payment.amount}分，'
            f'微信实付={wx_amount}分，out_trade_no={order_no}'
        )
        raise ValueError('支付金额异常，已拒绝处理')

    # 解析支付时间
    from django.utils.dateparse import parse_datetime
    paid_at = parse_datetime(pay_time) if pay_time else timezone.now()

    # 更新支付记录
    payment.status = PaymentRecord.STATUS_SUCCESS
    payment.transaction_id = transaction_id
    payment.paid_at = paid_at
    payment.save(update_fields=['status', 'transaction_id', 'paid_at', 'updated_at'])

    # 更新订单状态：待支付 → 已支付
    update_order_status(
        order=order,
        new_status=OrderMain.STATUS_PAID,
        operator='system',
        remark=f'微信支付成功，交易号: {transaction_id}',
    )
    order.paid_at = paid_at
    order.save(update_fields=['paid_at'])

    # 创建生产任务（订单进入生产链路）
    try:
        task = create_production_task(order)
        # 调用 MQTT 下发命令给上位机
        from mqtt import issue_make_command
        issue_make_command(order.order_no, task.device.device_sn, task.command_payload)
        logger.info(f'生产任务已创建: task_id={task.id}')
    except ValueError as e:
        logger.error(f'创建生产任务失败: {e}，order_no={order.order_no}')
        # 生产任务创建失败不影响支付成功的记录，需要人工介入
        update_order_status(
            order=order,
            new_status=OrderMain.STATUS_EXCEPTION,
            operator='system',
            remark=f'支付成功但无可用设备: {e}',
        )

    logger.info(f'支付成功处理完成: order_no={order.order_no}')
