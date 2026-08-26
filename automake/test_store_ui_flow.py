"""
Playwright 自动化 UI 测试：验证门店管理 3 大选项卡交互及设备传感器库存看板
并在运行结束前彻底关闭 30004 端口
"""

import os
import time
import subprocess
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')
django.setup()

from users.models import User
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:30004"


def run_ui_test():
    # 确保 30004 端口干净
    os.system("fuser -k 30004/tcp || true")
    time.sleep(1)

    print("🚀 启动 Django 后端测试服务 (Port: 30004)...")
    server_process = subprocess.Popen(
        ["/home/ubuntu/autoMachine/.venv1/bin/python", "manage.py", "runserver", "0.0.0.0:30004"],
        cwd="/home/ubuntu/autoMachine/automake",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(3)

    try:
        # 获取或创建 admin1
        admin = User.objects.filter(username='admin1').first()
        if not admin:
            admin = User.objects.create_superuser('admin1', 'admin1@ui.com', 'admin123')
        else:
            admin.set_password('admin123')
            admin.is_superuser = True
            admin.save()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 900})

            # 1. 登录
            print("  1. 登录运营管理平台...")
            page.goto(f"{BASE_URL}/login", wait_until="networkidle")
            page.fill('input[placeholder="请输入用户名"]', "admin1")
            page.fill('input[placeholder="请输入密码"]', "admin123")
            page.click('button:has-text("登 录")')
            page.wait_for_url("**/dashboard", timeout=8000)
            print("  ✓ 登录成功进入 Dashboard")

            # 2. 访问门店管理页面 (/stores)
            print("  2. 访问门店管理页面 (/stores)...")
            page.goto(f"{BASE_URL}/stores", wait_until="networkidle")
            page.wait_for_selector(".store-tabs", timeout=8000)

            content = page.content()
            assert "门店档案管理" in content
            assert "门店库存管理" in content
            assert "门店调拨流水" in content
            print("  ✓ 门店管理 3 大平行选项卡渲染成功！")

            # 截图 Tab 1
            os.makedirs("/home/ubuntu/.gemini/antigravity-cli/brain/d4d72c2a-627e-480f-aea5-921f9dbcb2c4", exist_ok=True)
            page.screenshot(path="/home/ubuntu/.gemini/antigravity-cli/brain/d4d72c2a-627e-480f-aea5-921f9dbcb2c4/store_management_tab1.png")

            # 3. 切换到 Tab 2【门店库存管理】
            print("  3. 切换到 Tab 2【门店库存管理】...")
            page.click("text=门店库存管理")
            page.wait_for_timeout(1500)
            content_tab2 = page.content()
            assert "当前在店库存" in content_tab2
            assert "出库到设备" in content_tab2 or "物料出库到设备" in content_tab2
            print("  ✓ 门店专属在店库存管理表格与出库加料入口展示正常！")
            page.screenshot(path="/home/ubuntu/.gemini/antigravity-cli/brain/d4d72c2a-627e-480f-aea5-921f9dbcb2c4/store_inventory_tab2.png")

            # 测试点击【+ 物料出库到设备】按钮打开弹窗
            dispatch_btn = page.locator('button:has-text("物料出库到设备")')
            if dispatch_btn.count() > 0:
                dispatch_btn.click()
                page.wait_for_selector('.el-dialog:has-text("物料出库加料到设备")', timeout=5000)
                print("  ✓ 【物料出库加料到设备】对话框弹窗成功打开！")
                page.screenshot(path="/home/ubuntu/.gemini/antigravity-cli/brain/d4d72c2a-627e-480f-aea5-921f9dbcb2c4/store_dispatch_dialog.png")
                page.click('.el-dialog:has-text("物料出库加料到设备") button:has-text("取消")')

            # 4. 切换到 Tab 3【门店调拨流水】
            print("  4. 切换到 Tab 3【门店调拨流水】...")
            page.click("text=门店调拨流水")
            page.wait_for_timeout(1500)
            content_tab3 = page.content()
            assert "总仓分拨入店" in content_tab3 or "出库加料到设备" in content_tab3
            print("  ✓ 门店三级调拨流水台账渲染正常！")
            page.screenshot(path="/home/ubuntu/.gemini/antigravity-cli/brain/d4d72c2a-627e-480f-aea5-921f9dbcb2c4/store_records_tab3.png")

            # 5. 访问设备综合管理【设备物料与耗材库存】(/devices?tab=stocks)
            print("  5. 访问设备综合管理【设备物料与耗材库存】(/devices?tab=stocks)...")
            page.goto(f"{BASE_URL}/devices?tab=stocks", wait_until="networkidle")
            page.wait_for_selector(".device-tabs", timeout=8000)
            page.wait_for_timeout(2000)
            content_dev = page.content()
            assert "硬件料桶液位监测" in content_dev
            assert "耗材仓余量监测" in content_dev
            print("  ✓ 设备物料与耗材传感器库存看板渲染正常！")
            page.screenshot(path="/home/ubuntu/.gemini/antigravity-cli/brain/d4d72c2a-627e-480f-aea5-921f9dbcb2c4/device_stocks_tab5.png")

            browser.close()
            print("  ✓ 浏览器测试全部通过并已关闭")

    finally:
        print("🛑 正在彻底终止测试服务并释放 30004 端口...")
        server_process.terminate()
        server_process.kill()
        os.system("fuser -k 30004/tcp || true")
        time.sleep(1)
        res = os.popen("ss -tulpn | grep 30004").read()
        if not res:
            print("  ✓ 端口 30004 已完全释放关闭！")
        else:
            print(f"  ⚠️ 警告: 30004 仍有占用: {res}")


if __name__ == '__main__':
    run_ui_test()
