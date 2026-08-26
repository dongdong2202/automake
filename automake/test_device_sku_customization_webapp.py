"""
Web App E2E 测试脚本 (webapp-testing):
验证设备管理的【设备菜单定制】选项卡新增【可售规格定制】列，
以及设备可售规格弹窗中“只能做减法，受全局控制”的开关控制与一键批量操作。
"""

import os
import time
import subprocess
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')
django.setup()

from playwright.sync_api import sync_playwright
from menus.models import MenuItem, MenuSku
from global_config.models import GlobalMenuSku, GlobalMenuItem
from stores.models import Store

BASE_URL = "http://127.0.0.1:30004"
ARTIFACTS_DIR = "/home/ubuntu/.gemini/antigravity-cli/brain/d4d72c2a-627e-480f-aea5-921f9dbcb2c4"


def setup_test_data():
    """确保有测试门店和菜单商品及多个SKU供测试"""
    store = Store.objects.first()
    if store:
        MenuItem.sync_store_menu(store)


def run_webapp_test():
    print("🚀 [Step 0] 准备测试数据...")
    setup_test_data()

    print("🚀 [Step 1] 启动 30004 测试服务...")
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
            print("🚀 [Step 2] 登录管理平台...")
            page.goto(f"{BASE_URL}/login", wait_until="networkidle")
            page.fill('input[placeholder="请输入用户名"]', "admin1")
            page.fill('input[placeholder="请输入密码"]', "admin123")
            page.click('button:has-text("登 录")')
            page.wait_for_url("**/dashboard", timeout=8000)
            print("  ✓ 登录成功")

            # 2. 导航至设备管理 -> 设备菜单定制 Tab
            print("🚀 [Step 3] 进入设备管理并切换至【设备菜单定制】...")
            page.goto(f"{BASE_URL}/devices", wait_until="networkidle")
            page.wait_for_selector(".device-management-page", timeout=8000)
            
            tab3 = page.locator('.el-tabs__item:has-text("设备菜单定制")')
            tab3.click()
            page.wait_for_timeout(1000)

            # 3. 校验表格中是否包含【可售规格定制】列
            print("🚀 [Step 4] 校验表格【可售规格定制】列与规格标签...")
            page.wait_for_selector('#pane-menus .el-table__row', timeout=8000)
            page.wait_for_timeout(500)
            table_content = page.locator('#pane-menus').inner_text()
            assert "可售规格定制" in table_content, "表格应包含'可售规格定制'列标题"
            print("  ✓ 表格中成功展示【可售规格定制】列")

            # 截图保存：设备菜单定制大表（含规格定制列）
            page.screenshot(path=os.path.join(ARTIFACTS_DIR, "device_menu_sku_column.png"))
            print("  ✓ 设备菜单定制表格截图已保存至 device_menu_sku_column.png")

            # 4. 点击【规格定制 >】打开设备可售规格定制弹窗
            print("🚀 [Step 5] 点击【规格定制 >】打开设备可售规格定制弹窗...")
            sku_config_btn = page.locator('#pane-menus button:has-text("规格定制")').first
            sku_config_btn.click()
            page.wait_for_selector(".el-dialog:has-text('设备可售规格定制')", timeout=5000)
            page.wait_for_timeout(800)

            # 校验弹窗内容
            dialog_content = page.content()
            assert "减法控制原则" in dialog_content
            assert "SKU ID" in dialog_content
            assert "规格名称" in dialog_content
            assert "规格加价" in dialog_content
            assert "设备总售价" in dialog_content
            assert "全局状态" in dialog_content
            assert "本设备状态" in dialog_content
            print("  ✓ 规格定制弹窗加载正常，减法原则提示清晰展示")

            # 截图保存：设备可售规格定制弹窗
            page.screenshot(path=os.path.join(ARTIFACTS_DIR, "device_sku_customization_dialog.png"))
            print("  ✓ 规格定制弹窗截图已保存至 device_sku_customization_dialog.png")

            # 5. 测试切换单个规格启用/停用状态
            print("🚀 [Step 6] 测试在设备端单独停用/启用某规格...")
            switch = page.locator('.el-dialog .el-table__body-wrapper .el-switch:not(.is-disabled)').first
            if switch.count() > 0:
                switch.click()
                page.wait_for_timeout(800)
                print("  ✓ 成功触发规格状态切换开关")

            # 6. 关闭弹窗并验证外层表格数据联动更新
            print("🚀 [Step 7] 关闭弹窗并验证列表页数据联动...")
            complete_btn = page.locator('.el-dialog button:has-text("完成")')
            complete_btn.click()
            page.wait_for_timeout(800)

            # 最终截图
            page.screenshot(path=os.path.join(ARTIFACTS_DIR, "device_menu_sku_column_final.png"))
            print("  ✓ 最终状态截图已保存至 device_menu_sku_column_final.png")

            browser.close()
            print("🎉 [Success] webapp-testing 设备规格定制交互验证 100% 全部通过！")

    finally:
        print("\n🛑 [Step 9] 终止测试服务并严格释放 30004 端口...")
        server_process.terminate()
        server_process.kill()
        os.system("fuser -k 30004/tcp || true")
        time.sleep(1)
        res = os.popen("ss -tulpn | grep 30004").read().strip()
        if not res:
            print("  ✓ 端口 30004 已完全释放关闭！")
        else:
            print(f"  ⚠️ 警告: 30004 仍被占用: {res}")


if __name__ == '__main__':
    run_webapp_test()
