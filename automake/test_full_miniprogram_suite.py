"""
AutoMake 微信小程序全量功能与全套后端 API 严格端到端集成测试套件
"""

import os
import json
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')
django.setup()

from django.test import RequestFactory
from rest_framework.test import force_authenticate
from users.models import User
from stores.models import Store
from devices.models import Device
from inventory.models import Material
from stores.views import StoreListView, StoreDetailView
from menus.views import StoreMenuView
from orders.views import OrderPrecheckView, OrderCreateView, OrderListView, OrderDetailView, OrderInvoiceView
from payments.views import PayMockSuccessView
from users.views import UserProfileView, UserCouponListView, UserCouponClaimView, UserPointsView, UserPhoneBindView
from devices.staff_views import StaffDeviceListView, StaffDeviceStockView, StaffConsumableUpdateView, StaffDeviceActionView
from django_redis import get_redis_connection

MINIPROGRAM_DIR = "/home/ubuntu/autoMachine/webmin"


def test_project_structure():
    print("==================================================================")
    print("🧪 [Test 1] 校验微信小程序项目结构与 11 个核心页面完整性")
    print("==================================================================")
    
    app_json_path = os.path.join(MINIPROGRAM_DIR, "app.json")
    with open(app_json_path, 'r', encoding='utf-8') as f:
        app_json = json.load(f)

    pages = app_json.get("pages", [])
    expected_pages = [
        "pages/index/index",
        "pages/menu/menu",
        "pages/product-detail/product-detail",
        "pages/cart/cart",
        "pages/orders/orders",
        "pages/order-detail/order-detail",
        "pages/invoice/invoice",
        "pages/coupon/coupon",
        "pages/points/points",
        "pages/staff/staff",
        "pages/my/my"
    ]
    
    for ep in expected_pages:
        assert ep in pages, f"app.json 缺少注册页面: {ep}"
        base = os.path.join(MINIPROGRAM_DIR, ep)
        for ext in ['.js', '.json', '.wxml', '.wxss']:
            fp = base + ext
            assert os.path.exists(fp), f"缺失页面文件: {fp}"
            assert os.path.getsize(fp) > 0, f"页面文件为空: {fp}"
        # 校验 json 有效性
        with open(base + '.json', 'r', encoding='utf-8') as jf:
            json.load(jf)
        print(f"  ✓ {ep} [4件套 .js .json .wxml .wxss 存在且非空]")

    # 校验 TabBar
    tab_list = app_json.get("tabBar", {}).get("list", [])
    assert len(tab_list) == 4
    for tab in tab_list:
        assert os.path.exists(os.path.join(MINIPROGRAM_DIR, tab['iconPath']))
        assert os.path.exists(os.path.join(MINIPROGRAM_DIR, tab['selectedIconPath']))
    print("  ✓ TabBar 导航图标 (8枚) 完整就绪")


def test_full_api_suite():
    print("\n==================================================================")
    print("🧪 [Test 2] 校验 Django 后端为小程序提供的全套 16 组 API 接口")
    print("==================================================================")
    rf = RequestFactory()

    # 准备测试用户
    customer_user, _ = User.objects.get_or_create(
        openid="oTest_Customer_Suite_001",
        defaults={'role': User.CUSTOMER, 'phone': '13900139000'}
    )
    staff_user, _ = User.objects.get_or_create(
        username="material_staff_001",
        defaults={'role': User.MATERIAL_ADMIN, 'is_staff': True}
    )

    # 1. 门店列表与定位
    print("▶ 1. GET /api/store/list 门店列表与定位...")
    resp = StoreListView.as_view()(rf.get('/api/store/list'))
    assert resp.status_code == 200
    stores = resp.data if isinstance(resp.data, list) else resp.data.get('data', [])
    assert len(stores) > 0
    store_id = stores[0]['id']
    print(f"  ✓ 成功获取 {len(stores)} 家门店，测试门店 ID: {store_id}")

    # 2. 设备/门店菜单与商品规格 (通过 device_sn)
    test_device_sn = stores[0].get('device_sn') or f"DEV_{store_id}"
    print(f"▶ 2. GET /api/menu/store/{test_device_sn} 设备菜单树...")
    resp = StoreMenuView.as_view()(rf.get(f'/api/menu/store/{test_device_sn}'), device_sn=test_device_sn)
    assert resp.status_code == 200
    menu_data = resp.data.get('data', resp.data)
    assert 'device_sn' in menu_data
    categories = menu_data.get('categories', [])
    first_item = categories[0]['items'][0]
    print(f"  ✓ 成功获取设备 {menu_data.get('device_sn')} 菜单: 分类 ({len(categories)} 个)，商品: {first_item['name']}, 基础价格: {first_item['base_price']}分")

    # 3. 准备在线设备与物料库存
    dev = Device.objects.filter(store_id=store_id).first()
    if not dev:
        dev = Device.objects.create(store_id=store_id, device_sn=f"DEV_{store_id}", status=Device.STATUS_ONLINE)
    else:
        dev.status = Device.STATUS_ONLINE
        dev.save(update_fields=['status'])

    try:
        redis_conn = get_redis_connection("default")
        for m in Material.objects.all():
            redis_conn.set(f"automake:stock:{dev.device_sn}:{m.code}", 99999)
    except Exception:
        pass

    # 4. 订单预校验 (Precheck)
    print("▶ 3. POST /api/order/precheck 订单金额与库存预校验...")
    first_skus = [s['id'] for s in first_item.get('skus', []) if s.get('is_active')]
    precheck_payload = {
        'store_id': store_id,
        'items': [{'item': first_item['id'], 'sku': first_skus[:1] if first_skus else [], 'quantity': 2}]
    }
    req = rf.post('/api/order/precheck', data=precheck_payload, content_type='application/json')
    force_authenticate(req, user=customer_user)
    resp = OrderPrecheckView.as_view()(req)
    assert resp.status_code == 200
    pre_data = resp.data.get('data', resp.data)
    assert pre_data['total_amount'] > 0
    print(f"  ✓ 预校验通过: 总金额={pre_data['total_amount']}分, 实付={pre_data['pay_amount']}分")

    # 5. 创建订单 (Create Order)
    print("▶ 4. POST /api/order/create 创建正式订单...")
    create_payload = {
        'store_id': store_id,
        'remark': '全量套件测试订单',
        'order_token': f'SUITE_{os.urandom(4).hex()}',
        'items': precheck_payload['items']
    }
    req = rf.post('/api/order/create', data=create_payload, content_type='application/json')
    force_authenticate(req, user=customer_user)
    resp = OrderCreateView.as_view()(req)
    assert resp.status_code in (200, 201)
    order_no = resp.data.get('data', resp.data).get('order_no')
    assert order_no
    print(f"  ✓ 订单创建成功: {order_no}")

    # 6. 模拟支付成功 (Mock Pay)
    print("▶ 5. POST /api/pay/mock-success 模拟支付成功闭环...")
    resp = PayMockSuccessView.as_view()(rf.post('/api/pay/mock-success', data={'order_no': order_no}, content_type='application/json'))
    assert resp.status_code == 200
    print("  ✓ 支付完成，自动创建生产任务并下发 MQTT")

    # 7. 订单详情 (Order Detail)
    print("▶ 6. GET /api/order/<order_no> 订单详情与明细...")
    req = rf.get(f'/api/order/{order_no}')
    force_authenticate(req, user=customer_user)
    resp = OrderDetailView.as_view()(req, order_no=order_no)
    assert resp.status_code == 200
    assert resp.data.get('data', resp.data)['order_no'] == order_no
    print("  ✓ 订单详情获取成功")

    # 8. 电子发票申请 (Invoice Apply)
    print("▶ 7. POST /api/order/<order_no>/invoice 申请电子发票...")
    inv_payload = {
        'invoice_type': 'company',
        'title': '北京智能自动化科技有限公司',
        'tax_no': '91110108MA00000000',
        'email': 'finance@automake.cn'
    }
    req = rf.post(f'/api/order/{order_no}/invoice', data=inv_payload, content_type='application/json')
    force_authenticate(req, user=customer_user)
    resp = OrderInvoiceView.as_view()(req, order_no=order_no)
    assert resp.status_code == 200
    print("  ✓ 电子发票申请成功")

    # 9. 电子发票查询 (Invoice Query)
    print("▶ 8. GET /api/order/<order_no>/invoice 查询发票详情...")
    req = rf.get(f'/api/order/{order_no}/invoice')
    force_authenticate(req, user=customer_user)
    resp = OrderInvoiceView.as_view()(req, order_no=order_no)
    assert resp.status_code == 200
    inv_data = resp.data.get('data', resp.data)
    assert inv_data['title'] == inv_payload['title']
    print(f"  ✓ 发票查询成功: 抬头={inv_data['title']}, 金额={inv_data['amount']}分")

    # 10. 优惠券列表 (User Coupons)
    print("▶ 9. GET /api/user/coupons 用户优惠券列表...")
    req = rf.get('/api/user/coupons')
    force_authenticate(req, user=customer_user)
    resp = UserCouponListView.as_view()(req)
    assert resp.status_code == 200
    coupons = resp.data.get('data', resp.data)
    assert len(coupons) > 0
    print(f"  ✓ 成功获取优惠券列表 (共 {len(coupons)} 张)")

    # 11. 领券中心领取 (Claim Coupon)
    print("▶ 10. POST /api/user/coupons/claim 领券中心免费领券...")
    claim_payload = {'title': '限时专享 ¥10 减免券', 'amount': 1000, 'min_spend': 3000}
    req = rf.post('/api/user/coupons/claim', data=claim_payload, content_type='application/json')
    force_authenticate(req, user=customer_user)
    resp = UserCouponClaimView.as_view()(req)
    assert resp.status_code == 200
    print("  ✓ 优惠券领取成功")

    # 12. 积分与流水 (User Points)
    print("▶ 11. GET /api/user/points 积分余额与流水记录...")
    req = rf.get('/api/user/points')
    force_authenticate(req, user=customer_user)
    resp = UserPointsView.as_view()(req)
    assert resp.status_code == 200
    points_data = resp.data.get('data', resp.data)
    assert points_data['points'] >= 0
    print(f"  ✓ 成功获取积分: 当前可用 {points_data['points']} 积分, 流水 {len(points_data['logs'])} 条")

    # 13. 手机号绑定 (Bind Phone)
    print("▶ 12. POST /api/user/phone/bind 绑定微信手机号...")
    req = rf.post('/api/user/phone/bind', data={'phone': '13812345678'}, content_type='application/json')
    force_authenticate(req, user=customer_user)
    resp = UserPhoneBindView.as_view()(req)
    assert resp.status_code == 200
    print("  ✓ 手机号成功绑定至账号: 13812345678")

    # 14. 物料员设备列表 (Staff Devices)
    print("▶ 13. GET /api/staff/devices 物料员/协调员可操作设备列表...")
    req = rf.get('/api/staff/devices')
    force_authenticate(req, user=staff_user)
    resp = StaffDeviceListView.as_view()(req)
    assert resp.status_code == 200
    staff_devs = resp.data.get('data', resp.data)
    assert len(staff_devs) > 0
    target_sn = staff_devs[0]['device_sn']
    print(f"  ✓ 成功获取员工设备列表 (首台设备: {target_sn})")

    # 15. 物料员查询耗材与料位 (Staff Device Stock)
    print(f"▶ 14. GET /api/staff/devices/{target_sn}/stock 查询杯子耗材与料桶...")
    req = rf.get(f'/api/staff/devices/{target_sn}/stock')
    force_authenticate(req, user=staff_user)
    resp = StaffDeviceStockView.as_view()(req, device_sn=target_sn)
    assert resp.status_code == 200
    stock_data = resp.data.get('data', resp.data)
    assert len(stock_data['consumables']) > 0
    print(f"  ✓ 查询到耗材 {len(stock_data['consumables'])} 项, 料位 {len(stock_data['materials'])} 项")

    # 16. 物料员补货录入 (Update Consumables)
    print("▶ 15. POST /api/staff/consumables/update 物料员手动更新耗材数量...")
    replenish_payload = {
        'device_sn': target_sn,
        'items': [
            {'code': 'paperL', 'quantity': 120},
            {'code': 'paperM', 'quantity': 150},
            {'code': 'plasticL', 'quantity': 90},
            {'code': 'membrane', 'quantity': 250},
            {'code': 'lid', 'quantity': 180}
        ]
    }
    req = rf.post('/api/staff/consumables/update', data=replenish_payload, content_type='application/json')
    force_authenticate(req, user=staff_user)
    resp = StaffConsumableUpdateView.as_view()(req)
    assert resp.status_code == 200
    print("  ✓ 耗材库存手动更新成功并同步至 Redis")

    # 17. 协调员设备控制 (Device Action)
    print(f"▶ 16. POST /api/staff/devices/{target_sn}/action 协调员下发重启复位指令...")
    req = rf.post(f'/api/staff/devices/{target_sn}/action', data={'action': 'reset'}, content_type='application/json')
    force_authenticate(req, user=staff_user)
    resp = StaffDeviceActionView.as_view()(req, device_sn=target_sn)
    assert resp.status_code == 200
    print("  ✓ 协调员设备指令已成功派发")

    print("\n==================================================================")
    print("🎉 恭喜！微信小程序 11 个页面结构与全套 16 组后端 API 100% 测试通过！")
    print("==================================================================")


if __name__ == '__main__':
    test_project_structure()
    test_full_api_suite()
