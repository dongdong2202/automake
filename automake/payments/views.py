"""
支付模块视图

接口列表：
- POST /api/pay/create       发起支付（返回小程序调起支付参数）
- POST /api/pay/callback     微信支付异步回调（公开，微信服务器调用）
"""

import json
import logging
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from utils.response import ok, error
from utils.wechat import WechatPayV3
from orders.models import OrderMain
from .models import PaymentCallbackLog
from .services import create_pay_request, process_payment_success

logger = logging.getLogger(__name__)


class PayCreateView(APIView):
    """
    发起支付接口

    POST /api/pay/create
    请求体：{ "order_no": "202506090001234" }
    响应：微信小程序 wx.requestPayment() 所需参数

    前置条件：订单已创建且状态为"待支付"
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        order_no = request.data.get('order_no', '').strip()
        if not order_no:
            return error('order_no 不能为空', code=5001)

        # 查找订单，并验证是当前用户的订单（防止越权）
        try:
            order = OrderMain.objects.prefetch_related('items').get(
                order_no=order_no,
                user=request.user,
            )
        except OrderMain.DoesNotExist:
            return error('订单不存在', code=5002, status=404)

        try:
            pay_params = create_pay_request(order, request.user)
        except ValueError as e:
            return error(str(e), code=5003)
        except Exception as e:
            logger.exception(f'发起支付异常: {e}')
            return error('支付系统异常，请稍后重试', code=5004, status=500)

        return ok(pay_params, message='支付参数获取成功')


class PayCallbackView(APIView):
    """
    微信支付异步回调接口

    POST /api/pay/callback
    由微信服务器异步调用（非用户请求），无需认证。

    处理流程：
    1. 先将原始回调报文落库（payment_callback_log）
    2. 验签（防篡改）
    3. 解密 resource 字段获取订单信息
    4. 调用业务处理函数
    5. 返回成功应答给微信（必须在 5 秒内响应）

    注意：微信会多次回调（如业务处理失败），需保证幂等。
    """
    permission_classes = [AllowAny]  # 微信服务器调用，无用户 token

    def post(self, request):
        # 获取原始请求体（用于验签和落库）
        raw_body = request.body.decode('utf-8')
        request_headers = request.headers

        # 先将回调报文落库（无论后续处理是否成功）
        try:
            body_json = json.loads(raw_body)
        except json.JSONDecodeError:
            logger.error('微信回调报文不是合法 JSON')
            return self._fail_response('报文格式错误')

        out_trade_no = ''
        transaction_id = ''

        # 解析 out_trade_no 用于日志关联（resource 解密前的浅层解析）
        resource = body_json.get('resource', {})

        log_entry = PaymentCallbackLog.objects.create(
            out_trade_no=out_trade_no,  # 解密前暂时为空，解密后更新
            transaction_id=transaction_id,
            raw_body=raw_body,
        )

        # 验证签名（防篡改）
        try:
            pay_client = WechatPayV3()
        except FileNotFoundError as e:
            logger.error(f'支付客户端初始化失败: {e}')
            log_entry.process_result = 'failed'
            log_entry.process_error = str(e)
            log_entry.save(update_fields=['process_result', 'process_error'])
            return self._fail_response('服务器配置错误')

        if not pay_client.verify_callback_signature(request_headers, raw_body):
            logger.warning('微信回调签名验证失败')
            log_entry.process_result = 'failed'
            log_entry.process_error = '签名验证失败'
            log_entry.save(update_fields=['process_result', 'process_error'])
            return self._fail_response('签名验证失败')

        # 解密回调数据
        try:
            decrypted = pay_client.decrypt_callback(resource)
        except Exception as e:
            logger.error(f'微信回调解密失败: {e}')
            log_entry.process_result = 'failed'
            log_entry.process_error = f'解密失败: {e}'
            log_entry.save(update_fields=['process_result', 'process_error'])
            return self._fail_response('解密失败')

        # 更新日志记录（填充解密后数据）
        out_trade_no = decrypted.get('out_trade_no', '')
        transaction_id = decrypted.get('transaction_id', '')
        pay_time = decrypted.get('success_time', '')  # 格式：2018-06-08T10:34:56+08:00
        wx_amount = decrypted.get('amount', {}).get('payer_total', 0)  # 实付金额（分）

        log_entry.out_trade_no = out_trade_no
        log_entry.transaction_id = transaction_id
        log_entry.decrypted_data = decrypted
        log_entry.save(update_fields=['out_trade_no', 'transaction_id', 'decrypted_data'])

        # 仅处理支付成功事件
        event_type = body_json.get('event_type', '')
        if event_type != 'TRANSACTION.SUCCESS':
            logger.info(f'忽略非支付成功事件: {event_type}')
            log_entry.process_result = 'ignored'
            log_entry.save(update_fields=['process_result'])
            return self._success_response()

        # 执行业务处理
        try:
            process_payment_success(
                order_no=out_trade_no,
                transaction_id=transaction_id,
                pay_time=pay_time,
                wx_amount=wx_amount,
            )
            log_entry.process_result = 'success'
            log_entry.save(update_fields=['process_result'])
        except Exception as e:
            logger.exception(f'支付回调业务处理失败: {e}, out_trade_no={out_trade_no}')
            log_entry.process_result = 'failed'
            log_entry.process_error = str(e)
            log_entry.save(update_fields=['process_result', 'process_error'])
            # 返回失败，微信会重试（注意：不能返回 200，否则微信不会重试）
            return self._fail_response(str(e))

        return self._success_response()

    @staticmethod
    def _success_response():
        """微信要求的成功应答格式"""
        return Response({'code': 'SUCCESS', 'message': '成功'}, status=200)

    @staticmethod
    def _fail_response(message: str):
        """微信要求的失败应答格式（微信会重试）"""
        return Response({'code': 'FAIL', 'message': message}, status=200)


class PayMockSuccessView(APIView):
    """
    开发测试专用的模拟支付成功接口（仅在 DEBUG=True 且开发模式下可用）

    POST /api/pay/mock-success
    请求体：{ "order_no": "202506090001234" }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        from django.conf import settings
        from django.utils import timezone
        import uuid
        
        if not settings.DEBUG:
            return error('仅在开发调试模式下允许调用模拟支付', code=5005, status=403)

        order_no = request.data.get('order_no', '').strip()
        if not order_no:
            return error('order_no 不能为空', code=5001)

        try:
            from .models import PaymentRecord
            payment = PaymentRecord.objects.get(
                out_trade_no=order_no,
                status=PaymentRecord.STATUS_PENDING
            )
        except PaymentRecord.DoesNotExist:
            return error('未找到该订单的待支付记录', code=5006, status=404)

        try:
            process_payment_success(
                order_no=order_no,
                transaction_id=f"mock_tx_{uuid.uuid4().hex[:20]}",
                pay_time=timezone.now().isoformat(),
                wx_amount=payment.amount,
            )
        except Exception as e:
            logger.exception(f"模拟支付成功处理失败: {e}")
            return error(f"处理失败: {str(e)}", code=5007)

        return ok(message="模拟支付成功，订单已进入出库流程")

