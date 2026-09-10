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
from rest_framework import serializers
from drf_spectacular.utils import extend_schema, OpenApiParameter

from utils.response import ok, error
from utils.wechat import WechatPayV3
from orders.models import OrderMain
from .models import PaymentCallbackLog
from .services import create_pay_request, process_payment_success
logger = logging.getLogger(__name__)


class PayCreateRequestSerializer(serializers.Serializer):
    order_no = serializers.CharField(required=True, max_length=64, help_text="商户订单号")


class PayNativeCreateRequestSerializer(serializers.Serializer):
    order_no = serializers.CharField(required=False, max_length=64, help_text="商户订单号")


class PayCodePayRequestSerializer(serializers.Serializer):
    order_no = serializers.CharField(required=True, max_length=64, help_text="商户订单号")
    auth_code = serializers.CharField(required=True, max_length=64, help_text="用户 18 位付款码")
    device_sn = serializers.CharField(required=False, allow_blank=True, max_length=128, help_text="设备编号 (可选)")


class PayTestCreateOrderRequestSerializer(serializers.Serializer):
    store_id = serializers.IntegerField(required=False, default=1, help_text="门店 ID")
    device_sn = serializers.CharField(required=False, default="sn005", help_text="设备 SN")
    item_id = serializers.IntegerField(required=False, help_text="商品 ID (可选)")


class PayMockSuccessRequestSerializer(serializers.Serializer):
    order_no = serializers.CharField(required=True, max_length=64, help_text="商户订单号")


class PayRefundRequestSerializer(serializers.Serializer):
    device_sn = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=128,
        help_text="设备编号 (如: sn005)"
    )
    refund_stock = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="退款退库存单号列表 (如: ['202608300001'])"
    )
    refund_no_stock = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="退款不退库存单号列表 (如: ['202608300002'])"
    )
    order_no = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        help_text="单个退款订单号 (可选，兼容单单退款)"
    )
    reason = serializers.CharField(
        required=False,
        default="设备或用户申请退款",
        max_length=256,
        help_text="退款原因"
    )


class PayRefundResponseDataSerializer(serializers.Serializer):
    success = serializers.BooleanField(help_text="是否全部成功")
    success_orders = serializers.ListField(
        child=serializers.CharField(),
        default=list,
        help_text="成功退款的订单号列表"
    )


class PayRefundResponseSerializer(serializers.Serializer):
    code = serializers.IntegerField(default=1, help_text="状态码 (1: 全部成功, 0: 失败或部分成功)")
    message = serializers.CharField(default="ok", help_text="提示信息")
    data = PayRefundResponseDataSerializer(help_text="返回数据")


class PayCreateView(APIView):
    """
    发起支付接口

    POST /api/pay/create
    请求体：{ "order_no": "202506090001234" }
    响应：微信小程序 wx.requestPayment() 所需参数
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="小程序支付下单 (JSAPI)",
        description="传入 order_no，返回微信小程序调起支付所需签名参数。",
        request=PayCreateRequestSerializer,
    )
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
    """
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(
        summary="Native 扫码支付下单",
        description="传入 order_no，返回支付二维码 code_url。",
        request=PayNativeCreateRequestSerializer,
    )
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
    """
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(
        summary="付款码支付 / 被扫支付",
        description="商户扫用户微信付款码扣款。",
        request=PayCodePayRequestSerializer,
    )
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
            if res.get('status') == 'failed':
                return error(res.get('message', '付款码支付失败'), code=5007, data=res)
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
    throttle_classes = []

    @extend_schema(
        summary="订单支付状态查询",
        description="根据订单号或交易号查询并同步最新支付状态。",
        parameters=[
            OpenApiParameter(name='order_no', description='商户订单号', required=False, type=str),
        ]
    )
    def get(self, request, order_id=None, order_no=None, out_trade_no=None):
        target_no = order_id or order_no or out_trade_no or request.query_params.get('order_no')
        if not target_no:
            return error('缺少订单号参数', code=5001)

        try:
            from .services import query_and_sync_payment_status
            sync_wechat = request.query_params.get('sync_wechat', '').lower() in ('1', 'true')
            status_data = query_and_sync_payment_status(target_no, sync_wechat=sync_wechat)
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
    throttle_classes = []

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
    throttle_classes = []

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
    throttle_classes = []

    @extend_schema(
        summary="模拟支付成功 (开发环境)",
        description="模拟微信支付成功并推进后续制作与出库流程。",
        request=PayMockSuccessRequestSerializer,
    )
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
    退款接口 (支持设备批量退款与单单退款)
    
    POST /api/pay/refund
    """
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(
        summary="退款接口 (支持设备批量退款与单单退款)",
        description="支持设备批量退款：输入 device_sn、退款退库存单号列表 (refund_stock)、退款不退库存单号列表 (refund_no_stock) 及 reason；也支持传入单个 order_no 执行单笔退款。",
        request=PayRefundRequestSerializer,
        responses={200: PayRefundResponseSerializer}
    )
    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        params = request.query_params

        device_sn = (
            data.get('device_sn') or params.get('device_sn') or
            data.get('sn') or params.get('sn') or
            data.get('device_no') or params.get('device_no') or ''
        )
        if isinstance(device_sn, str):
            device_sn = device_sn.strip()

        refund_stock = (
            data.get('refund_stock') or
            data.get('with_stock') or
            data.get('stock_orders') or
            data.get('refund_restore_stock_order_nos') or
            []
        )

        refund_no_stock = (
            data.get('refund_no_stock') or
            data.get('without_stock') or
            data.get('no_stock_orders') or
            data.get('refund_no_restore_stock_order_nos') or
            []
        )

        order_no = (
            data.get('order_no') or params.get('order_no') or
            data.get('orderNo') or params.get('orderNo') or ''
        )
        if isinstance(order_no, str):
            order_no = order_no.strip()

        reason = str(data.get('reason') or params.get('reason') or '退款申请').strip()

        # 场景 1：设备批量退款（传入 device_sn 或 退款单号列表）
        if device_sn or refund_stock or refund_no_stock:
            if not device_sn:
                sample_no = (refund_stock[0] if refund_stock else (refund_no_stock[0] if refund_no_stock else ''))
                order_obj = OrderMain.objects.filter(order_no=sample_no).first()
                if order_obj and order_obj.device:
                    device_sn = order_obj.device.device_sn
                else:
                    return Response({
                        'code': 0,
                        'message': '缺少设备编号 (device_sn)',
                        'data': {'success': False, 'success_orders': []}
                    }, status=400)

            from payments.services import batch_refund_device_orders
            try:
                result = batch_refund_device_orders(
                    device_sn=device_sn,
                    refund_stock=refund_stock,
                    refund_no_stock=refund_no_stock,
                    reason=reason
                )
                is_success = result.get('success', False)
                msg = 'ok' if is_success else ('部分退款成功' if result.get('success_orders') else '退款处理失败')
                return Response({
                    'code': 1 if is_success else 0,
                    'message': msg,
                    'data': result
                })
            except ValueError as e:
                return Response({
                    'code': 0,
                    'message': str(e),
                    'data': {'success': False, 'success_orders': []}
                }, status=400)
            except Exception as e:
                logger.exception(f"批量退款异常: {e}")
                return Response({
                    'code': 0,
                    'message': f"退款处理异常: {e}",
                    'data': {'success': False, 'success_orders': []}
                }, status=500)

        # 场景 2：单单退款（传入 order_no）
        if not order_no:
            return Response({
                'code': 0,
                'message': '请提供 device_sn 与退款单号列表，或提供单个 order_no',
                'data': {'success': False, 'success_orders': []}
            }, status=400)

        try:
            order_qs = OrderMain.objects.prefetch_related('items').filter(order_no=order_no)
            if request.user and request.user.is_authenticated:
                order = order_qs.filter(user=request.user).first() or order_qs.first()
            else:
                order = order_qs.first()
            if not order:
                return Response({
                    'code': 0,
                    'message': '订单不存在',
                    'data': {'success': False, 'success_orders': []}
                }, status=404)
        except Exception as e:
            return Response({
                'code': 0,
                'message': f'查询订单失败: {e}',
                'data': {'success': False, 'success_orders': []}
            }, status=400)

        from payments.services import refund_order
        from orders.services import restore_order_inventory
        try:
            restore_res = None
            is_unproduced = order.status in [OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING]
            should_restore = is_unproduced or bool(data.get('restore_stock', False))

            refund_order(order, reason=reason)
            if should_restore:
                restore_res = restore_order_inventory(
                    order=order,
                    operator=f'user:{request.user.id if request.user.is_authenticated else "kiosk"}',
                    reason=reason
                )

            return Response({
                'code': 1,
                'message': '退款处理成功（已释放物料库存）' if (restore_res and restore_res.get('restored_materials')) else '退款处理成功',
                'data': {
                    'success': True,
                    'success_orders': [order.order_no],
                    'order_no': order.order_no,
                    'restored_materials': restore_res.get('restored_materials', []) if restore_res else []
                }
            })
        except Exception as e:
            logger.exception(f"单单退款异常: {e}")
            return Response({
                'code': 0,
                'message': f"退款处理异常: {e}",
                'data': {'success': False, 'success_orders': []}
            }, status=500)
