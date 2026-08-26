"""
单元与权限规则测试：设备菜单规格定制与“只能做减法，受全局控制”业务约束验证
"""

import os
import django
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')
django.setup()

from django.test import RequestFactory
from rest_framework.test import force_authenticate
from users.models import User
from stores.models import Store
from devices.models import Device
from global_config.models import (
    DeviceModel, GlobalMenuCategory, GlobalMenuItem,
    GlobalSkuTemplate, GlobalMenuSku, GlobalSkuIngredient
)
from inventory.models import Material
from menus.models import MenuItem, MenuSku
from admin_api.views.menus import (
    StoreMenuItemListView, StoreMenuItemSkuListView,
    StoreMenuSkuDetailView
)


def run_unit_tests():
    print("🧪 开始执行【设备菜单规格定制与减法控制】全量业务逻辑测试...")

    # 1. 准备测试基底数据
    admin_user = User.objects.filter(is_superuser=True).first()
    if not admin_user:
        admin_user = User.objects.create_superuser('test_admin', 'admin@test.com', 'admin123')

    store = Store.objects.first()
    dev = Device.objects.filter(store=store).first()
    device_model = dev.device_model if dev else DeviceModel.objects.first()

    category = GlobalMenuCategory.objects.filter(device_model=device_model).first()
    if not category:
        category = GlobalMenuCategory.objects.create(name='测试分类', device_model=device_model)

    global_item, _ = GlobalMenuItem.objects.get_or_create(
        name='测试商品_减法控制',
        defaults={'category': category, 'base_price': 1500, 'is_active': True}
    )
    global_item.category = category
    global_item.is_active = True
    global_item.save()

    tpl_normal, _ = GlobalSkuTemplate.objects.get_or_create(name='标准杯_减法测试', defaults={'category': '杯型', 'default_price_delta': 0})
    tpl_large, _ = GlobalSkuTemplate.objects.get_or_create(name='超大杯_减法测试', defaults={'category': '杯型', 'default_price_delta': 300})

    # 全局规格 1：启用
    global_sku1, _ = GlobalMenuSku.objects.get_or_create(
        item=global_item, template=tpl_normal,
        defaults={'price_delta': 0, 'is_active': True}
    )
    global_sku1.is_active = True
    global_sku1.save()

    # 全局规格 2：停用 (测试全局控制)
    global_sku2, _ = GlobalMenuSku.objects.get_or_create(
        item=global_item, template=tpl_large,
        defaults={'price_delta': 300, 'is_active': False}
    )
    global_sku2.is_active = False
    global_sku2.save()

    # 同步到门店
    MenuItem.sync_store_menu(store)
    store_item = MenuItem.objects.get(store=store, global_item=global_item)
    store_sku1 = MenuSku.objects.get(item=store_item, global_sku=global_sku1)
    store_sku2 = MenuSku.objects.get(item=store_item, global_sku=global_sku2)

    rf = RequestFactory()

    # Case 1: 获取门店商品的SKU列表
    print("\n▶ [Case 1] 获取门店/设备商品的所有规格列表 (StoreMenuItemSkuListView)...")
    req = rf.get(f'/api/admin/menus/store-items/{store_item.id}/skus/')
    force_authenticate(req, user=admin_user)
    view = StoreMenuItemSkuListView.as_view()
    resp = view(req, item_id=store_item.id)
    assert resp.status_code == 200
    assert resp.data['code'] == 0
    skus_data = resp.data['data']
    assert len(skus_data) == 2
    print(f"  ✓ 成功获取 {len(skus_data)} 个规格项，字段完整返回")

    # Case 2: 本地做减法（开启 -> 关闭）
    print("\n▶ [Case 2] 测试全局启用规格在设备端做减法停用 (is_active: True -> False)...")
    req = rf.put(
        f'/api/admin/menus/store-skus/{store_sku1.id}/',
        data={'is_active': False},
        content_type='application/json'
    )
    force_authenticate(req, user=admin_user)
    view = StoreMenuSkuDetailView.as_view()
    resp = view(req, pk=store_sku1.id)
    assert resp.status_code == 200
    assert resp.data['code'] == 0
    store_sku1.refresh_from_db()
    assert store_sku1.is_active is False
    print("  ✓ 设备端成功做减法停用该规格")

    # Case 3: 本地在全局允许范围内恢复启用（关闭 -> 开启）
    print("\n▶ [Case 3] 测试在全局允许范围内设备端恢复启用 (is_active: False -> True)...")
    req = rf.put(
        f'/api/admin/menus/store-skus/{store_sku1.id}/',
        data={'is_active': True},
        content_type='application/json'
    )
    force_authenticate(req, user=admin_user)
    resp = view(req, pk=store_sku1.id)
    assert resp.status_code == 200
    assert resp.data['code'] == 0
    store_sku1.refresh_from_db()
    assert store_sku1.is_active is True
    print("  ✓ 设备端成功在全局允许范围内恢复启用")

    # Case 4: 严格减法限制 - 全局已停用的规格，设备端不可开启！
    print("\n▶ [Case 4] 核心约束测试：全局已停用的规格，设备端尝试开启必须被拒绝 (4003)...")
    req = rf.put(
        f'/api/admin/menus/store-skus/{store_sku2.id}/',
        data={'is_active': True},
        content_type='application/json'
    )
    force_authenticate(req, user=admin_user)
    resp = view(req, pk=store_sku2.id)
    assert resp.status_code == 400
    assert "全局已停用" in resp.data['message']
    store_sku2.refresh_from_db()
    assert store_sku2.is_active is False
    print(f"  ✓ 成功拦截非法开启请求: {resp.data['message']}")

    # Case 5: 严格减法限制 - 全局商品已下架时，设备端尝试开启规格必须被拒绝！
    print("\n▶ [Case 5] 核心约束测试：全局商品下架后，设备端尝试开启规格必须被拒绝 (4003)...")
    global_item.is_active = False
    global_item.save()
    global_sku1.is_active = True
    global_sku1.save()
    store_sku1.is_active = False
    store_sku1.save()

    req = rf.put(
        f'/api/admin/menus/store-skus/{store_sku1.id}/',
        data={'is_active': True},
        content_type='application/json'
    )
    force_authenticate(req, user=admin_user)
    resp = view(req, pk=store_sku1.id)
    print("Case 5 resp.data:", resp.data)
    assert resp.status_code == 400
    assert resp.data['code'] == 4003
    print(f"  ✓ 成功拦截商品下架时的开启请求: {resp.data['message']}")

    # 恢复全局商品上架
    global_item.is_active = True
    global_item.save()

    print("\n=======================================================")
    print("🎉 所有【设备菜单规格减法定制】测试用例 100% 验证通过！")
    print("=======================================================")


if __name__ == '__main__':
    run_unit_tests()
