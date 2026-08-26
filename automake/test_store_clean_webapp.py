"""
Web App E2E 测试脚本 (webapp-testing):
验证【门店管理】(门店档案) 列表中已移除【注册码】和【经纬度】列，
且新建/编辑门店弹窗中亦不再显示注册码与经纬度输入项。
"""

import os
import time
import subprocess
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')
django.setup()

from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:30004"
ARTIFACTS_DIR = "/home/ubuntu/.gemini/antigravity-cli/brain/d4d72c2a-627e-480f-aea5-921f9dbcb2c4"


def run_webapp_test():
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

            # 2. 导航至门店管理页面
            print("🚀 [Step 3] 进入门店管理 (/stores)...")
            page.goto(f"{BASE_URL}/stores", wait_until="networkidle")
            page.wait_for_selector(".store-management-page", timeout=8000)
            page.wait_for_selector(".el-table__row", timeout=8000)
            page.wait_for_timeout(1000)

            # 3. 校验门店列表表格内容：确认无“注册码”和“经纬度”
            print("🚀 [Step 4] 校验门店档案表格列...")
            header_text = page.locator('.el-table__header-wrapper').first.inner_text()
            print(f"  当前表头内容: {header_text.replace(chr(10), ' | ')}")
            assert "注册码" not in header_text, "表头中不应出现'注册码'"
            assert "经纬度" not in header_text, "表头中不应出现'经纬度'"
            assert "Lat" not in header_text, "表头中不应出现'Lat'"
            assert "门店名称" in header_text, "表头中应包含'门店名称'"
            assert "详细地址" in header_text, "表头中应包含'详细地址'"
            assert "联系电话" in header_text, "表头中应包含'联系电话'"
            print("  ✓ 门店档案表格已成功移除【注册码】和【经纬度】列")

            # 截图保存：门店列表
            page.screenshot(path=os.path.join(ARTIFACTS_DIR, "store_list_table_cleaned.png"))
            print("  ✓ 门店列表截图已保存至 store_list_table_cleaned.png")

            # 4. 点击【新增门店】打开弹窗并校验表单项
            print("🚀 [Step 5] 打开门店新建/编辑弹窗校验表单项...")
            page.click('button:has-text("新增门店")')
            page.wait_for_selector(".el-dialog:has-text('新增门店')", timeout=5000)
            page.wait_for_timeout(800)

            dialog_content = page.locator('.el-dialog').inner_text()
            assert "注册码" not in dialog_content, "弹窗表单不应包含'注册码'"
            assert "经纬度" not in dialog_content, "弹窗表单不应包含'经纬度'"
            assert "纬度" not in dialog_content, "弹窗表单不应包含'纬度'"
            assert "经度" not in dialog_content, "弹窗表单不应包含'经度'"
            assert "门店名称" in dialog_content, "弹窗表单应包含'门店名称'"
            assert "联系电话" in dialog_content, "弹窗表单应包含'联系电话'"
            assert "详细地址" in dialog_content, "弹窗表单应包含'详细地址'"
            print("  ✓ 门店新建/编辑表单已成功移除【注册码】和【经纬度】输入项")

            # 截图保存：门店表单弹窗
            page.screenshot(path=os.path.join(ARTIFACTS_DIR, "store_edit_dialog_cleaned.png"))
            print("  ✓ 门店弹窗截图已保存至 store_edit_dialog_cleaned.png")

            page.click('.el-dialog button:has-text("取消")')
            page.wait_for_timeout(500)

            browser.close()
            print("🎉 [Success] webapp-testing 门店档案管理显示清理验证 100% 全部通过！")

    finally:
        print("\n🛑 [Step 6] 终止测试服务并严格释放 30004 端口...")
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
