"""
微信 API 工具类

封装微信小程序和微信支付 APIv3 的调用逻辑。
所有密钥和证书路径从 settings 读取，不在此处硬编码。
"""

import hashlib
import hmac
import json
import os
import time
import uuid
import base64
import logging
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings

logger = logging.getLogger(__name__)


class WechatMiniApp:
    """
    微信小程序 API 工具类

    主要用于：
    - 通过 code 换取 openid 和 session_key（登录）
    - 获取 Access Token
    - 获取用户手机号
    """

    # 微信接口地址
    JSCODE2SESSION_URL = 'https://api.weixin.qq.com/sns/jscode2session'
    ACCESS_TOKEN_URL = 'https://api.weixin.qq.com/cgi-bin/token'
    PHONE_NUMBER_URL = 'https://api.weixin.qq.com/wxa/business/getuserphonenumber'

    @classmethod
    def code_to_session(cls, code: str) -> dict:
        """
        通过微信登录 code 换取 openid 和 session_key

        :param code: 小程序端 wx.login() 返回的 code，有效期 5 分钟
        :return: {'openid': ..., 'session_key': ..., 'unionid': ...（可能无）}
        :raises: ValueError 当微信返回错误时
        """
        params = {
            'appid': settings.WECHAT_APP_ID,
            'secret': settings.WECHAT_APP_SECRET,
            'js_code': code,
            'grant_type': 'authorization_code',
        }
        try:
            resp = requests.get(cls.JSCODE2SESSION_URL, params=params, timeout=5)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error(f'微信 jscode2session 网络请求失败: {e}')
            raise ValueError('无法连接微信服务器，请稍后重试')

        if 'errcode' in data and data['errcode'] != 0:
            logger.error(f'微信 jscode2session 返回错误: {data}')
            raise ValueError(f'微信登录失败: {data.get("errmsg", "未知错误")}')

        return data

    @classmethod
    def get_access_token(cls) -> str:
        """
        获取微信小程序 Access Token (带 Redis 缓存)
        """
        from django.core.cache import cache
        token = cache.get('wechat_access_token')
        if token:
            logger.debug("从 Redis 缓存中获取到微信 Access Token")
            return token

        logger.info("微信 Access Token 缓存失效，向微信服务器申请新 Token...")
        params = {
            'grant_type': 'client_credential',
            'appid': settings.WECHAT_APP_ID,
            'secret': settings.WECHAT_APP_SECRET,
        }
        try:
            resp = requests.get(cls.ACCESS_TOKEN_URL, params=params, timeout=5)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error(f'微信获取 access_token 网络请求失败: {e}')
            raise ValueError('获取微信 Access Token 失败，网络异常')

        if 'errcode' in data and data['errcode'] != 0:
            logger.error(f'微信获取 access_token 返回错误: {data}')
            raise ValueError(f'获取微信 Access Token 失败: {data.get("errmsg", "未知错误")}')

        token = data.get('access_token')
        expires_in = data.get('expires_in', 7200)
        if token:
            # 缓存时间稍短于失效时间（预留200秒过渡）
            cache.set('wechat_access_token', token, expires_in - 200)
            logger.info(f"微信 Access Token 申请成功，已写入 Redis 缓存 (有效期: {expires_in - 200}秒)")
            return token
        
        raise ValueError('未在微信响应中找到 access_token')

    @classmethod
    def get_user_phone_number(cls, phone_code: str) -> str:
        """
        通过前端传来的 code 获取用户微信绑定的手机号
        https://developers.weixin.qq.com/miniprogram/dev/OpenApiDoc/user-info/phone-number/getPhoneNumber.html

        :param phone_code: 手机号获取凭证
        :return: 手机号 (通常是 purePhoneNumber，不带国家区号)
        """
        logger.info(f"开始调用微信 API 解密手机号，凭证(phone_code)为: {phone_code[:10]}...")
        access_token = cls.get_access_token()
        url = f"{cls.PHONE_NUMBER_URL}?access_token={access_token}"
        data = {
            'code': phone_code
        }
        try:
            resp = requests.post(url, json=data, timeout=5)
            resp.raise_for_status()
            resp_data = resp.json()
        except requests.RequestException as e:
            logger.error(f'微信 getuserphonenumber 网络请求失败: {e}')
            raise ValueError('获取手机号网络请求失败')

        if 'errcode' in resp_data and resp_data['errcode'] != 0:
            logger.error(f'微信 getuserphonenumber 返回错误: {resp_data}')
            raise ValueError(f'微信获取手机号失败: {resp_data.get("errmsg", "未知错误")}')

        phone_info = resp_data.get('phone_info')
        if not phone_info:
            raise ValueError('微信未返回手机号信息')

        phone = phone_info.get('purePhoneNumber') or phone_info.get('phoneNumber')
        if not phone:
            raise ValueError('解析手机号失败')
        
        logger.info(f"微信 API 手机号解密成功")
        return phone


class WechatPayV3:
    """
    微信支付 APIv3 工具类

    支持：
    - 小程序支付（JSAPI）下单
    - 回调验签和数据解密
    - 退款申请

    证书说明：
    - 商户私钥（apiclient_key.pem）：用于请求签名
    - APIv3 密钥（32字节）：用于回调数据解密
    """

    BASE_URL = 'https://api.mch.weixin.qq.com'

    def __init__(self):
        """初始化，加载商户私钥"""
        self.mch_id = settings.WECHAT_PAY_MCH_ID
        self.api_v3_key = settings.WECHAT_PAY_API_V3_KEY
        self.cert_serial = settings.WECHAT_PAY_CERT_SERIAL
        self.notify_url = settings.WECHAT_PAY_NOTIFY_URL

        # 加载商户私钥（PEM 格式）
        key_path = settings.WECHAT_PAY_PRIVATE_KEY_PATH
        if not os.path.exists(key_path):
            raise FileNotFoundError(f'商户私钥文件不存在: {key_path}')
        with open(key_path, 'rb') as f:
            self._private_key = serialization.load_pem_private_key(f.read(), password=None)

    def _build_authorization(self, method: str, url_path: str, body: str = '') -> str:
        """
        构建 APIv3 请求头 Authorization 字段

        签名规则：
        商户号\n时间戳\n随机字符串\n请求路径\n请求体\n
        用商户私钥 SHA256withRSA 签名，Base64 编码后拼接
        """
        timestamp = str(int(time.time()))
        nonce_str = uuid.uuid4().hex

        # 构造待签名消息
        message = f'{method}\n{url_path}\n{timestamp}\n{nonce_str}\n{body}\n'

        # RSA-SHA256 签名
        signature = self._private_key.sign(
            message.encode('utf-8'),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        sign_b64 = base64.b64encode(signature).decode()

        return (
            f'WECHATPAY2-SHA256-RSA2048 '
            f'mchid="{self.mch_id}",'
            f'nonce_str="{nonce_str}",'
            f'signature="{sign_b64}",'
            f'timestamp="{timestamp}",'
            f'serial_no="{self.cert_serial}"'
        )

    def _request(self, method: str, path: str, json_data: dict = None) -> dict:
        """
        发送微信支付 API 请求（统一入口，带签名）

        :param method: HTTP 方法（GET/POST 等）
        :param path: API 路径（不含域名）
        :param json_data: 请求体数据
        :return: 响应 JSON 数据
        """
        body = json.dumps(json_data, ensure_ascii=False) if json_data else ''
        auth = self._build_authorization(method, path, body)
        headers = {
            'Authorization': auth,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'AutoMachine/1.0',
        }
        url = self.BASE_URL + path
        try:
            resp = requests.request(
                method, url, data=body.encode('utf-8'),
                headers=headers, timeout=10
            )
            resp.raise_for_status()
            return resp.json() if resp.text else {}
        except requests.HTTPError as e:
            error_body = e.response.text if e.response else ''
            logger.error(f'微信支付请求失败 {path}: {e} | 响应: {error_body}')
            raise ValueError(f'微信支付接口错误: {error_body}')
        except requests.RequestException as e:
            logger.error(f'微信支付网络异常 {path}: {e}')
            raise ValueError('无法连接微信支付服务器')

    def create_jsapi_order(self, out_trade_no: str, amount: int,
                           openid: str, description: str) -> dict:
        """
        创建 JSAPI 小程序支付订单

        :param out_trade_no: 商户订单号（全局唯一）
        :param amount: 支付金额（分）
        :param openid: 用户 openid
        :param description: 商品描述
        :return: 微信返回的 prepay_id 等数据
        """
        if settings.DEBUG:
            logger.info(f"[DEBUG] Mocking WeChat Pay JSAPI order creation for out_trade_no={out_trade_no}")
            import uuid
            return {"prepay_id": f"mock_prepay_{uuid.uuid4().hex}"}

        path = '/v3/pay/transactions/jsapi'
        data = {
            'appid': settings.WECHAT_APP_ID,
            'mchid': self.mch_id,
            'description': description,
            'out_trade_no': out_trade_no,
            'notify_url': self.notify_url,
            'amount': {'total': amount, 'currency': 'CNY'},
            'payer': {'openid': openid},
        }
        return self._request('POST', path, data)

    def build_pay_params(self, prepay_id: str) -> dict:
        """
        构建小程序端调起支付所需的参数包

        小程序调用 wx.requestPayment() 需要这些参数，
        其中 paySign 由服务端用商户私钥签名生成。

        :param prepay_id: 下单接口返回的 prepay_id
        :return: 小程序支付参数字典
        """
        timestamp = str(int(time.time()))
        nonce_str = uuid.uuid4().hex
        package = f'prepay_id={prepay_id}'

        # 签名消息格式
        message = f'{settings.WECHAT_APP_ID}\n{timestamp}\n{nonce_str}\n{package}\n'
        signature = self._private_key.sign(
            message.encode('utf-8'),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        pay_sign = base64.b64encode(signature).decode()

        return {
            'appId': settings.WECHAT_APP_ID,
            'timeStamp': timestamp,
            'nonceStr': nonce_str,
            'package': package,
            'signType': 'RSA',
            'paySign': pay_sign,
        }

    def decrypt_callback(self, resource: dict) -> dict:
        """
        解密微信支付回调中的 resource 字段

        微信 APIv3 回调的核心数据使用 AEAD_AES_256_GCM 加密。
        解密密钥为 APIv3 密钥（settings.WECHAT_PAY_API_V3_KEY）。

        :param resource: 回调 JSON 中的 resource 字段
        :return: 解密后的订单数据字典
        """
        algorithm = resource.get('algorithm', '')
        if algorithm != 'AEAD_AES_256_GCM':
            raise ValueError(f'不支持的加密算法: {algorithm}')

        ciphertext = base64.b64decode(resource['ciphertext'])
        nonce = resource['nonce'].encode('utf-8')
        associated_data = resource.get('associated_data', '').encode('utf-8')

        # APIv3 密钥转为字节（32字节）
        key = self.api_v3_key.encode('utf-8')

        # AES-256-GCM 解密
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data)
        return json.loads(plaintext.decode('utf-8'))

    def verify_callback_signature(self, headers: dict, body: str) -> bool:
        """
        验证微信支付回调签名（防篡改）

        微信在回调 HTTP Header 中携带签名信息，
        服务端需下载微信平台证书公钥进行验证。
        此处实现简化版（生产中应严格验证平台证书）。

        :param headers: HTTP 请求头字典
        :param body: 请求原始 body 字符串
        :return: True 表示签名验证通过
        """
        # 注意：完整实现需要下载微信平台公钥，此处记录关键 Header 以供审计
        wechat_signature = headers.get('Wechatpay-Signature', '')
        wechat_timestamp = headers.get('Wechatpay-Timestamp', '')
        wechat_nonce = headers.get('Wechatpay-Nonce', '')

        if not all([wechat_signature, wechat_timestamp, wechat_nonce]):
            logger.warning('微信回调缺少签名相关 Header')
            return False

        # 检查时间戳（防重放：超过5分钟的回调拒绝）
        try:
            callback_time = int(wechat_timestamp)
            if abs(time.time() - callback_time) > 300:
                logger.warning(f'微信回调时间戳过期: {wechat_timestamp}')
                return False
        except ValueError:
            return False

        # TODO: 下载微信平台证书，使用公钥验证 wechat_signature
        # 生产上线前务必完善此处！
        logger.info('微信回调签名验证通过（待完善平台证书验证）')
        return True

    def apply_refund(self, out_refund_no: str, transaction_id: str,
                     refund_amount: int, total_amount: int, reason: str = '') -> dict:
        """
        申请退款

        :param out_refund_no: 商户退款单号
        :param transaction_id: 微信支付交易号
        :param refund_amount: 退款金额（分）
        :param total_amount: 原订单总金额（分）
        :param reason: 退款原因
        :return: 微信退款响应数据
        """
        path = '/v3/refund/domestic/refunds'
        data = {
            'transaction_id': transaction_id,
            'out_refund_no': out_refund_no,
            'reason': reason,
            'amount': {
                'refund': refund_amount,
                'total': total_amount,
                'currency': 'CNY',
            },
        }
        return self._request('POST', path, data)
