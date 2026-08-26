"""
微信小程序静态工程完整性与 Django 后端联调自动化测试
"""

import os
import json
import subprocess
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')
django.setup()

from django.test import RequestFactory
from rest_framework.test import force_authenticate
from users.models import User
from stores.models import Store
from menus.models import MenuItem, MenuSku
from stores.views import StoreListView, StoreDetailView
from menus.views import StoreMenuView
from orders.views import OrderPrecheckView, OrderCreateView, OrderListView, OrderDetailView
from payments.views import PayMockSuccessView

MINIPROGRAM_DIR = "/home/ubuntu/autoMachine/webmin"


def test_miniprogram_project_integrity():
    print("🧪 [Test 1] 校验微信小程序项目配置与 JSON 文件完整性...")
    
    app_json_path = os.path.join(MINIPROGRAM_DIR, "app.json")
    with open(app_json_path, 'r', encoding='utf-8') as f:
        app_json = json.load(f)
    print("  ✓ app.json 解析成功")

    # 校验所有注册的页面文件是否存在 4 件套 (.js, .json, .wxml, .wxss)
    pages = app_json.get("pages", [])
    assert len(pages) >= 4, f"页面数量过少: {len(pages)}"
    
    for p in pages:
        base_path = os.path.join(MINIPROGRAM_DIR, p)
        for ext in ['.js', '.json', '.wxml', '.wxss']:
            file_path = base_path + ext
            assert os.path.exists(file_path), f"缺失页面文件: {file_path}"
        # 校验页面 json 合法性
        with open(base_path + '.json', 'r', encoding='utf-8') as f:
            json.load(f)
    print(f"  ✓ 全量 {len(pages)} 个页面四件套 (.js, .json, .wxml, .wxss) 完整且 JSON 格式有效")

    # 校验 TabBar 图标资源
    tab_list = app_json.get("tabBar", {}).get("list", [])
    assert len(tab_list) == 4, f"TabBar 项数量不为 4: {len(tab_list)}"
    for tab in tab_list:
        icon = os.path.join(MINIPROGRAM_DIR, tab.get("iconPath", ""))
        selected_icon = os.path.join(MINIPROGRAM_DIR, tab.get("selectedIconPath", ""))
        assert os.path.exists(icon), f"缺失 TabBar 图标: {icon}"
        assert os.path.exists(selected_icon), f"缺失 TabBar 选中图标: {selected_icon}"
    print("  ✓ TabBar 导航配置与 8 组状态图标文件全部就绪")

    # 校验 project.config.json
    proj_config_path = os.path.join(MINIPROGRAM_DIR, "project.config.json")
    with open(proj_config_path, 'r', encoding='utf-8') as f:
        proj_config = json.load(f)
    assert proj_config.get("compileType") == "miniprogram"
    print("  ✓ project.config.json 配置合法")


def test_miniprogram_backend_api_flow():
    print("\n🧪 [Test 2] 校验 Django 后端为小程序提供的核心业务闭环 API...")
    rf = RequestFactory()

    # 1. 创建或获取测试用户
    customer_user, _ = User.objects.get_or_create(
        openid="oTest_MiniProgram_User_001",
        defaults={'role': User.CUSTOMER, 'phone': '13800138000'}
    )

    # 2. 门店列表接口
    print("▶ [Step 1] 测试 /api/store/list 门店列表...")
    store_view = StoreListView.as_view()
    req = rf.get('/api/store/list')
    resp = store_view(req)
    assert resp.status_code == 200
    stores = resp.data if isinstance(resp.data, list) else resp.data.get('data', [])
    assert len(stores) > 0, "数据库中应至少有 1 家门店"
    test_store_id = stores[0]['id']
    print(f"  ✓ 成功获取门店列表 (首个门店 ID: {test_store_id}, 名称: {stores[0]['name']})")

    # 3. 门店菜单接口
    print(f"▶ [Step 2] 测试 /api/menu/store/{test_store_id} 门店菜单树...")
    menu_view = StoreMenuView.as_view()
    req = rf.get(f'/api/menu/store/{test_store_id}')
    resp = menu_view(req, store_id=test_store_id)
    assert resp.status_code == 200
    menu_data = resp.data.get('data', resp.data)
    categories = menu_data.get('categories', [])
    assert len(categories) > 0, "门店应包含菜单分类"
    first_item = None
    for cat in categories:
        if cat.get('items'):
            first_item = cat['items'][0]
            break
    assert first_item is not None, "分类下应包含商品"
    print(f"  ✓ 成功获取门店菜单 (分类数: {len(categories)}, 首个商品: {first_item['name']})")

    # 4. 准备在线设备与 Redis 虚拟库存保证下单测试
    from devices.models import Device
    from inventory.models import Material
    from django_redis import get_redis_connection

    dev = Device.objects.filter(store_id=test_store_id).first()
    if not dev:
        dev = Device.objects.create(
            store_id=test_store_id,
            device_sn=f"SN_TEST_{test_store_id}",
            status=Device.STATUS_ONLINE
        )
    else:
        dev.status = Device.STATUS_ONLINE
        dev.save(update_fields=['status'])

    # 填充所有物料的 Redis 虚拟库存
    try:
        redis_conn = get_redis_connection("default")
        for m in Material.objects.all():
            redis_conn.set(f"automake:stock:{dev.device_sn}:{m.code}", 99999)
    except Exception as e:
        print("  (Redis 库存填充提示:", e, ")")

    # 4. 订单预校验 (Precheck)
    print("▶ [Step 3] 测试 /api/order/precheck 下单前预校验与金额计算...")
    precheck_view = OrderPrecheckView.as_view()
    first_skus = [s['id'] for s in first_item.get('skus', []) if s.get('is_active')]
    precheck_payload = {
        'store_id': test_store_id,
        'items': [
            {
                'item': first_item['id'],
                'sku': first_skus[:1] if first_skus else [],
                'quantity': 1
            }
        ]
    }
    req = rf.post('/api/order/precheck', data=precheck_payload, content_type='application/json')
    force_authenticate(req, user=customer_user)
    resp = precheck_view(req)
    assert resp.status_code == 200
    precheck_data = resp.data.get('data', resp.data)
    print(f"  ✓ 预校验通过: 总金额={precheck_data.get('total_amount')}分, 实付={precheck_data.get('pay_amount')}分")

    # 5. 创建正式订单
    print("▶ [Step 4] 测试 /api/order/create 创建订单...")
    create_view = OrderCreateView.as_view()
    create_payload = {
        'store_id': test_store_id,
        'remark': '小程序自动化测试订单',
        'order_token': f'TEST_TOKEN_{os.urandom(4).hex()}',
        'items': precheck_payload['items']
    }
    req = rf.post('/api/order/create', data=create_payload, content_type='application/json')
    force_authenticate(req, user=customer_user)
    resp = create_view(req)
    assert resp.status_code in (200, 201)
    order_data = resp.data.get('data', resp.data)
    order_no = order_data.get('order_no')
    assert order_no, "应成功返回订单号"
    print(f"  ✓ 订单创建成功: 订单号={order_no}, 状态={order_data.get('status')}")

    # 6. 模拟支付成功 (联调出杯闭环)
    print(f"▶ [Step 5] 测试 /api/pay/mock-success 模拟支付成功...")
    mock_pay_view = PayMockSuccessView.as_view()
    req = rf.post('/api/pay/mock-success', data={'order_no': order_no}, content_type='application/json')
    resp = mock_pay_view(req)
    assert resp.status_code == 200
    print(f"  ✓ 模拟支付成功完成")

    # 7. 查看订单详情
    print(f"▶ [Step 6] 测试 /api/order/{order_no} 订单详情...")
    detail_view = OrderDetailView.as_view()
    req = rf.get(f'/api/order/{order_no}')
    force_authenticate(req, user=customer_user)
    resp = detail_view(req, order_no=order_no)
    assert resp.status_code == 200
    detail_data = resp.data.get('data', resp.data)
    print(f"  ✓ 订单详情获取成功: 当前状态={detail_data.get('status')}, 明细数={len(detail_data.get('items', []))}")

    print("\n=======================================================")
    print("🎉 微信小程序全链路后端 API 与项目完整性 100% 测试通过！")
    print("=======================================================")


if __name__ == '__main__':
    test_miniprogram_project_integrity()
    test_miniprogram_backend_api_flow()
