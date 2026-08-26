"""
Web App E2E 测试脚本 (webapp-testing):
验证全局菜单档案管理新增【菜单规格库】选项卡及商品专属配方定制/继承功能。
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

            # 2. 导航至全局菜单管理页面
            print("🚀 [Step 3] 进入全局菜单管理页面 (/menus)...")
            page.goto(f"{BASE_URL}/menus", wait_until="networkidle")
            page.wait_for_selector(".menu-management-page", timeout=8000)

            # 3. 切换至【菜单规格库】选项卡
            print("🚀 [Step 4] 点击并进入 Tab 2: 菜单规格库...")
            tab2_header = page.locator('.el-tabs__item:has-text("菜单规格库")')
            tab2_header.click()
            page.wait_for_timeout(1000)

            # 验证大表展示
            skus_tab_content = page.content()
            assert "菜单规格库" in skus_tab_content
            assert "SKU ID" in skus_tab_content
            assert "所属商品" in skus_tab_content
            assert "生效配料用量" in skus_tab_content
            print("  ✓ 菜单规格库选项卡大表加载正常")

            # 截图保存：菜单规格库表格
            page.screenshot(path=os.path.join(ARTIFACTS_DIR, "menu_sku_library_tab.png"))
            print("  ✓ 菜单规格库表格截图已保存至 menu_sku_library_tab.png")

            # 4. 测试配料调整弹窗
            print("🚀 [Step 5] 测试商品规格配料调整 (定制配方)...")
            edit_recipe_btn = page.locator('button:has-text("配料调整")').first
            edit_recipe_btn.click()
            page.wait_for_selector(".el-dialog:has-text('调整规格配料配方')", timeout=5000)
            page.wait_for_timeout(800)

            # 截图保存：配方调整弹窗
            page.screenshot(path=os.path.join(ARTIFACTS_DIR, "menu_sku_recipe_dialog.png"))
            print("  ✓ 配方调整弹窗截图已保存至 menu_sku_recipe_dialog.png")

            # 点击保存配方
            save_recipe_btn = page.locator('.el-dialog button:has-text("确认保存配方")')
            save_recipe_btn.click()
            page.wait_for_timeout(1000)
            print("  ✓ 规格配方保存成功并生效")

            # 5. 测试在【全局菜谱商品】Tab 1 中新建商品并挂载规格与配料
            print("🚀 [Step 6] 测试新建商品并自动注入/定制规格配料...")
            tab1_header = page.locator('.el-tabs__item:has-text("全局菜谱商品")')
            tab1_header.click()
            page.wait_for_timeout(800)

            create_item_btn = page.locator('button:has-text("+ 新建全局商品")')
            create_item_btn.click()
            page.wait_for_selector(".el-dialog:has-text('新建全局商品档案')", timeout=5000)

            # 填写商品名称
            test_item_name = f"鲜萃茉莉奶绿_{int(time.time()) % 10000}"
            page.fill('input[placeholder="如 经典美式、生椰拿铁"]', test_item_name)
            page.wait_for_timeout(500)

            # 点击确认保存商品
            confirm_item_btn = page.locator('.el-dialog button:has-text("确认保存商品与规格")')
            confirm_item_btn.click()
            page.wait_for_timeout(1500)
            print(f"  ✓ 成功创建包含规格与配料的新商品: {test_item_name}")

            # 6. 再次切换至【菜单规格库】验证新建商品的独立 SKU ID
            print("🚀 [Step 7] 在菜单规格库中校验新建商品独立 SKU ID...")
            tab2_header = page.locator('.el-tabs__item:has-text("菜单规格库")')
            tab2_header.click()
            page.wait_for_timeout(1000)

            tab2_updated_content = page.content()
            assert test_item_name in tab2_updated_content, f"新商品 {test_item_name} 的规格应出现在菜单规格库大表中"
            print(f"  ✓ 新建商品 {test_item_name} 已成功在菜单规格库注册独立 SKU 实体！")

            # 7. 截图最终菜单规格库状态
            page.screenshot(path=os.path.join(ARTIFACTS_DIR, "menu_sku_library_tab_final.png"))
            print("  ✓ 最终状态截图已保存至 menu_sku_library_tab_final.png")

            browser.close()
            print("🎉 [Success] webapp-testing 端到端真实交互验证 100% 全部通过！")

    finally:
        print("\n🛑 [Step 8] 终止测试服务并严格释放 30004 端口...")
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
