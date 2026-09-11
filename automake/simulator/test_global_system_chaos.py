#!/usr/bin/env python3
"""
全系统业务逻辑混沌模糊与不变量测试套件 (Global System Chaos & Invariant Test Suite)

遵循原则：
1. 严格只测不改 (Report Only, No Direct Code Changes)。
2. 独立第三方判定基准 (System Oracle)，跳出逻辑自证闭环。
3. 涵盖 8 大核心业务领域：
   - 领域 1: 订单状态机单向流转与终态防篡改
   - 领域 2: 支付回调 20 并发幂等与资金守恒
   - 领域 3: 水平/垂直越权安全渗透 (IDOR & Privilege Escalation)
   - 领域 4: 取餐码并发与跨日翻转测试
   - 领域 5: 制作中退款时序与硬件 MQTT Cancel 响应对抗
   - 领域 6: 耗材双写与 Redis 存储单位审计
   - 领域 7: 优惠券与积分闭环核算审计
   - 领域 8: 耗材防二次扣减对 Redis 的易失性依赖审计
"""

import os
import sys
import time
import json
import logging
import threading
from decimal import Decimal
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# 初始化 Django 运行环境
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')
import django
django.setup()

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone
from django_redis import get_redis_connection
from rest_framework.test import APIRequestFactory, force_authenticate

from global_config.models import (
    DeviceModel, GlobalMenuCategory, GlobalMenuItem,
    GlobalSkuTemplate, GlobalMenuSku, GlobalSkuIngredient
)
from stores.models import Store
from devices.models import Device, DeviceBarrelDict, DeviceConsumableStock, DeviceCommand
from inventory.models import Material
from menus.models import MenuItem, MenuSku
from orders.models import OrderMain, OrderItem, OrderStatusLog, ProductionTask
from payments.models import PaymentRecord, RefundRecord
from notifications.models import PickupCode

User = get_user_model()
logger = logging.getLogger(__name__)


class GlobalChaosTestReport:
    """审计测试报告聚合器"""
    def __init__(self):
        self.findings = []
        self.passed_tests = []
        self.lock = threading.Lock()

    def record_finding(self, domain: str, severity: str, title: str, details: str, code_location: str = ''):
        with self.lock:
            self.findings.append({
                'domain': domain,
                'severity': severity, # CRITICAL, HIGH, MEDIUM, LOW
                'title': title,
                'details': details,
                'code_location': code_location,
                'timestamp': datetime.now().isoformat()
            })

    def record_pass(self, domain: str, title: str):
        with self.lock:
            self.passed_tests.append({
                'domain': domain,
                'title': title
            })

    def print_summary(self):
        print("\n" + "="*80)
        print("          AutoMake 全系统业务逻辑与安全渗透审计报告 (Summary)")
        print("="*80)
        print(f"✅ 通过的不变量测试项: {len(self.passed_tests)}")
        print(f"🚨 发现的潜在隐患/缺陷: {len(self.findings)}")
        print("-" * 80)
        
        for idx, f in enumerate(self.findings, 1):
            color = "\033[91m" if f['severity'] in ('CRITICAL', 'HIGH') else "\033[93m"
            reset = "\033[0m"
            print(f"{color}[{f['severity']}] #{idx} 领域: {f['domain']} - {f['title']}{reset}")
            print(f"   代码位置: {f['code_location']}")
            print(f"   详细说明: {f['details']}\n")
        
        print("="*80)


report = GlobalChaosTestReport()


def setup_test_fixtures():
    """初始化基础测试固件"""
    with transaction.atomic():
        # 1. 用户
        user_a, _ = User.objects.get_or_create(username='test_user_a', defaults={'is_active': True, 'role': 'customer'})
        user_b, _ = User.objects.get_or_create(username='test_user_b', defaults={'is_active': True, 'role': 'customer'})
        staff_user, _ = User.objects.get_or_create(username='test_staff_m', defaults={'is_active': True, 'role': 'material_admin'})
        coord_user, _ = User.objects.get_or_create(username='test_coord_c', defaults={'is_active': True, 'role': 'coordinator'})

        # 2. 门店与设备
        store, _ = Store.objects.get_or_create(
            name='混沌测试旗舰店',
            defaults={'status': Store.STATUS_OPEN, 'address': '高新南九道99号', 'lat': 22.54, 'lng': 113.94}
        )
        store.status = Store.STATUS_OPEN
        store.save()

        dev_model, _ = DeviceModel.objects.get_or_create(code='MODEL_CHAOS', defaults={'name': '全景混沌测试机型'})
        device, _ = Device.objects.get_or_create(
            device_sn='SN_GLOBAL_CHAOS_01',
            defaults={
                'device_name': '全局测试现制机',
                'store': store,
                'device_model': dev_model,
                'status': Device.STATUS_ONLINE
            }
        )
        device.status = Device.STATUS_ONLINE
        device.save()

        # 3. 基础耗材
        for code, name, unit, qty in [
            ('paperL', '大纸杯', '个', 500),
            ('paperM', '中纸杯', '个', 500),
            ('plasticL', '大塑料杯', '个', 500),
            ('plasticM', '中塑料杯', '个', 500),
            ('lid', '杯盖', '个', 500),
            ('membrane', '封口膜', '张', 500),
        ]:
            mat, _ = Material.objects.get_or_create(
                code=code,
                defaults={'name': name, 'unit': unit, 'material_type': Material.TYPE_CONSUMABLE}
            )
            cs, _ = DeviceConsumableStock.objects.get_or_create(
                device=device,
                code=mat,
                defaults={'quantity': qty, 'init_quantity': qty, 'warn_level': 20, 'stop_sale_level': 5}
            )
            cs.quantity = qty
            cs.save()

        # 4. 商品与 SKU
        cat, _ = GlobalMenuCategory.objects.get_or_create(
            name='全局咖啡系列',
            device_model=dev_model,
            defaults={'sort_order': 1, 'is_active': True}
        )
        g_item, _ = GlobalMenuItem.objects.get_or_create(
            category=cat,
            name='热美式咖啡',
            defaults={'base_price': 1500, 'is_active': True}
        )
        menu_item, _ = MenuItem.objects.get_or_create(
            store=store,
            global_item=g_item,
            defaults={'device_model': dev_model, 'base_price': 1500, 'is_active': True}
        )

    return {
        'user_a': user_a,
        'user_b': user_b,
        'staff_user': staff_user,
        'coord_user': coord_user,
        'store': store,
        'device': device,
        'menu_item': menu_item
    }


# ============================================================================
# 领域 1: 订单状态机单向流转与终态防篡改
# ============================================================================
def test_domain_state_machine_integrity(ctx):
    print("▶ 正在检验 [领域 1: 状态机单向流转与终态防篡改]...")
    user = ctx['user_a']
    store = ctx['store']
    device = ctx['device']

    # 1. 检验已退款订单防迟到的 MQTT 硬件回调覆盖
    ord_refunded = OrderMain.objects.create(
        user=user, store=store, device=device,
        total_amount=1500, pay_amount=1500, status=OrderMain.STATUS_REFUNDED
    )
    from devices.views import receive_device_status
    # 模拟硬件迟到上报 done 消息
    done_payload = {
        'type': 'order_status',
        'order_no': ord_refunded.order_no,
        'status': 'done',
        'message': '硬件出杯完成'
    }
    receive_device_status(device.device_sn, done_payload)
    ord_refunded.refresh_from_db()
    
    if ord_refunded.status == OrderMain.STATUS_DONE:
        report.record_finding(
            domain='状态机流转',
            severity='CRITICAL',
            title='迟到的硬件 done 回调覆盖已退款订单状态',
            details=f'订单 {ord_refunded.order_no} 已处于 REFUNDED 终态，接收到硬件回调后状态被反向篡改为 DONE！',
            code_location='devices/views.py#receive_device_status'
        )
    else:
        report.record_pass('状态机流转', '已退款订单成功防御迟到的硬件 done 回调覆盖')

    # 2. 检验待支付订单是否允许直接被取消
    from orders.services import cancel_order
    ord_pending = OrderMain.objects.create(
        user=user, store=store, device=device,
        total_amount=1500, pay_amount=1500, status=OrderMain.STATUS_PENDING_PAY
    )
    try:
        cancel_order(ord_pending, operator='user_test', remark='主动取消')
        ord_pending.refresh_from_db()
        if ord_pending.status == OrderMain.STATUS_CANCELLED:
            report.record_pass('状态机流转', '待支付订单正常取消流转至 CANCELLED')
    except Exception as e:
        report.record_finding(
            domain='状态机流转',
            severity='MEDIUM',
            title='待支付订单取消失败',
            details=f'合法待支付订单调用 cancel_order 抛出异常: {e}',
            code_location='orders/services.py#cancel_order'
        )

    # 3. 检验已出杯完成订单是否能被 cancel_order 违规取消
    ord_done = OrderMain.objects.create(
        user=user, store=store, device=device,
        total_amount=1500, pay_amount=1500, status=OrderMain.STATUS_DONE
    )
    try:
        cancel_order(ord_done, operator='user_test', remark='试图取消已完成订单')
        ord_done.refresh_from_db()
        if ord_done.status == OrderMain.STATUS_CANCELLED:
            report.record_finding(
                domain='状态机流转',
                severity='HIGH',
                title='已出杯完成订单被非法取消',
                details=f'已处于 DONE 状态的订单竟然被 cancel_order 强制变更为 CANCELLED！',
                code_location='orders/services.py#cancel_order'
            )
    except ValueError:
        report.record_pass('状态机流转', '已完成订单受到保护，禁止被 cancel_order 非法取消')


# ============================================================================
# 领域 2: 支付回调 20 并发幂等性与资金守恒
# ============================================================================
def test_domain_payment_idempotency_and_concurrency(ctx):
    print("▶ 正在检验 [领域 2: 支付回调 20 并发幂等与资金守恒]...")
    user = ctx['user_a']
    store = ctx['store']
    device = ctx['device']
    menu_item = ctx['menu_item']

    from orders.services import create_order
    from payments.services import confirm_payment_success

    # 创建合法待支付订单
    items_data = [{'item': menu_item.id, 'sku': [], 'quantity': 1}]
    order = create_order(user, store.id, items_data, device_sn=device.device_sn)

    payment, _ = PaymentRecord.objects.get_or_create(
        out_trade_no=order.order_no,
        defaults={
            'order': order,
            'user': user,
            'amount': order.pay_amount,
            'status': PaymentRecord.STATUS_PENDING
        }
    )

    # 记录初始耗材库存
    cs_paper = DeviceConsumableStock.objects.get(device=device, code__code='paperL')
    init_qty = cs_paper.quantity

    # 模拟微信支付网关并发 20 次重试通知
    def _call_confirm(idx):
        try:
            return confirm_payment_success(
                out_trade_no=order.order_no,
                transaction_id=f"mock_tx_wx_{order.order_no}",
                paid_amount_fen=order.pay_amount,
                source='wechat_callback_stress'
            )
        except Exception as e:
            return str(e)

    results = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(_call_confirm, i) for i in range(20)]
        for fut in as_completed(futures):
            results.append(fut.result())

    # 判定 1: ProductionTask 是否严格唯一
    task_count = ProductionTask.objects.filter(order=order).count()
    if task_count > 1:
        report.record_finding(
            domain='支付幂等',
            severity='CRITICAL',
            title='并发支付回调导致重复生成生产任务 (Double Production Task)',
            details=f'订单 {order.order_no} 受到 20 次并发支付通知后，生成了 {task_count} 个 ProductionTask 硬件制作凭据！将导致机器重复制作出杯！',
            code_location='payments/services.py#process_payment_success'
        )
    else:
        report.record_pass('支付幂等', '并发支付通知下生产任务严格唯一 (1 Task)')

    # 判定 2: 耗材扣减量是否严格等于 1 个杯子
    cs_paper.refresh_from_db()
    deducted_qty = init_qty - cs_paper.quantity
    if deducted_qty != 1:
        report.record_finding(
            domain='支付资金与物料守恒',
            severity='HIGH',
            title='并发支付通知下耗材扣减量与需求量不符',
            details=f'需求 1 个纸杯，20 次并发回调后实际扣减了 {deducted_qty} 个纸杯！',
            code_location='payments/services.py#process_payment_success'
        )
    else:
        report.record_pass('支付资金与物料守恒', '并发支付通知下耗材严格扣减 1 次，无重复扣减')

    # 判定 3: 篡改金额攻击检验 (金额不匹配)
    ord_tamper = create_order(user, store.id, items_data, device_sn=device.device_sn)
    PaymentRecord.objects.create(
        out_trade_no=ord_tamper.order_no,
        order=ord_tamper,
        user=user,
        amount=ord_tamper.pay_amount,
        status=PaymentRecord.STATUS_PENDING
    )
    tamper_blocked = False
    try:
        confirm_payment_success(
            out_trade_no=ord_tamper.order_no,
            transaction_id=f"mock_tx_tamper_{ord_tamper.order_no}",
            paid_amount_fen=ord_tamper.pay_amount - 100, # 少付 1 元
            source='tamper_attack'
        )
    except ValueError:
        tamper_blocked = True

    if tamper_blocked:
        report.record_pass('资金安全', '金额篡改回调被 100% 拦截并阻断')
    else:
        report.record_finding(
            domain='资金安全',
            severity='CRITICAL',
            title='少付金额回调未被拦截 (Underpayment Vulnerability)',
            details=f'订单应付 {ord_tamper.pay_amount} 分，回调支付 {ord_tamper.pay_amount - 100} 分，系统未能成功阻断！',
            code_location='payments/services.py#process_payment_success'
        )


# ============================================================================
# 领域 3: 水平与垂直越权安全渗透 (IDOR & Privilege Escalation)
# ============================================================================
def test_domain_security_privilege_escalation(ctx):
    print("▶ 正在检验 [领域 3: 水平与垂直越权安全渗透 (IDOR & Privilege Escalation)]...")
    user_a = ctx['user_a']
    user_b = ctx['user_b']
    store = ctx['store']
    device = ctx['device']

    factory = APIRequestFactory()

    # ------------------------------------------------------------------------
    # 3.1 水平越权退款 (IDOR in PayRefundView)
    # ------------------------------------------------------------------------
    ord_b = OrderMain.objects.create(
        user=user_b, store=store, device=device,
        total_amount=2000, pay_amount=2000, status=OrderMain.STATUS_PAID
    )
    PaymentRecord.objects.create(
        out_trade_no=ord_b.order_no,
        order=ord_b,
        user=user_b,
        amount=2000,
        status=PaymentRecord.STATUS_SUCCESS,
        transaction_id=f"mock_tx_{ord_b.order_no}"
    )

    from payments.views import PayRefundView
    view_refund = PayRefundView.as_view()

    r = get_redis_connection('default')
    def _responder_idor():
        for _ in range(25):
            time.sleep(0.2)
            r.set(f"automake:cancel_ack:{ord_b.order_no}", json.dumps({'type': 'cancel_ack', 'status': 'ok', 'order_no': ord_b.order_no}), ex=10)
    threading.Thread(target=_responder_idor, daemon=True).start()

    req = factory.post(
        '/api/pay/refund',
        data={'order_no': ord_b.order_no, 'reason': '用户A恶意水平越权退款用户B的订单'},
        format='json'
    )
    force_authenticate(req, user=user_a)
    resp = view_refund(req)

    ord_b.refresh_from_db()
    if ord_b.status == OrderMain.STATUS_REFUNDED or (resp.status_code == 200 and resp.data.get('code') == 1):
        report.record_finding(
            domain='安全漏洞 (IDOR)',
            severity='CRITICAL',
            title='严重水平越权漏洞：普通用户 A 可退款普通用户 B 的订单',
            details=(
                f"在 payments/views.py 的 PayRefundView 中，由于回退逻辑 `order = order_qs.filter(user=request.user).first() or order_qs.first()`，"
                f"用户 A 携带自身 Token 请求退款用户 B 的订单 {ord_b.order_no}，系统成功响应 200 并将用户 B 的订单退款！"
            ),
            code_location='payments/views.py#L693-L696'
        )
    else:
        report.record_pass('安全防护', '水平越权退款已被正确拦截')

    # ------------------------------------------------------------------------
    # 3.2 垂直越权：普通顾客调用物料员接口修改耗材库存
    # ------------------------------------------------------------------------
    from devices.staff_views import StaffConsumableUpdateView
    view_consumable = StaffConsumableUpdateView.as_view()

    req_update = factory.post(
        '/api/staff/consumables/update',
        data={
            'device_sn': device.device_sn,
            'items': [{'code': 'paperL', 'quantity': 999}]
        },
        format='json'
    )
    force_authenticate(req_update, user=user_a) # 普通顾客身份
    resp_update = view_consumable(req_update)

    if resp_update.status_code == 200:
        report.record_finding(
            domain='安全漏洞 (垂直越权)',
            severity='CRITICAL',
            title='垂直越权：普通顾客可直接调用物料员接口任意修改设备耗材',
            details=(
                f"StaffConsumableUpdateView 仅声明 permission_classes = [IsAuthenticated]，缺少角色校验。"
                f"普通顾客 user_a (role='customer') 调用 POST /api/staff/consumables/update 成功返回 200 并篡改了库存！"
            ),
            code_location='devices/staff_views.py#L123'
        )
    else:
        report.record_pass('安全防护', '物料员耗材更新接口对普通顾客拦截成功')

    # ------------------------------------------------------------------------
    # 3.3 垂直越权：普通顾客下发设备 Action (如 reset / sync)
    # ------------------------------------------------------------------------
    from devices.staff_views import StaffDeviceActionView
    view_action = StaffDeviceActionView.as_view()

    req_action = factory.post(
        f'/api/staff/devices/{device.device_sn}/action',
        data={'action': 'reset'},
        format='json'
    )
    force_authenticate(req_action, user=user_a) # 普通顾客身份
    resp_action = view_action(req_action, device_sn=device.device_sn)

    if resp_action.status_code == 200:
        report.record_finding(
            domain='安全漏洞 (垂直越权)',
            severity='CRITICAL',
            title='垂直越权：普通顾客可直接下发指令重启复位硬件设备',
            details=(
                f"StaffDeviceActionView 仅配置 permission_classes = [IsAuthenticated]。"
                f"普通顾客 user_a 调用 POST /api/staff/devices/{device.device_sn}/action 成功下发 reset 指令！"
            ),
            code_location='devices/staff_views.py#L178'
        )
    else:
        report.record_pass('安全防护', '协调员设备控制指令接口对普通顾客拦截成功')


# ============================================================================
# 领域 4: 取餐码并发生成、跨日翻转与全局唯一键冲突
# ============================================================================
def test_domain_pickup_code_lifecycle(ctx):
    print("▶ 正在检验 [领域 4: 取餐码并发生成、跨日翻转与全局唯一键冲突]...")
    user = ctx['user_a']
    store = ctx['store']
    device = ctx['device']

    from notifications.services import create_pickup_code

    # 1. 检验单表 unique=True 下的历史遗留编号跳跃与碰撞风险
    # 模拟历史数据库中已存在 '0001' 号取餐码
    ord_hist = OrderMain.objects.create(
        user=user, store=store, device=device,
        total_amount=1000, pay_amount=1000, status=OrderMain.STATUS_PAID,
        paid_at=timezone.now() - timedelta(days=2) # 2天前
    )
    PickupCode.objects.filter(code='0001').delete()
    PickupCode.objects.create(
        order=ord_hist,
        code='0001',
        expires_at=timezone.now() + timedelta(minutes=30),
        status=PickupCode.STATUS_ACTIVE
    )

    # 今日第一笔订单
    ord_today = OrderMain.objects.create(
        user=user, store=store, device=device,
        total_amount=1000, pay_amount=1000, status=OrderMain.STATUS_PAID,
        paid_at=timezone.now()
    )
    
    code_created = None
    try:
        pk_obj = create_pickup_code(ord_today)
        code_created = pk_obj.code
    except Exception as e:
        report.record_finding(
            domain='履约取餐码',
            severity='CRITICAL',
            title='取餐码跨日生成抛出唯一键冲突异常',
            details=f'在历史已存在 0001 取餐码的情况下，新一天的订单调用 create_pickup_code 发生致命错误: {e}',
            code_location='notifications/services.py#create_pickup_code'
        )

    if code_created:
        if code_created == '0002':
            report.record_finding(
                domain='履约取餐码',
                severity='HIGH',
                title='取餐码跨日无法归零，受全局 unique 约束被迫顺延跳号',
                details=(
                    f"设计预期为每日从 0001 重新递增发号。但由于 PickupCode.code 在整张表上加了 unique=True，"
                    f"今日第 1 笔订单因历史存在 0001，被迫跳号生成为 '{code_created}'。"
                    f"累积订单超过 9999 时将发生位宽溢出或碰撞崩溃！"
                ),
                code_location='notifications/models.py#L160 & services.py#L259'
            )
        else:
            report.record_pass('履约取餐码', f'今日首单生成取餐码: {code_created}')

    # 2. 检验并发生成取餐码
    def _create_pickup(idx):
        ord_sub = OrderMain.objects.create(
            user=user, store=store, device=device,
            total_amount=1000, pay_amount=1000, status=OrderMain.STATUS_PAID,
            paid_at=timezone.now()
        )
        try:
            return create_pickup_code(ord_sub).code
        except Exception as err:
            return f"ERR: {err}"

    concurrent_codes = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = [ex.submit(_create_pickup, i) for i in range(5)]
        for f in as_completed(futs):
            concurrent_codes.append(f.result())

    errors = [c for c in concurrent_codes if str(c).startswith('ERR:')]
    if errors:
        report.record_finding(
            domain='履约取餐码',
            severity='HIGH',
            title='并发生成取餐码发生竞争异常',
            details=f'并发生成取餐码时发生碰撞或异常: {errors}',
            code_location='notifications/services.py#create_pickup_code'
        )
    else:
        report.record_pass('履约取餐码', f'并发成功生成 5 个取餐码: {concurrent_codes}')


# ============================================================================
# 领域 5: 制作中退款时序与硬件 MQTT Cancel 响应对抗
# ============================================================================
def test_domain_hardware_cancel_ack_race(ctx):
    print("▶ 正在检验 [领域 5: 制作中退款时序与硬件 MQTT Cancel 响应对抗]...")
    user = ctx['user_a']
    store = ctx['store']
    device = ctx['device']

    from payments.services import refund_order
    r = get_redis_connection('default')

    # Case 1: 上位机应答拒绝停机 (如正在注液) -> 云端退款必须被驳回
    ord_making = OrderMain.objects.create(
        user=user, store=store, device=device,
        total_amount=1800, pay_amount=1800, status=OrderMain.STATUS_MAKING
    )
    PaymentRecord.objects.create(
        out_trade_no=ord_making.order_no,
        order=ord_making,
        user=user,
        amount=1800,
        status=PaymentRecord.STATUS_SUCCESS,
        transaction_id=f"mock_tx_making_{ord_making.order_no}"
    )

    # 预注入上位机拒退 ACK (后台线程持续写入，对抗 issue_cancel_command_with_ack 内部的 delete)
    ack_key = f"automake:cancel_ack:{ord_making.order_no}"
    def _responder_refuse():
        for _ in range(25):
            time.sleep(0.15)
            r.set(ack_key, json.dumps({
                'type': 'cancel_ack',
                'status': 'refuse',
                'order_no': ord_making.order_no,
                'reason': '机械臂已注液，无法取消'
            }), ex=10)
    threading.Thread(target=_responder_refuse, daemon=True).start()

    refund_refused = False
    try:
        refund_order(ord_making, reason='用户申请取消', skip_device_cancel=False)
    except ValueError as e:
        if '拒绝退款' in str(e) or '无法取消' in str(e) or '拒绝' in str(e):
            refund_refused = True

    ord_making.refresh_from_db()
    if refund_refused and ord_making.status == OrderMain.STATUS_MAKING:
        report.record_pass('硬件协同', '上位机拒绝停机时，云端退款被成功拦截，订单保持 MAKING 状态')
    else:
        report.record_finding(
            domain='软硬件协同',
            severity='CRITICAL',
            title='上位机拒绝停机时云端仍退款成功 (既退款又出杯漏洞)',
            details=f'上位机已明确回传拒绝取消，但 refund_order 未能阻断退款流程！当前订单状态: {ord_making.status}',
            code_location='payments/services.py#refund_order'
        )

    # Case 2: 上位机应答同意停机 (status: ok) -> 退款成功流转为 REFUNDED
    ord_cancel_ok = OrderMain.objects.create(
        user=user, store=store, device=device,
        total_amount=1800, pay_amount=1800, status=OrderMain.STATUS_MAKING
    )
    PaymentRecord.objects.create(
        out_trade_no=ord_cancel_ok.order_no,
        order=ord_cancel_ok,
        user=user,
        amount=1800,
        status=PaymentRecord.STATUS_SUCCESS,
        transaction_id=f"mock_tx_ok_{ord_cancel_ok.order_no}"
    )

    ack_ok_key = f"automake:cancel_ack:{ord_cancel_ok.order_no}"
    def _responder_ok():
        for _ in range(25):
            time.sleep(0.15)
            r.set(ack_ok_key, json.dumps({
                'type': 'cancel_ack',
                'status': 'ok',
                'order_no': ord_cancel_ok.order_no
            }), ex=10)
    threading.Thread(target=_responder_ok, daemon=True).start()

    try:
        refund_order(ord_cancel_ok, reason='测试退款停机成功', skip_device_cancel=False)
        ord_cancel_ok.refresh_from_db()
        if ord_cancel_ok.status == OrderMain.STATUS_REFUNDED:
            report.record_pass('硬件协同', '上位机同意取消后，退款成功闭环且状态流转为 REFUNDED')
        else:
            report.record_finding(
                domain='软硬件协同',
                severity='MEDIUM',
                title='上位机同意取消后退款状态未更新',
                details=f'上位机已同意停机，但订单状态未变为 REFUNDED，当前状态: {ord_cancel_ok.status}',
                code_location='payments/services.py#refund_order'
            )
    except Exception as e:
        report.record_finding(
            domain='软硬件协同',
            severity='HIGH',
            title='上位机同意停机场景下退款失败',
            details=f'上位机已返回 ok，退款时抛出异常: {e}',
            code_location='payments/services.py#refund_order'
        )


# ============================================================================
# 领域 6: 耗材双写与 Redis 存储单位审计
# ============================================================================
def test_domain_consumable_unit_audit(ctx):
    print("▶ 正在检验 [领域 6: 耗材双写与 Redis 存储单位审计]...")
    device = ctx['device']
    staff_user = ctx['staff_user']
    r = get_redis_connection('default')

    from devices.staff_views import StaffConsumableUpdateView
    factory = APIRequestFactory()
    view_consumable = StaffConsumableUpdateView.as_view()

    # 录入 50 个大纸杯
    req = factory.post(
        '/api/staff/consumables/update',
        data={'device_sn': device.device_sn, 'items': [{'code': 'paperL', 'quantity': 50}]},
        format='json'
    )
    force_authenticate(req, user=staff_user)
    view_consumable(req)

    # 检查 MySQL
    cs = DeviceConsumableStock.objects.get(device=device, code__code='paperL')
    mysql_qty = cs.quantity

    # 检查 Redis 键值
    redis_key = f"automake:stock:{device.device_sn}:paperL"
    redis_val = r.get(redis_key)
    redis_qty = int(redis_val) if redis_val else None

    if redis_qty == 5000 and mysql_qty == 50:
        report.record_finding(
            domain='单位一致性与防超卖',
            severity='HIGH',
            title='物料员录入耗材时 Redis 数量被错误放大 100 倍',
            details=(
                f"物料员录入 50 个纸杯，MySQL 中为 50，但 Redis 中因代码写成 `quantity * 100` "
                f"导致被写入为 {redis_qty}！这会导致基于 Redis 余量的预扣/校验出现 100 倍严重虚标！"
            ),
            code_location='devices/staff_views.py#L164'
        )
    elif redis_qty == 50 and mysql_qty == 50:
        report.record_pass('单位一致性', '耗材在 MySQL 与 Redis 中的单位及数值严格一致 (50 == 50)')
    else:
        report.record_finding(
            domain='单位一致性',
            severity='MEDIUM',
            title='耗材写入 Redis 与 MySQL 数值不匹配',
            details=f'MySQL={mysql_qty}, Redis={redis_qty}',
            code_location='devices/staff_views.py#StaffConsumableUpdateView'
        )


# ============================================================================
# 领域 7: 优惠券与积分扣减闭环核查
# ============================================================================
def test_domain_coupon_and_points_integration(ctx):
    print("▶ 正在检验 [领域 7: 优惠券与积分扣减闭环核查]...")
    user = ctx['user_a']
    store = ctx['store']
    device = ctx['device']
    menu_item = ctx['menu_item']

    from orders.models import UserCoupon
    from orders.services import precheck_order, create_order

    # 用户持有一张满减券
    coupon = UserCoupon.objects.create(
        user=user,
        title='测试立减 5 元券',
        coupon_type=UserCoupon.TYPE_DIRECT,
        amount=500, # 500分
        min_spend=0,
        expires_at=timezone.now() + timedelta(days=7),
        status=UserCoupon.STATUS_AVAILABLE
    )

    items_data = [{'item': menu_item.id, 'sku': [], 'quantity': 1}]

    # 尝试在预检或下单中传入 coupon_id
    checked = precheck_order(store.id, items_data, device_sn=device.device_sn, coupon_id=coupon.id)
    ord_obj = create_order(user, store.id, items_data, device_sn=device.device_sn, coupon_id=coupon.id)

    if ord_obj.discount_amount == 0 and ord_obj.pay_amount == ord_obj.total_amount:
        coupon.refresh_from_db()
        if coupon.status == UserCoupon.STATUS_AVAILABLE and coupon.used_order is None:
            report.record_finding(
                domain='营销资产闭环',
                severity='MEDIUM',
                title='优惠券未实际参与订单价格计算与核销 (功能未闭环)',
                details=(
                    f"用户持有 5 元优惠券并传入下单，但订单 discount_amount 仍为 0，pay_amount 等于原价 {ord_obj.total_amount}，"
                    f"且 UserCoupon 状态保持未核销。优惠券功能在下单链路上处于未接通状态。"
                ),
                code_location='orders/services.py#create_order'
            )
    else:
        report.record_pass('营销资产闭环', '优惠券成功抵扣并核销')


# ============================================================================
# 领域 8: 耗材防二次扣减持久化完整性审计
# ============================================================================
def test_domain_stock_deduction_persistence(ctx):
    print("▶ 正在检验 [领域 8: 耗材防二次扣减对 Redis 的易失性依赖]...")
    user = ctx['user_a']
    store = ctx['store']
    device = ctx['device']
    menu_item = ctx['menu_item']

    from orders.services import create_order, update_order_status
    from payments.services import confirm_payment_success
    r = get_redis_connection('default')

    # 1. 创建订单并完成支付
    items_data = [{'item': menu_item.id, 'sku': [], 'quantity': 1}]
    order = create_order(user, store.id, items_data, device_sn=device.device_sn)
    PaymentRecord.objects.create(
        out_trade_no=order.order_no,
        order=order,
        user=user,
        amount=order.pay_amount,
        status=PaymentRecord.STATUS_PENDING
    )
    confirm_payment_success(
        out_trade_no=order.order_no,
        transaction_id=f"mock_tx_persist_{order.order_no}",
        paid_amount_fen=order.pay_amount
    )

    cs_paper = DeviceConsumableStock.objects.get(device=device, code__code='paperL')
    qty_after_pay = cs_paper.quantity

    # 2. 模拟 Redis 发生重启 / 键淘汰 (Key 被逐出)
    r.delete(f"automake:order_stock_deducted:{order.order_no}")

    # 3. 硬件上报制作完成 (done)，触发 update_order_status(..., STATUS_DONE)
    update_order_status(
        order=order,
        new_status=OrderMain.STATUS_DONE,
        operator='device_test',
        remark='出货完成'
    )

    cs_paper.refresh_from_db()
    qty_after_done = cs_paper.quantity

    if qty_after_done < qty_after_pay:
        report.record_finding(
            domain='物料守恒与防二次扣减',
            severity='HIGH',
            title='Redis 键淘汰导致订单在出杯完成时发生耗材二次扣减',
            details=(
                f"由于防二次扣减标记仅依赖 `automake:order_stock_deducted:{order.order_no}` 这一 Redis 键，"
                f"在 Redis 重启或键过期后，订单状态流转至 DONE 时再次执行 deduct_order_consumables，"
                f"导致纸杯被重复多扣了一次！(原剩余={qty_after_pay}, 现剩余={qty_after_done})"
            ),
            code_location='orders/services.py#L758'
        )
    else:
        report.record_pass('物料守恒', 'Redis 键丢失场景下耗材未发生二次扣减')


def run_all_tests():
    print("="*80)
    print("         启动 AutoMake 全系统业务逻辑与不变量混沌模糊测试")
    print("="*80)
    ctx = setup_test_fixtures()

    test_domain_state_machine_integrity(ctx)
    test_domain_payment_idempotency_and_concurrency(ctx)
    test_domain_security_privilege_escalation(ctx)
    test_domain_pickup_code_lifecycle(ctx)
    test_domain_hardware_cancel_ack_race(ctx)
    test_domain_consumable_unit_audit(ctx)
    test_domain_coupon_and_points_integration(ctx)
    test_domain_stock_deduction_persistence(ctx)

    report.print_summary()


if __name__ == '__main__':
    run_all_tests()
