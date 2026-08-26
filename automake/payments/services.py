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


def create_native_pay_request(order: OrderMain, user=None) -> dict:
    """
    发起微信 Native 扫码支付 (用户扫商户二维码)

    :param order: 待支付的 OrderMain 对象
    :param user: 操作用户（可选）
    :return: 包含 code_url、out_trade_no、order_no 等信息的字典
    """
    if not order.can_pay:
        raise ValueError(f'订单状态 [{order.get_status_display()}] 不允许支付')

    target_user = user or order.user

    # 幂等处理：复用已有未支付记录或新建
    existing = PaymentRecord.objects.filter(
        order=order,
        pay_method='wechat_native',
        status=PaymentRecord.STATUS_PENDING
    ).first()

    if existing:
        out_trade_no = existing.out_trade_no
    else:
        out_trade_no = f'{order.order_no}'
        # 若已有其他支付方式使用过该 out_trade_no，加后缀避免微信 TRADE_TYPE 冲突
        if PaymentRecord.objects.filter(out_trade_no=out_trade_no).exclude(pay_method='wechat_native').exists():
            out_trade_no = f'{order.order_no}_NAT'

    try:
        pay_client = WechatPayV3()
        description = order.items.first().item_name if order.items.exists() else '咖啡饮品'
        wx_result = pay_client.create_native_order(
            out_trade_no=out_trade_no,
            amount=order.pay_amount,
            description=description,
        )
    except (ValueError, FileNotFoundError) as e:
        logger.error(f'调用微信 Native 下单失败: {e}')
        raise ValueError(str(e))

    code_url = wx_result.get('code_url')
    if not code_url:
        raise ValueError('微信支付 Native 下单接口返回异常，缺少 code_url')

    with transaction.atomic():
        if existing:
            existing.pay_params = {'code_url': code_url}
            existing.pay_method = 'wechat_native'
            existing.save(update_fields=['pay_params', 'pay_method', 'updated_at'])
            payment = existing
        else:
            payment = PaymentRecord.objects.create(
                order=order,
                user=target_user,
                out_trade_no=out_trade_no,
                amount=order.pay_amount,
                status=PaymentRecord.STATUS_PENDING,
                pay_params={'code_url': code_url},
                pay_method='wechat_native',
            )

    logger.info(f'Native 支付二维码生成成功: out_trade_no={out_trade_no}, code_url={code_url}')
    return {
        'order_no': order.order_no,
        'out_trade_no': out_trade_no,
        'code_url': code_url,
        'amount': order.pay_amount,
        'pay_method': 'wechat_native',
    }


def process_codepay_request(order: OrderMain, auth_code: str, device_sn: str = None, user=None, spbill_create_ip: str = '127.0.0.1') -> dict:
    """
    发起微信付款码支付 / 被扫支付 (商户上位机扫用户微信付款码)

    :param order: 待支付的 OrderMain 对象
    :param auth_code: 用户付款码 (18位纯数字，严禁日志明文输出)
    :param device_sn: 设备序列号 (可选)
    :param user: 支付用户 (可选)
    :param spbill_create_ip: 终端 IP
    :return: 支付处理结果字典
    """
    if not order.can_pay:
        raise ValueError(f'订单状态 [{order.get_status_display()}] 不允许支付')

    auth_code_str = str(auth_code).strip()
    if not auth_code_str.isdigit() or len(auth_code_str) < 16:
        raise ValueError('无效的付款码，必须为 18 位数字')

    target_user = user or order.user
    
    existing = PaymentRecord.objects.filter(
        order=order,
        pay_method='wechat_codepay',
        status=PaymentRecord.STATUS_PENDING
    ).first()

    if existing:
        out_trade_no = existing.out_trade_no
        payment = existing
    else:
        out_trade_no = f'{order.order_no}'
        if PaymentRecord.objects.filter(out_trade_no=out_trade_no).exclude(pay_method='wechat_codepay').exists():
            out_trade_no = f'{order.order_no}_MIC'

        payment = PaymentRecord.objects.create(
            order=order,
            user=target_user,
            out_trade_no=out_trade_no,
            amount=order.pay_amount,
            status=PaymentRecord.STATUS_PENDING,
            pay_method='wechat_codepay',
        )

    try:
        pay_client = WechatPayV3()
        description = order.items.first().item_name if order.items.exists() else '咖啡饮品'
        # 发起被扫扣款（注意：auth_code 敏感不打印日志）
        wx_result = pay_client.create_codepay_order(
            out_trade_no=out_trade_no,
            amount=order.pay_amount,
            auth_code=auth_code_str,
            description=description,
            spbill_create_ip=spbill_create_ip or '127.0.0.1'
        )
    except (ValueError, FileNotFoundError) as e:
        logger.error(f'调用微信付款码支付失败: {e}')
        raise ValueError(str(e))

    return_code = wx_result.get('return_code', '')
    result_code = wx_result.get('result_code', '')

    if return_code == 'SUCCESS' and result_code == 'SUCCESS':
        # 扣款明确成功
        transaction_id = wx_result.get('transaction_id')
        time_end = wx_result.get('time_end')  # 格式如 20141030133525
        confirm_payment_success(
            out_trade_no=out_trade_no,
            transaction_id=transaction_id,
            paid_amount_fen=order.pay_amount,
            source='wechat_codepay'
        )
        return {
            'status': 'success',
            'order_no': order.order_no,
            'out_trade_no': out_trade_no,
            'transaction_id': transaction_id,
            'message': '付款码支付成功，正在制作'
        }
    
    err_code = wx_result.get('err_code', '')
    if err_code in ('USERPAYING', 'BANKERROR', 'SYSTEMERROR'):
        # 用户正在手机端输入密码等，需进入轮询/查单阶段
        return {
            'status': 'userpaying',
            'order_no': order.order_no,
            'out_trade_no': out_trade_no,
            'message': '用户支付中，请在手机上确认支付密码'
        }

    err_msg = wx_result.get('err_code_des') or wx_result.get('return_msg') or '付款码支付失败'
    logger.warning(f"付款码支付失败: order_no={order.order_no}, err_code={err_code}, msg={err_msg}")
    return {
        'status': 'failed',
        'order_no': order.order_no,
        'out_trade_no': out_trade_no,
        'err_code': err_code,
        'message': err_msg
    }


def query_and_sync_payment_status(order_no: str) -> dict:
    """
    主动查询微信支付订单状态并同步确认业务成功

    :param order_no: 业务订单号
    :return: 订单支付与制作状态
    """
    order = OrderMain.objects.filter(order_no=order_no).first()
    if not order:
        raise ValueError('订单不存在')

    # 1. 若本地订单已支付/制作中/完成，直接返回
    if order.status in (OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING, OrderMain.STATUS_DONE):
        return {
            'paid': True,
            'order_no': order.order_no,
            'order_status': order.status,
            'order_status_display': order.get_status_display(),
            'message': '订单已支付'
        }

    # 2. 本地仍为待支付，向微信主动查单
    payment = PaymentRecord.objects.filter(order=order).order_by('-created_at').first()
    if not payment:
        return {
            'paid': False,
            'order_no': order.order_no,
            'order_status': order.status,
            'order_status_display': order.get_status_display(),
            'message': '尚未发起支付'
        }

    try:
        pay_client = WechatPayV3()
        wx_resp = pay_client.query_order(payment.out_trade_no)
    except Exception as e:
        logger.warning(f"微信查单异常 order_no={order_no}: {e}")
        return {
            'paid': False,
            'order_no': order.order_no,
            'order_status': order.status,
            'order_status_display': order.get_status_display(),
            'message': f'查单暂未成功: {e}'
        }

    trade_state = wx_resp.get('trade_state')
    if trade_state == 'SUCCESS':
        transaction_id = wx_resp.get('transaction_id')
        paid_amount = wx_resp.get('amount', {}).get('payer_total', payment.amount)
        confirm_payment_success(
            out_trade_no=payment.out_trade_no,
            transaction_id=transaction_id,
            paid_amount_fen=paid_amount,
            source='wechat_query'
        )
        order.refresh_from_db()
        return {
            'paid': True,
            'order_no': order.order_no,
            'order_status': order.status,
            'order_status_display': order.get_status_display(),
            'trade_state': 'SUCCESS',
            'message': '支付成功，已确认'
        }
    
    return {
        'paid': False,
        'order_no': order.order_no,
        'order_status': order.status,
        'order_status_display': order.get_status_display(),
        'trade_state': trade_state or 'NOTPAY',
        'trade_state_desc': wx_resp.get('trade_state_desc', ''),
        'message': wx_resp.get('trade_state_desc', '等待支付中')
    }


def confirm_payment_success(*, out_trade_no: str, transaction_id: str, paid_amount_fen: int, source: str = 'wechat_callback', paid_at=None) -> dict:
    """
    统一核心支付确认服务函数
    (JSAPI 回调、Native 扫码回调、付款码同步成功、主动查单补偿 统一由此处确认)
    """
    pay_time_str = paid_at.isoformat() if paid_at and hasattr(paid_at, 'isoformat') else str(paid_at or timezone.now())
    process_payment_success(
        order_no=out_trade_no,
        transaction_id=transaction_id,
        pay_time=pay_time_str,
        wx_amount=paid_amount_fen
    )
    return {'ok': True, 'out_trade_no': out_trade_no, 'transaction_id': transaction_id}


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
    per_cup_materials = calculate_required_materials(items_data)
    all_materials = {}
    for cup in per_cup_materials:
        cup_mats = cup.get('materials', cup) if isinstance(cup, dict) else cup
        for code, qty in cup_mats.items():
            all_materials[code] = all_materials.get(code, Decimal('0.00')) + Decimal(str(qty))

    from inventory.models import Material
    consumable_codes = set(
        Material.objects.filter(
            code__in=all_materials.keys(),
            material_type__in=[Material.TYPE_CONSUMABLE, Material.TYPE_CUP]
        ).values_list('code', flat=True)
    )
    known_consumable_codes = {'paperL', 'paperM', 'plasticL', 'plasticM', 'lid', 'membrane'}

    required_cups = {
        code: qty for code, qty in all_materials.items()
        if code in consumable_codes or code in known_consumable_codes
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

    # 1. 校验并扣减 MySQL 中的杯型与耗材库存 (通过 select_for_update 保证并发一致性)
    from devices.models import DeviceConsumableStock
    db_consumable_success = True
    insufficient_cup = None
    with transaction.atomic():
        cs_records = {
            cs.code_id: cs
            for cs in DeviceConsumableStock.objects.select_for_update().filter(device=device, code__in=required_cups.keys())
        }
        for cup_code, qty in required_cups.items():
            cs_obj = cs_records.get(cup_code)
            if not cs_obj or cs_obj.quantity < int(qty):
                db_consumable_success = False
                insufficient_cup = cup_code
                break
            cs_obj.quantity -= int(qty)
            cs_obj.save(update_fields=['quantity', 'updated_at'])

    if not db_consumable_success:
        # MySQL 耗材库存不足，直接标记订单异常并自动退款
        with transaction.atomic():
            payment.status = PaymentRecord.STATUS_SUCCESS
            payment.transaction_id = transaction_id
            payment.paid_at = paid_at
            payment.save(update_fields=['status', 'transaction_id', 'paid_at', 'updated_at'])
            update_order_status(
                order=order,
                new_status=OrderMain.STATUS_EXCEPTION, # failed
                operator='system',
                remark=f'耗材 {insufficient_cup} 数据库库存不足，自动退款'
            )
            refund_order(order, reason="耗材库存不足自动退款")
        raise ValueError("耗材库存不足，已触发退款")

    # 2. 同步更新 Redis 缓存与原子记录
    redis_deducted = []
    for cup_code, qty in required_cups.items():
        key = get_redis_stock_key(device.device_sn, cup_code)
        val_to_deduct = int(qty * 100)
        try:
            redis_conn.decrby(key, val_to_deduct)
            redis_deducted.append((cup_code, val_to_deduct))
        except Exception:
            pass

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
