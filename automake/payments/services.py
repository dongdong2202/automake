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


def refund_order(order: OrderMain, reason: str = "库存不足，系统自动退款"):
    """
    微信退款接口调用与记录（真实退款代码）
    """
    from .models import RefundRecord, PaymentRecord
    from utils.wechat import WechatPayV3
    
    payment = PaymentRecord.objects.filter(order=order, status=PaymentRecord.STATUS_SUCCESS).first()
    if not payment:
        logger.warning(f"订单 {order.order_no} 没有成功的支付记录，无法退款")
        return

    # 检查是否已存在成功退款记录
    if RefundRecord.objects.filter(order=order, status=RefundRecord.STATUS_SUCCESS).exists():
        logger.info(f"订单 {order.order_no} 已经退款，无需重复退款")
        return

    import uuid
    out_refund_no = f"RF-{uuid.uuid4().hex[:16]}"
    
    try:
        pay_client = WechatPayV3()
        transaction_id = payment.transaction_id
        if not transaction_id:
            raise ValueError("支付记录中没有有效的微信交易号，无法退款")
            
        wx_result = pay_client.apply_refund(
            out_refund_no=out_refund_no,
            transaction_id=transaction_id,
            refund_amount=payment.amount,
            total_amount=payment.amount,
            reason=reason
        )
        
        refund_id = wx_result.get('refund_id')
        wx_status = wx_result.get('status', 'SUCCESS').upper()
        
        status_map = {
            'SUCCESS': RefundRecord.STATUS_SUCCESS,
            'PROCESSING': RefundRecord.STATUS_PENDING,
            'ABNORMAL': RefundRecord.STATUS_FAILED,
            'CLOSED': RefundRecord.STATUS_FAILED,
        }
        record_status = status_map.get(wx_status, RefundRecord.STATUS_SUCCESS)
        
        refund = RefundRecord.objects.create(
            order=order,
            payment=payment,
            refund_id=refund_id,
            out_refund_no=out_refund_no,
            refund_amount=payment.amount,
            reason=reason,
            status=record_status,
            refunded_at=timezone.now() if record_status == RefundRecord.STATUS_SUCCESS else None
        )
        
        # 同步更新订单主表状态
        from orders.models import OrderStatusLog
        old_status = order.status
        if record_status == RefundRecord.STATUS_SUCCESS:
            order.status = OrderMain.STATUS_REFUNDED
        elif record_status == RefundRecord.STATUS_PENDING:
            order.status = OrderMain.STATUS_REFUNDING
        else:
            order.status = OrderMain.STATUS_EXCEPTION
            
        order.save(update_fields=['status', 'updated_at'])
        
        OrderStatusLog.objects.create(
            order=order,
            from_status=old_status,
            to_status=order.status,
            operator="System",
            remark=f"发起退款，退款单号: {out_refund_no}, 状态: {record_status}"
        )
        logger.info(f"已处理真实退款: order_no={order.order_no}, out_refund_no={out_refund_no}, refund_id={refund_id}, status={record_status}")
    except Exception as e:
        logger.exception(f"调用微信退款接口失败: order_no={order.order_no}, error={e}")
        # 创建一个失败的退款记录
        RefundRecord.objects.create(
            order=order,
            payment=payment,
            out_refund_no=out_refund_no,
            refund_amount=payment.amount,
            reason=reason,
            status=RefundRecord.STATUS_FAILED
        )
        raise e



def process_payment_success(order_no: str, transaction_id: str,
                            pay_time: str, wx_amount: int) -> None:
    """
    处理支付成功（由微信回调触发）。

    """
    from orders.services import get_redis_stock_key, MenuSku
    from decimal import Decimal
    from django_redis import get_redis_connection
    
    # 查找支付记录
    try:
        payment = PaymentRecord.objects.select_related('order', 'user').get(
            out_trade_no=order_no
        )
    except PaymentRecord.DoesNotExist:
        raise ValueError(f'支付记录不存在: out_trade_no={order_no}')

    # 幂等检查
    if payment.status == PaymentRecord.STATUS_SUCCESS:
        logger.info(f'支付回调已处理，跳过: out_trade_no={order_no}')
        return

    order = payment.order

    # 金额校验
    if wx_amount != payment.amount:
        logger.error(f'支付金额不匹配！订单={payment.amount}，实付={wx_amount}')
        raise ValueError('支付金额异常，已拒绝处理')

    from django.utils.dateparse import parse_datetime
    paid_at = parse_datetime(pay_time) if pay_time else timezone.now()

    # 提前生成全局唯一的 OrderToken (UUID)，以便全链路 JSON 日志追踪
    order_token = str(uuid.uuid4())

    # 0. 校验系统等待制作的订单数量是否小于 50
    waiting_count = OrderMain.objects.filter(
        status__in=[OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING]
    ).exclude(pk=order.pk).count()
    if waiting_count >= 100:
        logger.warning(f"支付回调校验失败：系统等待制作的订单已达上限 {waiting_count}，拒绝支付出餐")
        with transaction.atomic():
            payment.status = PaymentRecord.STATUS_SUCCESS
            payment.transaction_id = transaction_id
            payment.paid_at = paid_at
            payment.save(update_fields=['status', 'transaction_id', 'paid_at', 'updated_at'])
            
            update_order_status(
                order=order,
                new_status=OrderMain.STATUS_EXCEPTION,
                operator='system',
                remark='系统制作队列已满，自动退款'
            )
            refund_order(order, reason="系统繁忙自动退款")
        raise ValueError("系统繁忙，已自动退款")

    # 1. 调用 calculate_required_materials 计算订单所需的所有物料总量，并过滤出该订单所需的耗材总量
    items_data = []
    for item in order.items.prefetch_related('skus').all():
        skus = list(item.skus.all())
        if not skus and item.item:
            base_sku = MenuSku.objects.filter(item=item.item, is_active=True).first()
            if base_sku:
                skus = [base_sku]
        items_data.append({
            'item': item.item,
            'skus': skus,
            'quantity': item.quantity
        })

    from orders.services import calculate_required_materials
    all_materials = calculate_required_materials(items_data)

    from inventory.models import Material
    consumable_codes = set(
        Material.objects.filter(
            code__in=all_materials.keys(),
            material_type=Material.TYPE_CONSUMABLE
        ).values_list('code', flat=True)
    )

    required_cups = {
        code: qty for code, qty in all_materials.items() if code in consumable_codes
    }
    device = order.device
    if not device:
        raise ValueError("订单未绑定设备")

    redis_conn = get_redis_connection("default")

    # 【支付流程 4 - 步骤 1：并发防超卖预扣】
    # 定制的 LUA 预扣脚本：扣减后余额不低于极低阈值 (critical_val)。利用 Redis 单线程机制实现原子操作，防止并发超卖。
    LUA_DECR_CUP = """
    local stock = tonumber(redis.call('get', KEYS[1]) or "0")
    local num = tonumber(ARGV[1])
    local crit = tonumber(ARGV[2])
    if (stock - num) >= crit then
        redis.call('decrby', KEYS[1], num)
        return 1 -- 成功
    else
        return 0 -- 极度缺货
    end
    """

    # 核心日志点 1：原子预扣开始 (JSON 结构化日志)
    logger.info(json.dumps({
        "event": "redis_precheck_start",
        "order_no": order.order_no,
        "OrderToken": order_token,
        "device_sn": device.device_sn,
        "required_cups": {code: float(qty) for code, qty in required_cups.items()}
    }, ensure_ascii=False))

    # 执行 Redis 原子预扣 (Lua 脚本)
    redis_deducted = []
    redis_success = True
    for cup_code, qty in required_cups.items():
        key = get_redis_stock_key(device.device_sn, cup_code)
        val_to_deduct = int(qty * 100)
        
        from devices.models import DeviceConsumableStock, DeviceMaterialStock
        stock_config = DeviceConsumableStock.objects.filter(device=device, code=cup_code).first()
        if stock_config:
            warn_level = float(stock_config.warn_level)
        else:
            material_config = DeviceMaterialStock.objects.filter(device=device, code=cup_code).first()
            warn_level = float(material_config.warn_level) if material_config else 0
            
        critical_val = int(warn_level * 0.2 * 100)

        res = redis_conn.register_script(LUA_DECR_CUP)(keys=[key], args=[val_to_deduct, critical_val])
        
        logger.info(json.dumps({
            "event": "redis_precheck_deduct",
            "order_no": order.order_no,
            "OrderToken": order_token,
            "material_code": cup_code,
            "quantity_deduct_val": val_to_deduct,
            "critical_val": critical_val,
            "status": "success" if res == 1 else "failed"
        }, ensure_ascii=False))

        if res == 1:
            redis_deducted.append((cup_code, val_to_deduct))
        else:
            redis_success = False
            break

    if not redis_success:
        # Redis 预扣失败，执行反向补偿/释放已扣除的虚拟杯子库存
        for code, val in redis_deducted:
            key = get_redis_stock_key(device.device_sn, code)
            redis_conn.incrby(key, val)
            logger.info(json.dumps({
                "event": "redis_precheck_compensate",
                "order_no": order.order_no,
                "OrderToken": order_token,
                "material_code": code,
                "quantity_compensate_val": val
            }, ensure_ascii=False))
        
        # 预扣失败说明机器已经缺货，直接标记订单异常并向用户自动退款
        with transaction.atomic():
            payment.status = PaymentRecord.STATUS_SUCCESS
            payment.transaction_id = transaction_id
            payment.paid_at = paid_at
            payment.save(update_fields=['status', 'transaction_id', 'paid_at', 'updated_at'])
            
            update_order_status(
                order=order,
                new_status=OrderMain.STATUS_EXCEPTION, # failed
                operator='system',
                remark='库存预扣失败，自动退款'
            )
            refund_order(order, reason="可用库存不足自动退款")
        raise ValueError("高并发预扣库存不足，已触发退款")

    # 【支付流程 4 - 步骤 2：持久化事务与硬件指令下发】
    # Redis 预扣成功，执行 DB 事务持久化状态
    try:
        with transaction.atomic():
            # 更新支付记录状态为成功
            payment.status = PaymentRecord.STATUS_SUCCESS
            payment.transaction_id = transaction_id
            payment.paid_at = paid_at
            payment.save(update_fields=['status', 'transaction_id', 'paid_at', 'updated_at'])

            # 绑定提前生成的 OrderToken (UUID)，将状态更新为 PENDING_DISPENSE (待出杯)
            order.order_token = order_token
            order.paid_at = paid_at
            order.status = OrderMain.STATUS_PAID
            order.save(update_fields=['order_token', 'paid_at', 'status', 'updated_at'])

            OrderStatusLog.objects.create(
                order=order,
                from_status=OrderMain.STATUS_PENDING_PAY,
                to_status=OrderMain.STATUS_PAID,
                operator='system',
                remark=f'微信支付成功，指令已下发，交易号: {transaction_id}'
            )

            # 创建生成生产任务 (ProductionTask)，作为向硬件下发的任务凭证
            task = create_production_task(order)

        # 核心日志点 2：出库指令下发前/后日志 (JSON 结构化日志)
        logger.info(json.dumps({
            "event": "command_dispatch",
            "order_no": order.order_no,
            "OrderToken": order.order_token,
            "device_sn": device.device_sn,
            "payload": task.command_payload
        }, ensure_ascii=False))

        # 4. 指令下发 (放在 DB 事务外，防止网络阻塞导致 DB 事务过长)
        from mqtt import issue_make_command
        issue_make_command(order.order_no, device.device_sn, task.command_payload)
        logger.info(f'支付成功处理完成，指令已下发: order_no={order.order_no}, =={ task.command_payload}')

    except Exception as e:
        logger.error(f'支付成功后置业务处理失败: {e}，开始进行冲正与退款')
        # 4.3 冲正：补偿 Redis 虚拟库存
        for code, val in redis_deducted:
            key = get_redis_stock_key(device.device_sn, code)
            redis_conn.incrby(key, val)
            logger.info(json.dumps({
                "event": "redis_precheck_compensate_error_rollback",
                "order_no": order.order_no,
                "OrderToken": order_token,
                "material_code": code,
                "quantity_compensate_val": val
            }, ensure_ascii=False))
        
        # 更新订单为 FAILED 并触发退款
        with transaction.atomic():
            update_order_status(
                order=order,
                new_status=OrderMain.STATUS_EXCEPTION, # failed
                operator='system',
                remark=f'后置处理异常，自动退款: {e}'
            )
            refund_order(order, reason=f"系统异常退款: {e}")
        raise e

def process_refund_callback(out_refund_no: str, refund_status: str) -> None:
    """
    处理微信退款回调
    """
    from .models import RefundRecord
    from orders.models import OrderMain, OrderStatusLog
    
    try:
        refund = RefundRecord.objects.select_related('order').get(out_refund_no=out_refund_no)
    except RefundRecord.DoesNotExist:
        logger.warning(f"退款回调记录不存在: out_refund_no={out_refund_no}")
        return
        
    if refund.status != RefundRecord.STATUS_PENDING:
        logger.info(f"退款回调已处理跳过: out_refund_no={out_refund_no}")
        return
        
    status_map = {
        'SUCCESS': RefundRecord.STATUS_SUCCESS,
        'CLOSED': RefundRecord.STATUS_FAILED,
        'ABNORMAL': RefundRecord.STATUS_FAILED,
    }
    
    new_status = status_map.get(refund_status)
    if not new_status:
        logger.warning(f"未知的退款状态: {refund_status}")
        return
        
    order = refund.order
    with transaction.atomic():
        refund.status = new_status
        if new_status == RefundRecord.STATUS_SUCCESS:
            refund.refunded_at = timezone.now()
        refund.save(update_fields=['status', 'refunded_at'])
        
        old_order_status = order.status
        if new_status == RefundRecord.STATUS_SUCCESS:
            order.status = OrderMain.STATUS_REFUNDED
        else:
            order.status = OrderMain.STATUS_EXCEPTION
            
        order.save(update_fields=['status', 'updated_at'])
        
        OrderStatusLog.objects.create(
            order=order,
            from_status=old_order_status,
            to_status=order.status,
            operator="WechatCallback",
            remark=f"微信退款回调: {refund_status}"
        )
        logger.info(f"退款回调处理成功: out_refund_no={out_refund_no}, status={new_status}")
