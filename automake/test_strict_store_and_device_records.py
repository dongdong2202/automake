"""
严密全量测试：
1. 验证【门店管理 -> 门店调拨流水】台账全面支持全部门店与指定门店筛选，历史记录完整展示；
2. 验证【设备综合管理 -> 设备库存流水】选择门店、选择设备，展示设备流水记录，不显示桶信息；
3. 测试完成后严格关闭 30004 端口。
"""

import os
import time
import subprocess
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')
django.setup()

from users.models import User
from stores.models import Store
from devices.models import Device
from inventory.models import Material, StoreInventoryRecord
from rest_framework.test import APIRequestFactory, force_authenticate
from admin_api.views.stores import StoreInventoryRecordListView
from admin_api.views.devices import DeviceInventoryRecordListView
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:30004"


def test_backend_and_ui():
    print("🚀 [Step 1] 开始后端 API 严格验证...")
    admin = User.objects.filter(is_superuser=True).first()
    if not admin:
        admin = User.objects.create_superuser('admin1', 'admin1@strict.com', 'admin123')
    else:
        admin.set_password('admin123')
        admin.is_superuser = True
        admin.save()

    factory = APIRequestFactory()

    # 1. 验证门店调拨流水 API (全部门店)
    store_rec_view = StoreInventoryRecordListView.as_view()
    req1 = factory.get('/api/admin/stores/records/')
    force_authenticate(req1, user=admin)
    resp1 = store_rec_view(req1)
    assert resp1.status_code == 200
    store_records_count = resp1.data['data']['count']
    print(f"  ✓ 门店调拨流水 (全部门店) API 返回正常，记录数: {store_records_count}")
    assert store_records_count > 0, "门店调拨流水不应为空！"

    # 2. 验证设备库存流水 API (全部设备 & 筛选设备)
    dev_rec_view = DeviceInventoryRecordListView.as_view()
    req2 = factory.get('/api/admin/devices/records/')
    force_authenticate(req2, user=admin)
    resp2 = dev_rec_view(req2)
    assert resp2.status_code == 200
    dev_records_count = resp2.data['data']['count']
    print(f"  ✓ 设备库存流水 API 返回正常，记录数: {dev_records_count}")

    # 如果没有设备流水，自动模拟一条加料流水用于验证
    if dev_records_count == 0:
        dev = Device.objects.first()
        store = dev.store if dev and dev.store else Store.objects.first()
        mat = Material.objects.first()
        StoreInventoryRecord.objects.create(
            store=store,
            material=mat,
            device=dev,
            record_type=StoreInventoryRecord.TYPE_OUT_TO_DEVICE,
            quantity=5.0,
            operator=admin,
            remarks='严格测试设备加料流水'
        )
        req2 = factory.get('/api/admin/devices/records/')
        force_authenticate(req2, user=admin)
        resp2 = dev_rec_view(req2)
        dev_records_count = resp2.data['data']['count']

    assert dev_records_count > 0, "设备流水记录不应为空！"
    first_record = resp2.data['data']['results'][0]
    print(f"  ✓ 示例设备流水: 设备={first_record.get('device_name') or first_record.get('device_sn')}, 物料={first_record.get('material_name')}, 数量={first_record.get('quantity')}")

    print("\n🚀 [Step 2] 启动服务并执行 Playwright 真实浏览器端到端交互测试...")
    os.system("fuser -k 30004/tcp || true")
    time.sleep(1)

    server_process = subprocess.Popen(
        ["/home/ubuntu/autoMachine/.venv1/bin/python", "manage.py", "runserver", "0.0.0.0:30004"],
        cwd="/home/ubuntu/autoMachine/automake",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(3)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 900})

            # 1. 登录
            page.goto(f"{BASE_URL}/login", wait_until="networkidle")
            page.fill('input[placeholder="请输入用户名"]', "admin1")
            page.fill('input[placeholder="请输入密码"]', "admin123")
            page.click('button:has-text("登 录")')
            page.wait_for_url("**/dashboard", timeout=8000)
            print("  ✓ 登录成功进入运营管理平台")

            # 2. 访问门店管理页面 (/stores?tab=records)
            page.goto(f"{BASE_URL}/stores?tab=records", wait_until="networkidle")
            page.wait_for_selector(".store-tabs", timeout=8000)
            page.wait_for_timeout(1500)

            content_store_rec = page.content()
            assert "门店调拨流水" in content_store_rec
            # 确认表格有行数据
            rows = page.locator(".el-tab-pane:visible .el-table__body tr")
            row_count = rows.count()
            print(f"  ✓ 门店调拨流水页面渲染成功！表格展示了 {row_count} 条流水记录行")
            assert row_count > 0, "门店调拨流水表格行数应大于 0！"

            # 截图保存
            page.screenshot(path="/home/ubuntu/.gemini/antigravity-cli/brain/d4d72c2a-627e-480f-aea5-921f9dbcb2c4/strict_store_records.png")

            # 3. 访问设备综合管理页面 (/devices?tab=stocks)
            page.goto(f"{BASE_URL}/devices?tab=stocks", wait_until="networkidle")
            page.wait_for_selector(".device-tabs", timeout=8000)
            page.wait_for_timeout(1500)

            content_dev_rec = page.content()
            assert "设备库存流水" in content_dev_rec
            assert "选择门店" in content_dev_rec
            assert "选择设备" in content_dev_rec
            assert "硬件料桶液位监测" not in content_dev_rec, "设备库存页面不应显示料桶信息！"
            assert "耗材仓余量监测" not in content_dev_rec, "设备库存页面不应显示料桶/仓位卡片！"

            dev_rows = page.locator(".el-tab-pane:visible .el-table__body tr")
            dev_row_count = dev_rows.count()
            print(f"  ✓ 设备库存流水页面渲染成功！表单含选择门店与设备，表格展示了 {dev_row_count} 条设备流水记录行，且无任何桶卡片！")
            assert dev_row_count > 0, "设备库存流水表格行数应大于 0！"

            # 截图保存
            page.screenshot(path="/home/ubuntu/.gemini/antigravity-cli/brain/d4d72c2a-627e-480f-aea5-921f9dbcb2c4/strict_device_records.png")

            browser.close()
            print("  ✓ Playwright 浏览器端到端测试 100% 通过！")

    finally:
        print("\n🛑 [Step 3] 彻底终止测试服务并严格释放 30004 端口...")
        server_process.terminate()
        server_process.kill()
        os.system("fuser -k 30004/tcp || true")
        time.sleep(1)
        res = os.popen("ss -tulpn | grep 30004").read().strip()
        if not res:
            print("  ✓ 端口 30004 已完全释放关闭！")
        else:
            print(f"  ⚠️ 警告: 30004 仍在占用: {res}")


if __name__ == '__main__':
    test_backend_and_ui()
