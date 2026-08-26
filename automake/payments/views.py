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

        # 【支付流程 1：客户端请求】查找订单，并验证是当前用户的订单（防止越权）
        try:
            order = OrderMain.objects.prefetch_related('items').get(
                order_no=order_no,
                user=request.user,
            )
        except OrderMain.DoesNotExist:
            return error('订单不存在', code=5002, status=404)

        try:
            # 【支付流程 2 & 3：生成预支付单与签名】
            # 内部逻辑会请求微信服务器获取 prepay_id，并使用本地商户私钥对参数进行 RSA 签名
            pay_params = create_pay_request(order, request.user)
        except ValueError as e:
            return error(str(e), code=5003)
        except Exception as e:
            logger.exception(f'发起支付异常: {e}')
            return error('支付系统异常，请稍后重试', code=5004, status=500)

        # 返回签名后的包给前端，前端拿着这些参数调用 wx.requestPayment() 唤起微信收银台
        return ok(pay_params, message='支付参数获取成功')


class PayNativeCreateView(APIView):
    """
    Native 扫码支付下单接口 (用户扫商户二维码)

    POST /api/pay/wechat/native
    POST /api/orders/<str:order_id>/native-payment/
    请求体：{ "order_no": "20260825123456" } (若 URL 中包含 order_id 可省略)
    响应：包含 code_url，供上位机/前端生成二维码展示
    """
    permission_classes = [AllowAny]

    def post(self, request, order_id=None):
        order_no = order_id or request.data.get('order_no', '').strip()
        if not order_no:
            return error('缺少 order_no 参数', code=5001)

        try:
            order = OrderMain.objects.prefetch_related('items').get(order_no=order_no)
        except OrderMain.DoesNotExist:
            return error('订单不存在', code=5002, status=404)

        try:
            from .services import create_native_pay_request
            res = create_native_pay_request(order, user=request.user if request.user.is_authenticated else order.user)
            return ok(res, message='Native 支付二维码生成成功')
        except ValueError as e:
            return error(str(e), code=5003)
        except Exception as e:
            logger.exception(f'生成 Native 支付二维码异常: {e}')
            return error('支付系统异常，请稍后重试', code=5004, status=500)


class PayCodePayView(APIView):
    """
    付款码支付接口 (商户扫用户微信付款码 / 被扫支付)

    POST /api/internal/payments/wechat/codepay/
    POST /api/pay/wechat/codepay
    请求体：
    {
        "order_no": "20260825123456",
        "auth_code": "134567890123456789",  // 18位付款码
        "device_sn": "sn005"                 // 可选
    }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        order_no = request.data.get('order_no', '').strip()
        auth_code = request.data.get('auth_code', '').strip()
        device_sn = request.data.get('device_sn', '').strip()

        if not order_no or not auth_code:
            return error('order_no 和 auth_code 均不能为空', code=5001)

        try:
            order = OrderMain.objects.prefetch_related('items').get(order_no=order_no)
        except OrderMain.DoesNotExist:
            return error('订单不存在', code=5002, status=404)

        try:
            from .services import process_codepay_request
            # 获取客户端IP
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            client_ip = x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR', '127.0.0.1')

            res = process_codepay_request(
                order=order,
                auth_code=auth_code,
                device_sn=device_sn,
                user=request.user if request.user.is_authenticated else order.user,
                spbill_create_ip=client_ip
            )
            return ok(res, message=res.get('message', '扣款请求已处理'))
        except ValueError as e:
            return error(str(e), code=5003)
        except Exception as e:
            logger.exception(f'付款码支付异常: {e}')
            return error(f'付款码支付系统异常: {e}', code=5004, status=500)


class PayStatusQueryView(APIView):
    """
    订单支付与制作状态查询接口 (支持主动查单补偿)

    GET /api/orders/<str:order_id>/payment-status/
    GET /api/pay/status/<str:order_no>
    GET /api/internal/payments/<str:out_trade_no>/status/
    """
    permission_classes = [AllowAny]

    def get(self, request, order_id=None, order_no=None, out_trade_no=None):
        target_no = order_id or order_no or out_trade_no or request.query_params.get('order_no')
        if not target_no:
            return error('缺少订单号参数', code=5001)

        try:
            from .services import query_and_sync_payment_status
            status_data = query_and_sync_payment_status(target_no)
            return ok(status_data, message='查询成功')
        except ValueError as e:
            return error(str(e), code=5002, status=404)
        except Exception as e:
            logger.exception(f'查询支付状态异常: {e}')
            return error('查询支付状态系统异常', code=5004, status=500)


class PaymentTestPageView(APIView):
    """
    真实微信支付测试控制台 (Native 扫码 & 付款码 2合1 测试界面)
    GET /payment-test/
    """
    permission_classes = [AllowAny]

    def get(self, request):
        from django.shortcuts import render
        from stores.models import Store
        from devices.models import Device
        from menus.models import MenuItem

        stores = Store.objects.filter(status=Store.STATUS_OPEN)
        devices = Device.objects.filter(status=Device.STATUS_ONLINE)
        items = MenuItem.objects.filter(is_active=True).select_related('global_item')[:10]

        context = {
            'stores': stores,
            'devices': devices,
            'items': items,
        }
        return render(request, 'payments/test.html', context)


class PayTestCreateOrderView(APIView):
    """
    测试专用：一键免鉴权创建 0.01 元真实测试订单
    POST /api/pay/test/create-order
    """
    permission_classes = [AllowAny]

    def post(self, request):
        from users.models import User
        from stores.models import Store
        from devices.models import Device
        from menus.models import MenuItem, MenuSku
        from orders.models import OrderMain, OrderItem

        store_id = request.data.get('store_id', 1)
        device_sn = request.data.get('device_sn', 'sn005')
        item_id = request.data.get('item_id')

        store = Store.objects.filter(id=store_id).first() or Store.objects.filter(status=Store.STATUS_OPEN).first()
        device = Device.objects.filter(device_sn=device_sn).first() or Device.objects.filter(status=Device.STATUS_ONLINE).first()
        
        # 获取或创建测试用户
        user, _ = User.objects.get_or_create(openid='oJqP67L3test_pay_user_openid')

        item = MenuItem.objects.filter(id=item_id).first() if item_id else MenuItem.objects.filter(store=store, is_active=True).first()
        if not item:
            item = MenuItem.objects.filter(is_active=True).first()

        # 创建 0.01 元测试订单
        order = OrderMain.objects.create(
            user=user,
            store=store,
            device=device,
            total_amount=1, # 0.01元
            discount_amount=0,
            pay_amount=1,   # 1分钱
            status=OrderMain.STATUS_PENDING_PAY
        )

        sku_name = "默认规格"
        sku_obj = None
        if item:
            sku_obj = MenuSku.objects.filter(item=item, is_active=True).first()
            if sku_obj and sku_obj.global_sku and sku_obj.global_sku.template:
                sku_name = sku_obj.global_sku.template.name

        order_item = OrderItem.objects.create(
            order=order,
            item=item,
            item_name=item.name if item else "测试拿铁",
            sku_name=sku_name,
            quantity=1,
            unit_price=1,
            subtotal=1
        )
        if sku_obj:
            order_item.skus.add(sku_obj)

        return ok({
            'order_no': order.order_no,
            'pay_amount': order.pay_amount,
            'status': order.status,
            'status_display': order.get_status_display(),
            'device_sn': device.device_sn if device else '',
            'store_name': store.name if store else ''
        }, message='测试订单创建成功 (0.01元)')


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

        # 【支付流程 3 - 步骤 2：防篡改验签】验证请求头中的签名，确保消息真实来自于微信
        if not pay_client.verify_callback_signature(request_headers, raw_body):
            logger.warning('微信回调签名验证失败')
            log_entry.process_result = 'failed'
            log_entry.process_error = '签名验证失败'
            log_entry.save(update_fields=['process_result', 'process_error'])
            return self._fail_response('签名验证失败')

        # 解密回调数据
        # 【支付流程 3 - 步骤 3：数据解密】使用 APIv3 密钥，解密 AES-256-GCM 密文数据
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

        event_type = body_json.get('event_type', '')

        try:
            if event_type == 'TRANSACTION.SUCCESS':
                # 【支付流程 4：业务履约与处理】交由核心服务层执行订单后续逻辑
                process_payment_success(
                    order_no=out_trade_no,
                    transaction_id=transaction_id,
                    pay_time=pay_time,
                    wx_amount=wx_amount,
                )
                log_entry.process_result = 'success'
                log_entry.save(update_fields=['process_result'])

            elif event_type.startswith('REFUND.'):
                from .services import process_refund_callback
                out_refund_no = decrypted.get('out_refund_no', '')
                refund_status = decrypted.get('refund_status', '')
                process_refund_callback(
                    out_refund_no=out_refund_no,
                    refund_status=refund_status
                )
                log_entry.process_result = 'success'
                log_entry.save(update_fields=['process_result'])

            else:
                logger.info(f'忽略无需处理的事件: {event_type}')
                log_entry.process_result = 'ignored'
                log_entry.save(update_fields=['process_result'])

        except Exception as e:
            logger.exception(f'微信回调业务处理失败: {e}, out_trade_no={out_trade_no}')
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

        from .models import PaymentRecord
        from orders.models import OrderMain

        try:
            order = OrderMain.objects.get(order_no=order_no)
        except OrderMain.DoesNotExist:
            return error('未找到该订单', code=5002, status=404)

        payment, _ = PaymentRecord.objects.get_or_create(
            out_trade_no=order_no,
            defaults={
                'order': order,
                'user': order.user,
                'amount': order.pay_amount,
                'status': PaymentRecord.STATUS_PENDING
            }
        )

        try:
            from .services import confirm_payment_success
            confirm_payment_success(
                out_trade_no=order_no,
                transaction_id=f"mock_tx_{uuid.uuid4().hex[:20]}",
                paid_amount_fen=payment.amount,
                source="mock"
            )
        except Exception as e:
            logger.exception(f"模拟支付成功处理失败: {e}")
            return error(f"处理失败: {str(e)}", code=5007)

        return ok(message="模拟支付成功，订单已进入出库流程")


class PayRefundView(APIView):
    """
    主动退款接口
    
    POST /api/pay/refund
    请求体：{ "order_no": "202506090001234" }
    逻辑：只有在订单尚未开始制作时（STATUS_PAID），允许自动退款。
    操作包括：向下发取消指令、释放Redis库存、调用微信退款接口。
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        order_no = request.data.get('order_no', '').strip()
        if not order_no:
            return error('order_no 不能为空', code=5001)

        try:
            order = OrderMain.objects.prefetch_related('items').get(order_no=order_no, user=request.user)
        except OrderMain.DoesNotExist:
            return error('订单不存在', code=5002, status=404)

        # 检查是否可以自动退款：必须是 PENDING_DISPENSE (STATUS_PAID)
        if order.status != OrderMain.STATUS_PAID:
            return error('无法自动完成退款，订单可能已开始制作或已处理，请联系客服', code=5008)

        from mqtt import issue_device_command
        from orders.services import update_order_status

        # 1. 向设备下发取消指令 (撤单)
        if order.device:
            success = issue_device_command(
                device_sn=order.device.device_sn,
                command_type='cancel',
                order_no=order.order_no
            )
            if not success:
                return error('设备离线或下发指令失败，无法自动撤单退款，请联系客服', code=5010)
        else:
            return error('订单未绑定设备，无法撤单', code=5011)

        # 记录状态（可选，标识正在撤单中）
        update_order_status(
            order=order,
            new_status=OrderMain.STATUS_REFUNDING,
            operator='user',
            remark='用户申请退款，等待设备确认撤单'
        )

        return ok(message='撤单指令已下发，等待设备确认后将自动退款')


