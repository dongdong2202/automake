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
import threading
from datetime import timedelta
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
    # 1. 状态与设备环境 Precheck
    if not order.can_pay:
        raise ValueError(f'订单状态 [{order.get_status_display()}] 不允许支付')

    from orders.services import precheck_device_environment_for_pay
    env_ok, env_msg = precheck_device_environment_for_pay(order)
    if not env_ok:
        raise ValueError(env_msg)

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

    from orders.services import precheck_device_environment_for_pay
    env_ok, env_msg = precheck_device_environment_for_pay(order)
    if not env_ok:
        raise ValueError(env_msg)

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
        # 计算 90s 超时时间 (RFC3339 格式)
        expire_dt = timezone.localtime(order.created_at or timezone.now()) + timedelta(seconds=90)
        min_expire = timezone.localtime() + timedelta(seconds=65)
        if expire_dt < min_expire:
            expire_dt = timezone.localtime() + timedelta(seconds=90)
        time_expire_str = expire_dt.isoformat()

        wx_result = pay_client.create_native_order(
            out_trade_no=out_trade_no,
            amount=order.pay_amount,
            description=description,
            time_expire=time_expire_str,
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


def _start_codepay_polling_thread(order_no: str, out_trade_no: str, max_duration: float = 90.0, interval: float = 1.5) -> threading.Thread:
    """
    付款码 USERPAYING 后台异步主动轮询线程。
    微信付款码支付 (被扫支付) 无异步 Webhook 回调机制，
    当用户正在手机端输入密码 (USERPAYING) 时，后台立即启动轻量异步子线程主动轮询查单，
    一旦用户输完密码扣款成功，第一时间 (1~2s) 确认支付、流转订单履约时间线并下发制作。
    """
    def _poll_worker():
        import time
        from django.db import close_old_connections
        from utils.wechat import WechatPayV3
        from orders.models import OrderMain

        deadline = time.time() + max_duration
        logger.info(f"[CODEPAY_POLL] 启动付款码后台主动轮询: order_no={order_no}, out_trade_no={out_trade_no}, 最长={max_duration}s")

        pay_client = WechatPayV3()
        while time.time() < deadline:
            time.sleep(interval)
            try:
                close_old_connections()
                order = OrderMain.objects.filter(order_no=order_no).first()
                if not order or order.status != OrderMain.STATUS_PENDING_PAY:
                    logger.info(f"[CODEPAY_POLL] 订单 {order_no} 状态已流转为 {getattr(order, 'status', None)}，安全退出主动轮询")
                    break

                wx_resp = pay_client.query_order(out_trade_no)
                trade_state = wx_resp.get('trade_state') if wx_resp else None
                if trade_state == 'SUCCESS':
                    tx_id = wx_resp.get('transaction_id')
                    payer_total = wx_resp.get('amount', {}).get('payer_total', order.pay_amount)
                    logger.info(
                        f"[CODEPAY_POLL] 微信确认付款码支付成功: order_no={order_no}, out_trade_no={out_trade_no}, "
                        f"tx_id={tx_id}, 实付={payer_total}分，第一时间触发支付成功与时间线流转！"
                    )
                    confirm_payment_success(
                        out_trade_no=out_trade_no,
                        transaction_id=tx_id,
                        paid_amount_fen=payer_total,
                        source='wechat_codepay_poll'
                    )
                    cancel_order_timeout_timer(order_no)
                    break
                elif trade_state in ('CLOSED', 'REVOKED', 'PAYERROR'):
                    logger.info(f"[CODEPAY_POLL] 微信返回终态 {trade_state}，退出轮询")
                    break
            except Exception as e:
                logger.warning(f"[CODEPAY_POLL] 微信轮询查单异常 out_trade_no={out_trade_no}: {e}")
            finally:
                close_old_connections()

    t = threading.Thread(target=_poll_worker, daemon=True)
    t.start()
    return t


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
        # 确保 out_trade_no 唯一且不超过 32 位（微信支付限制 32 字符以内）
        base_no = f"{order.order_no}"
        if not PaymentRecord.objects.filter(out_trade_no=base_no).exists():
            out_trade_no = base_no
        else:
            prefix = base_no[:24]
            out_trade_no = f"{prefix}_M{uuid.uuid4().hex[:5]}"
            while PaymentRecord.objects.filter(out_trade_no=out_trade_no).exists():
                out_trade_no = f"{prefix}_M{uuid.uuid4().hex[:5]}"

        payment = PaymentRecord.objects.create(
            order=order,
            user=target_user,
            out_trade_no=out_trade_no,
            amount=order.pay_amount,
            status=PaymentRecord.STATUS_PENDING,
            pay_method='wechat_codepay',
        )

    # 1. 实际支付扣款前执行设备环境 Precheck (只读核验，支付成功前不锁库存)
    from orders.services import precheck_device_environment_for_pay
    env_ok, env_msg = precheck_device_environment_for_pay(order)
    if not env_ok:
        logger.warning(f"付款码支付前环境核验失败: order_no={order.order_no}, {env_msg}")
        return {
            'status': 'failed',
            'order_no': order.order_no,
            'err_code': 'ENV_PRECHECK_FAILED',
            'message': f'支付前环境核验未通过: {env_msg}（未发起任何扣款）'
        }

    # 计算 90s 超时时间 (yyyyMMddHHmmss 格式，必须按北京时间格式化)
    expire_dt = timezone.localtime(order.created_at or timezone.now()) + timedelta(seconds=90)
    min_expire = timezone.localtime() + timedelta(seconds=65)
    if expire_dt < min_expire:
        expire_dt = timezone.localtime() + timedelta(seconds=90)
    time_expire_str = expire_dt.strftime('%Y%m%d%H%M%S')

    try:
        pay_client = WechatPayV3()
        description = order.items.first().item_name if order.items.exists() else '咖啡饮品'
        # 发起被扫扣款（带 90s 过期参数，auth_code 敏感不打印日志）
        wx_result = pay_client.create_codepay_order(
            out_trade_no=out_trade_no,
            amount=order.pay_amount,
            auth_code=auth_code_str,
            description=description,
            spbill_create_ip=spbill_create_ip or '127.0.0.1',
            time_expire=time_expire_str,
        )
    except (ValueError, FileNotFoundError) as e:
        logger.error(f'调用微信付款码支付失败: {e}')
        raise ValueError(str(e))
    except Exception as e:
        logger.error(f'调用微信付款码支付系统未知异常: {e}')
        raise e

    return_code = wx_result.get('return_code', '')
    result_code = wx_result.get('result_code', '')

    if return_code == 'SUCCESS' and result_code == 'SUCCESS':
        # 扣款明确成功 -> 确认支付，内部原子扣减库存（若库存不足自动退款）
        transaction_id = wx_result.get('transaction_id')
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
        # 用户正在手机端输入密码等，立即启动后台异步主动轮询，并在 1~2s 内第一时间完成支付履约与时间线流转
        import sys
        poll_interval = 0.05 if 'test' in sys.argv else 1.5
        _start_codepay_polling_thread(order.order_no, out_trade_no, interval=poll_interval)
        return {
            'status': 'userpaying',
            'order_no': order.order_no,
            'out_trade_no': out_trade_no,
            'message': '用户支付中，请在手机上确认支付密码'
        }

    # 微信明确返回扣款失败 (如余额不足、密码错误、用户取消)
    payment.status = PaymentRecord.STATUS_FAILED
    err_msg = wx_result.get('err_code_des') or wx_result.get('return_msg') or '付款码支付失败'
    if '签名错误' in str(err_msg):
        err_msg = f"{err_msg}（微信商户平台API密钥未配置或不符，请前往 pay.weixin.qq.com -> 账户中心 -> API安全 -> 设置API密钥）"

    payment.pay_params['error'] = err_msg
    payment.pay_params['err_code'] = err_code
    payment.save(update_fields=['status', 'pay_params', 'updated_at'])

    logger.warning(f"付款码支付失败: order_no={order.order_no}, err_code={err_code}, msg={err_msg}")
    return {
        'status': 'failed',
        'order_no': order.order_no,
        'out_trade_no': out_trade_no,
        'err_code': err_code,
        'message': err_msg
    }


_active_order_timers = {}
_timer_lock = threading.Lock()


def start_order_timeout_timer(order_no: str, timeout_seconds: float = 90.0) -> threading.Timer:
    """
    在后台启动原生异步线程定时器 (threading.Timer)。
    经过 timeout_seconds (默认 90 秒) 后在后台自动唤醒：
    若订单仍处于未支付状态，由该异步后台线程直接执行关单、微信关单并写入订单流水。
    完全不阻塞 Django 主请求线程。
    """
    def _timer_callback():
        try:
            with _timer_lock:
                _active_order_timers.pop(order_no, None)

            from django.db import close_old_connections
            close_old_connections()
            from orders.models import OrderMain
            order = OrderMain.objects.filter(order_no=order_no).first()
            if order and order.status == OrderMain.STATUS_PENDING_PAY:
                logger.info(f"[ORDER_TIMER] 订单 {order_no} 90s 超时定时器到期，后台异步线程自动执行关单...")
                close_timeout_order(order, operator='system_timer', remark=f'服务端{int(timeout_seconds)}秒倒计时到期自动关单')
        except Exception as e:
            logger.error(f"[ORDER_TIMER] 90s 超时定时器执行异常 order_no={order_no}: {e}")
        finally:
            from django.db import close_old_connections
            close_old_connections()

    t = threading.Timer(timeout_seconds, _timer_callback)
    t.daemon = True
    with _timer_lock:
        old_timer = _active_order_timers.pop(order_no, None)
        if old_timer:
            try:
                old_timer.cancel()
            except Exception:
                pass
        _active_order_timers[order_no] = t
    t.start()
    logger.info(f"[ORDER_TIMER] 已为订单 {order_no} 启动后台原生异步定时器 ({timeout_seconds}s)")
    return t


def cancel_order_timeout_timer(order_no: str):
    """
    取消指定订单的后台超时关单定时器 (例如在支付成功或主动取消时调用)
    """
    with _timer_lock:
        timer = _active_order_timers.pop(order_no, None)
        if timer:
            try:
                timer.cancel()
                logger.info(f"[ORDER_TIMER] 订单 {order_no} 超时定时器已成功取消")
            except Exception:
                pass


def close_timeout_order(order: OrderMain, operator: str = 'system', remark: str = '支付超过90秒超时未付') -> bool:
    """
    关闭超时未支付的订单及对应的支付单，并使用原生线程异步记录订单流水。
    设计原则：支付前不锁定/扣减物料库存，故超时关单无需释放库存。
    """
    if order.status != OrderMain.STATUS_PENDING_PAY:
        return False

    from orders.services import record_order_timeline
    from utils.wechat import WechatPayV3

    # 1. 查找待支付记录
    pending_payments = PaymentRecord.objects.filter(
        order=order,
        status=PaymentRecord.STATUS_PENDING
    )

    pay_client = None
    # 关键防线：超时关单前逐一向微信网关核验真实的扣款状态（防止用户在手机端刚完成支付却被误取消）
    for payment in pending_payments.order_by('-created_at'):
        try:
            if pay_client is None:
                pay_client = WechatPayV3()
            wx_resp = pay_client.query_order(payment.out_trade_no)
            if wx_resp and wx_resp.get('trade_state') == 'SUCCESS':
                transaction_id = wx_resp.get('transaction_id')
                paid_amount = wx_resp.get('amount', {}).get('payer_total', payment.amount)
                logger.info(
                    f"[TIMEOUT_CLOSE_INTERCEPT] 订单 {order.order_no} (out_trade_no={payment.out_trade_no}) "
                    f"在关单前核验到微信已支付成功 (tx={transaction_id})，立即阻断关单并转入支付成功确认流程！"
                )
                confirm_payment_success(
                    out_trade_no=payment.out_trade_no,
                    transaction_id=transaction_id,
                    paid_amount_fen=paid_amount,
                    source='timeout_query_intercept'
                )
                cancel_order_timeout_timer(order.order_no)
                return False
        except Exception as e:
            logger.warning(f"[TIMEOUT_CLOSE] 核验微信支付状态异常 out_trade_no={payment.out_trade_no}: {e}")

    # 2. 经微信核验证实确实未付款，安全关闭本地支付单并将非付款码的微信端订单关闭
    for payment in pending_payments:
        payment.status = PaymentRecord.STATUS_CLOSED
        if isinstance(payment.pay_params, dict):
            payment.pay_params['close_reason'] = remark
        else:
            payment.pay_params = {'close_reason': remark}
        payment.save(update_fields=['status', 'pay_params', 'updated_at'])

        # 尝试向微信支付网关发起关单（付款码支付在微信端无法普通关单，且已有 time_expire 保护）
        if payment.pay_method != 'wechat_codepay':
            try:
                if pay_client is None:
                    pay_client = WechatPayV3()
                pay_client.close_order(payment.out_trade_no)
                logger.info(f"[TIMEOUT_CLOSE] 成功调用微信网关关单: out_trade_no={payment.out_trade_no}")
            except Exception as e:
                logger.warning(f"[TIMEOUT_CLOSE] 调用微信网关关单异常（可忽略）: out_trade_no={payment.out_trade_no}, err={e}")

    # 3. 更新订单状态为 CANCELLED
    old_status = order.status
    order.status = OrderMain.STATUS_CANCELLED
    order.save(update_fields=['status', 'updated_at'])

    # 3. 原生子线程异步记录订单流转时间线 (OrderStatusLog)
    order_id = order.id
    def _async_log():
        try:
            from django.db import close_old_connections
            close_old_connections()
            thread_order = OrderMain.objects.filter(id=order_id).first()
            if not thread_order:
                logger.warning(f"[TIMEOUT_CLOSE] 异步流水未找到订单: id={order_id}")
                return
            record_order_timeline(
                order=thread_order,
                action=OrderStatusLog.ACTION_CANCELLED,
                action_name='订单超时取消',
                from_status=old_status,
                to_status=OrderMain.STATUS_CANCELLED,
                operator_type=OrderStatusLog.OP_SYSTEM,
                operator=operator,
                remark=remark,
                payload={'timeout_seconds': 90, 'trigger': 'auto_timeout_90s'}
            )
            logger.info(f"[TIMEOUT_CLOSE] 订单 {thread_order.order_no} 异步流水成功落库")
        except Exception as err:
            logger.error(f"[TIMEOUT_CLOSE] 异步写入订单流水日志异常: {err}")
        finally:
            from django.db import close_old_connections
            close_old_connections()

    # 若当前已经在后台异步子线程（如 timer 回调）中，则直接执行落库；若在主线程，则拉起异步子线程落库
    if threading.current_thread() is threading.main_thread():
        t = threading.Thread(target=_async_log, daemon=True)
        t.start()
    else:
        _async_log()

    cancel_order_timeout_timer(order.order_no)
    logger.info(f"[TIMEOUT_CLOSE] 订单 {order.order_no} 90秒超时关单成功，已触发异步流水记录。")
    return True


def query_and_sync_payment_status(order_no: str, sync_wechat: bool = False) -> dict:
    """
    查询订单支付与制作状态（纯只读查询）。
    超时未支付关单由后台原生异步定时器 (threading.Timer) 统一主动执行。

    :param order_no: 业务订单号
    :param sync_wechat: 是否向微信主动查单并触发确认（默认 False）
    :return: 订单支付与制作状态
    """
    order = OrderMain.objects.filter(order_no=order_no).first()
    if not order:
        raise ValueError('订单不存在')

    # 1. 若本地订单已支付/制作中/完成，直接返回
    if order.status in (OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING, OrderMain.STATUS_DONE):
        pickup_code_val = ''
        try:
            if hasattr(order, 'pickup_code') and order.pickup_code:
                pickup_code_val = order.pickup_code.code
            else:
                from notifications.models import PickupCode
                p = PickupCode.objects.filter(order=order).first()
                if p:
                    pickup_code_val = p.code
        except Exception:
            pass
        return {
            'paid': True,
            'order_no': order.order_no,
            'order_status': order.status,
            'order_status_display': order.get_status_display(),
            'order_token': getattr(order, 'order_token', '') or '',
            'pickup_code': pickup_code_val,
            'trade_state': 'SUCCESS',
            'message': '订单已支付'
        }

    # 2. 若订单已处于取消或关闭状态（由后台定时器或用户主动取消触发）
    if order.status == OrderMain.STATUS_CANCELLED:
        return {
            'paid': False,
            'timeout': True,
            'order_no': order.order_no,
            'order_status': order.status,
            'order_status_display': order.get_status_display(),
            'trade_state': 'CLOSED',
            'message': '订单已取消或超时关闭'
        }

    # 3. 待支付状态检查与查单候选集
    candidate_payments = list(PaymentRecord.objects.filter(order=order, status=PaymentRecord.STATUS_PENDING).order_by('-created_at'))
    if not candidate_payments:
        candidate_payments = list(PaymentRecord.objects.filter(order=order).exclude(status=PaymentRecord.STATUS_FAILED).order_by('-created_at')[:1])
    if not candidate_payments:
        return {
            'paid': False,
            'order_no': order.order_no,
            'order_status': order.status,
            'order_status_display': order.get_status_display(),
            'trade_state': 'NOTPAY',
            'message': '尚未发起有效支付'
        }

    # 对于普通扫码支付(Native/JSAPI)，微信会通过 Webhook 异步回调通知，默认只读本地状态；
    # 但若显式请求 sync_wechat=True，或当前订单存在待确认的付款码支付(wechat_codepay，微信官方无 Webhook 回调)，则必须主动向微信查单同步！
    has_pending_codepay = any(p.pay_method == 'wechat_codepay' and p.status == PaymentRecord.STATUS_PENDING for p in candidate_payments)
    if not sync_wechat and not has_pending_codepay:
        return {
            'paid': False,
            'timeout': False,
            'order_no': order.order_no,
            'order_status': order.status,
            'order_status_display': order.get_status_display(),
            'trade_state': 'NOTPAY',
            'message': '等待支付中'
        }

    pay_client = WechatPayV3()
    wx_resp = None
    target_payment = candidate_payments[0]
    for p in candidate_payments:
        try:
            resp = pay_client.query_order(p.out_trade_no)
            if resp and resp.get('trade_state') == 'SUCCESS':
                target_payment = p
                wx_resp = resp
                break
            wx_resp = resp
            target_payment = p
        except Exception as e:
            logger.warning(f"微信查单异常 order_no={order_no}, out_trade_no={p.out_trade_no}: {e}")

    if not wx_resp:
        return {
            'paid': False,
            'order_no': order.order_no,
            'order_status': order.status,
            'order_status_display': order.get_status_display(),
            'message': '查单暂未成功'
        }

    trade_state = wx_resp.get('trade_state')
    if trade_state == 'SUCCESS':
        transaction_id = wx_resp.get('transaction_id')
        paid_amount = wx_resp.get('amount', {}).get('payer_total', target_payment.amount)
        confirm_payment_success(
            out_trade_no=target_payment.out_trade_no,
            transaction_id=transaction_id,
            paid_amount_fen=paid_amount,
            source='wechat_query'
        )
        order.refresh_from_db()
        pickup_code_val = ''
        try:
            if hasattr(order, 'pickup_code') and order.pickup_code:
                pickup_code_val = order.pickup_code.code
            else:
                from notifications.models import PickupCode
                p = PickupCode.objects.filter(order=order).first()
                if p:
                    pickup_code_val = p.code
        except Exception:
            pass
        return {
            'paid': True,
            'order_no': order.order_no,
            'order_status': order.status,
            'order_status_display': order.get_status_display(),
            'order_token': getattr(order, 'order_token', '') or '',
            'pickup_code': pickup_code_val,
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


def refund_order(order: OrderMain, reason: str = "库存不足，系统自动退款", funds_account: str = None, skip_device_cancel: bool = False):
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

    # 仅当订单处于制作中 (STATUS_MAKING) 阶段，才需要向下位机发送 cancel 指令并阻塞等待 5s ACK
    import sys
    is_running_tests = 'test' in sys.argv
    if not skip_device_cancel and not is_running_tests and order.device and order.status == OrderMain.STATUS_MAKING:
        from mqtt import issue_cancel_command_with_ack
        is_ok, cancel_msg = issue_cancel_command_with_ack(
            device_sn=order.device.device_sn,
            order_no=order.order_no,
            reason=reason,
            timeout=5.0
        )
        if not is_ok:
            logger.warning(f"上位机拒绝退款停机或超时: order_no={order.order_no}, reason={cancel_msg}")
            raise ValueError(f"设备拒绝退款或响应超时: {cancel_msg}")

    import uuid
    out_refund_no = f"RF-{uuid.uuid4().hex[:16]}"
    
    try:
        pay_client = WechatPayV3()
        transaction_id = payment.transaction_id
        if not transaction_id:
            raise ValueError("支付记录中没有有效的微信交易号，无法退款")

        pay_client = WechatPayV3()
        wx_result = pay_client.apply_refund(
            out_refund_no=out_refund_no,
            transaction_id=transaction_id,
            refund_amount=payment.amount,
            total_amount=payment.amount,
            reason=reason,
            funds_account=funds_account
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
        from payments.models import get_pay_method_display
        pay_method_str = getattr(payment, 'pay_method', 'wechat_jsapi') if payment else ''
        pay_method_text = get_pay_method_display(pay_method_str) if payment else '微信支付'

        if record_status == RefundRecord.STATUS_SUCCESS:
            order.status = OrderMain.STATUS_REFUNDED
            action = OrderStatusLog.ACTION_REFUND_SUCCESS
            action_name = '退款成功'
            remark = f"{pay_method_text}原路退款成功，退款单号: {out_refund_no}, 微信退款号: {refund_id}, 金额: {payment.amount / 100:.2f}元"
        elif record_status == RefundRecord.STATUS_PENDING:
            order.status = OrderMain.STATUS_REFUNDING
            action = OrderStatusLog.ACTION_REFUND_APPLIED
            action_name = '退款受理中'
            remark = f"发起{pay_method_text}原路退款申请，微信受理中，退款单号: {out_refund_no}"
        else:
            order.status = OrderMain.STATUS_EXCEPTION
            action = OrderStatusLog.ACTION_REFUND_FAILED
            action_name = '退款失败'
            remark = f"{pay_method_text}退款受理失败，退款单号: {out_refund_no}, 状态: {record_status}"
            
        order.save(update_fields=['status', 'updated_at'])
        
        from orders.services import record_order_timeline
        record_order_timeline(
            order=order,
            action=action,
            action_name=action_name,
            from_status=old_status,
            to_status=order.status,
            operator_type=OrderStatusLog.OP_SYSTEM,
            operator="System",
            remark=remark,
            payload={
                'out_refund_no': out_refund_no,
                'refund_id': refund_id,
                'refund_amount': payment.amount,
                'pay_method': pay_method_str,
                'pay_method_display': pay_method_text,
                'reason': reason,
                'record_status': record_status,
            }
        )
        logger.info(f"已处理退款流转: order_no={order.order_no}, out_refund_no={out_refund_no}, refund_id={refund_id}, status={record_status}")
    except Exception as e:
        logger.exception(f"调用微信退款接口失败: order_no={order.order_no}, error={e}")
        # 创建一个失败的退款记录并保存失败具体原因
        fail_reason = f"{reason} (失败: {e})"[:256]
        RefundRecord.objects.create(
            order=order,
            payment=payment,
            out_refund_no=out_refund_no,
            refund_amount=payment.amount,
            reason=fail_reason,
            status=RefundRecord.STATUS_FAILED
        )
        # 核心：将退款失败显式记录到履约流转时间线中，保证 100% 可追溯
        try:
            from orders.services import record_order_timeline
            from orders.models import OrderStatusLog
            record_order_timeline(
                order=order,
                action=OrderStatusLog.ACTION_REFUND_FAILED,
                action_name='退款失败',
                from_status=order.status,
                to_status=order.status,
                operator_type=OrderStatusLog.OP_SYSTEM,
                operator="System",
                remark=f"退款申请失败: {str(e)}",
                payload={
                    'out_refund_no': out_refund_no,
                    'refund_amount': payment.amount,
                    'reason': reason,
                    'error': str(e),
                    'error_type': e.__class__.__name__
                }
            )
        except Exception as log_err:
            logger.error(f"记录退款失败时间线异常: {log_err}")
        raise e



def batch_refund_device_orders(
    device_sn: str,
    refund_stock: list = None,
    refund_no_stock: list = None,
    reason: str = "设备退款",
    **kwargs
) -> dict:
    """
    设备订单批量退款业务函数

    :param device_sn: 设备序列号
    :param refund_stock: 退款退库存单号列表
    :param refund_no_stock: 退款不退库存单号列表
    :param reason: 退款原因
    :return: {'success': bool, 'success_orders': list[str]}
    """
    from devices.models import Device
    from orders.models import OrderMain
    from orders.services import restore_order_inventory
    from django.db.models import Q
    from django.db import transaction
    from orders.models import ProductionTask

    device = Device.objects.filter(device_sn=device_sn).first()
    if not device:
        raise ValueError(f"设备 {device_sn} 不存在")

    # 规范化参数列表
    def _clean_nos(raw_list):
        if not raw_list:
            return []
        if isinstance(raw_list, str):
            raw_list = [item.strip() for item in raw_list.split(',') if item.strip()]
        cleaned = [str(item).strip() for item in raw_list if item and str(item).strip()]
        return list(dict.fromkeys(cleaned))

    stock_nos = _clean_nos(refund_stock or kwargs.get('refund_restore_stock_order_nos') or kwargs.get('with_stock'))
    no_stock_nos = _clean_nos(refund_no_stock or kwargs.get('refund_no_restore_stock_order_nos') or kwargs.get('without_stock'))

    if not stock_nos and not no_stock_nos:
        raise ValueError("退款单号列表不能为空")

    failed_orders = []
    success_orders = []
    all_restored_materials = []

    # 1. 处理【退款退库存】
    for order_no in stock_nos:
        order = OrderMain.objects.filter(
            Q(order_no=order_no) | Q(order_token=order_no),
            device=device
        ).first()

        if not order:
            failed_orders.append(order_no)
            logger.warning(f"退款退库存失败：订单 {order_no} 不存在或不属于设备 {device_sn}")
            continue

        try:
            with transaction.atomic():
                refund_order(order, reason=reason, skip_device_cancel=True)
                res_restore = restore_order_inventory(
                    order=order,
                    operator=f'device:{device_sn}',
                    reason=f'退款退库存: {reason}'
                )
                if res_restore and res_restore.get('restored_materials'):
                    all_restored_materials.extend(res_restore['restored_materials'])
            success_orders.append(order.order_no)
        except Exception as e:
            logger.exception(f"订单 {order_no} 退款退库存异常: {e}")
            failed_orders.append(order_no)

    # 2. 处理【退款不退库存】
    for order_no in no_stock_nos:
        order = OrderMain.objects.filter(
            Q(order_no=order_no) | Q(order_token=order_no),
            device=device
        ).first()

        if not order:
            failed_orders.append(order_no)
            logger.warning(f"退款不退库存失败：订单 {order_no} 不存在或不属于设备 {device_sn}")
            continue

        try:
            with transaction.atomic():
                ProductionTask.objects.filter(order=order).update(
                    status=ProductionTask.TASK_FAILED,
                    failure_reason='设备退款不退库存'
                )
                refund_order(order, reason=reason, skip_device_cancel=True)
            success_orders.append(order.order_no)
        except Exception as e:
            logger.exception(f"订单 {order_no} 退款不退库存异常: {e}")
            failed_orders.append(order_no)

    is_success = (len(failed_orders) == 0) and (len(success_orders) > 0)
    return {
        'success': is_success,
        'success_orders': success_orders,
        'restored_materials': all_restored_materials
    }



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

    import time
    # 防并发互斥锁：针对单笔订单加 Redis 分布式排他锁，防止微信重试通知或并发请求穿透
    redis_conn = get_redis_connection('default')
    lock_key = f"automake:pay_proc_lock:{order_no}"
    acquired = redis_conn.set(lock_key, "1", nx=True, ex=30)
    if not acquired:
        # 并发通道正在处理，等待其处理完成
        for _ in range(15):
            time.sleep(0.2)
            payment.refresh_from_db()
            if payment.status == PaymentRecord.STATUS_SUCCESS:
                logger.info(f'并发等待完成，支付已由另一通道处理成功: out_trade_no={order_no}')
                return
    # 获锁后二次检查 DB 状态
    payment.refresh_from_db()
    if payment.status == PaymentRecord.STATUS_SUCCESS:
        logger.info(f'获取锁后二次检查：支付回调已处理，跳过: out_trade_no={order_no}')
        try:
            redis_conn.delete(lock_key)
        except Exception:
            pass
        return

    order = payment.order

    # 金额校验
    if wx_amount != payment.amount:
        logger.error(f'支付金额不匹配！订单={payment.amount}，实付={wx_amount}')
        try:
            redis_conn.delete(lock_key)
        except Exception:
            pass
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
        try:
            redis_conn.delete(lock_key)
        except Exception:
            pass
        raise ValueError("系统繁忙，已自动退款")

    # 1. 调用 calculate_required_materials 计算订单所需的所有物料总量，并过滤出该订单所需的耗材总量
    items_data = []
    order_items = getattr(order, '_prefetched_objects_cache', {}).get('items')
    if order_items is None:
        order_items = order.items.select_related('item').prefetch_related('skus').all()

    for item in order_items:
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
        cup_mats = cup.get('sub_total_materials', {}) if isinstance(cup, dict) else cup
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

    is_prelocked = bool(payment and payment.pay_params and payment.pay_params.get('stock_prelocked'))
    redis_deducted = []

    if not is_prelocked:
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

        # 标记该订单耗材已完成数据库扣减
        order.stock_deducted = True
        order.save(update_fields=['stock_deducted', 'updated_at'])
        redis_conn.set(f"automake:order_stock_deducted:{order.order_no}", "1", ex=86400)

        # 2. 同步更新 Redis 缓存与原子记录
        for cup_code, qty in required_cups.items():
            key = get_redis_stock_key(device.device_sn, cup_code)
            val_to_deduct = int(qty)
            try:
                redis_conn.decrby(key, val_to_deduct)
                redis_deducted.append((cup_code, val_to_deduct))
            except Exception:
                pass
    else:
        logger.info(f"[STOCK] 订单 {order.order_no} 耗材已在实际支付前完成原子排他预锁，跳过重复扣减")

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

            cancel_order_timeout_timer(order.order_no)

            from orders.services import record_order_timeline
            already_paid_logged = OrderStatusLog.objects.filter(
                order=order,
                action=OrderStatusLog.ACTION_PAY_SUCCESS
            ).exists()
            if not already_paid_logged:
                from payments.models import get_pay_method_display
                pay_method_str = getattr(payment, 'pay_method', 'wechat_jsapi')
                pay_method_text = get_pay_method_display(pay_method_str)
                record_order_timeline(
                    order=order,
                    action=OrderStatusLog.ACTION_PAY_SUCCESS,
                    action_name=f'{pay_method_text}成功',
                    from_status=OrderMain.STATUS_PENDING_PAY,
                    to_status=OrderMain.STATUS_PAID,
                    operator_type=OrderStatusLog.OP_WECHAT,
                    operator='wechat_pay',
                    remark=f'{pay_method_text}成功，实付: {payment.amount / 100:.2f}元，交易号: {transaction_id}',
                    payload={
                        'transaction_id': transaction_id,
                        'pay_method': pay_method_str,
                        'pay_method_display': pay_method_text,
                        'order_token': str(order_token) if order_token else '',
                        'pay_amount': payment.amount,
                        'paid_at': paid_at.isoformat() if paid_at else timezone.now().isoformat(),
                        'device_sn': order.device.device_sn if order.device else ''
                    }
                )

            # 先生成取餐码（当日支付订单号+1规则），便于生产任务注入取餐号 ticketNo
            try:
                from notifications.services import create_pickup_code
                create_pickup_code(order)
            except Exception as e:
                logger.warning(f"生成取餐码异常（不影响出餐）: {e}")

            # 创建生成生产任务 (ProductionTask)，作为向硬件下发的任务凭证
            task = create_production_task(order)

        # 4. 指令下发 (仅首次创建的任务才向硬件下发制作指令，杜绝重复出杯)
        if getattr(task, '_is_created', True):
            # 核心日志点 2：出库指令下发前/后日志 (JSON 结构化日志)
            logger.info(json.dumps({
                "event": "command_dispatch",
                "order_no": order.order_no,
                "OrderToken": order.order_token,
                "device_sn": device.device_sn,
                "payload": task.command_payload
            }, ensure_ascii=False))

            from mqtt import issue_make_command
            issue_make_command(order.order_no, device.device_sn, task.command_payload)
            logger.info(f'支付成功处理完成，指令已下发: order_no={order.order_no}, =={task.command_payload}')
        else:
            logger.info(f'订单 {order.order_no} 生产任务已存在，跳过重复下发 MQTT 指令')

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
    finally:
        # 释放 Redis 互斥排他锁
        try:
            redis_conn.delete(lock_key)
        except Exception:
            pass

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
        
        from orders.services import record_order_timeline
        if new_status == RefundRecord.STATUS_SUCCESS:
            cb_action = OrderStatusLog.ACTION_REFUND_SUCCESS
            cb_name = '微信退款成功'
            cb_remark = f"微信退款回调确认：退款成功（单号: {out_refund_no}）"
        else:
            cb_action = OrderStatusLog.ACTION_REFUND_FAILED
            cb_name = '微信退款失败'
            cb_remark = f"微信退款回调失败: {refund_status}（单号: {out_refund_no}）"

        record_order_timeline(
            order=order,
            action=cb_action,
            action_name=cb_name,
            from_status=old_order_status,
            to_status=order.status,
            operator_type=OrderStatusLog.OP_WECHAT,
            operator="WechatCallback",
            remark=cb_remark,
            payload={
                'out_refund_no': out_refund_no,
                'refund_id': refund.refund_id,
                'refund_status': refund_status,
                'refund_amount': refund.refund_amount
            }
        )
        logger.info(f"退款回调处理成功: out_refund_no={out_refund_no}, status={new_status}, action={cb_action}")
