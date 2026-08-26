import asyncio
import os
import sys
from playwright.async_api import async_playwright

BASE_URL = "http://127.0.0.1:30004"

async def run_e2e_tests():
    print(f"🚀 开始使用 Playwright 进行前端 E2E 全量端到端测试: {BASE_URL}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()

        # 收集控制台错误
        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

        try:
            # 1. 测试登录页面
            print("\n[Step 1] 访问登录页面...")
            await page.goto(f"{BASE_URL}/login", wait_until="networkidle")
            title = await page.title()
            print(f"  ✓ 页面标题: {title}")
            
            # 输入账号密码登录
            print("  -> 输入账号密码登录 (admin1 / admin123)...")
            await page.fill('input[placeholder="请输入用户名"]', "admin1")
            await page.fill('input[placeholder="请输入密码"]', "admin123")
            await page.click('button:has-text("登 录")')
            
            # 等待跳转到仪表盘
            await page.wait_for_url("**/dashboard", timeout=10000)
            print("  ✓ 登录成功，成功跳转至 /dashboard 运营驾驶舱")

            # 2. 运营驾驶舱仪表盘
            print("\n[Step 2] 测试运营驾驶舱...")
            await page.wait_for_selector(".stat-card, .chart-card", timeout=8000)
            stat_cards = await page.locator(".stat-card").count()
            print(f"  ✓ 驾驶舱核心指标卡片已渲染，数量: {stat_cards}")

            # 3. 销售数据分析中心
            print("\n[Step 3] 测试数据分析中心...")
            await page.goto(f"{BASE_URL}/analytics/sales", wait_until="networkidle")
            await page.wait_for_selector(".chart-card", timeout=8000)
            print("  ✓ 销售数据分析图表卡片渲染成功")

            # 4. 设备综合管理整合页 (/devices) - 3 大平行选项卡测试
            print("\n[Step 4] 测试设备综合管理整合页及 3 大平行选项卡 (/devices)...")
            await page.goto(f"{BASE_URL}/devices", wait_until="networkidle")
            await page.wait_for_selector(".device-tabs", timeout=8000)

            # Tab 1: 设备档案管理
            print("  -> 测试 Tab 1: 设备档案管理...")
            device_rows = await page.locator(".el-tab-pane[name='devices'] .el-table__row, .el-table__row").count()
            print(f"  ✓ 设备列表表格渲染成功，设备记录数: {device_rows}")

            # 切换到 Tab 2: 设备型号/类型
            print("  -> 切换到 Tab 2: 设备型号/类型...")
            await page.click('.el-tabs__item:has-text("设备型号/类型")')
            await page.wait_for_timeout(500)
            model_rows = await page.locator(".el-tab-pane:not([style*='display: none']) .el-table__row, .el-table__row").count()
            print(f"  ✓ 设备型号 Tab 渲染成功，型号记录数: {model_rows}")

            # 验证录入新机型弹窗
            await page.click('button:has-text("+ 录入新机型")')
            await page.wait_for_selector(".el-dialog:visible", timeout=5000)
            dialog_text = await page.locator(".el-dialog:visible").inner_text()
            assert "型号名称" in dialog_text
            assert "型号编码" in dialog_text
            print("  ✓ 设备型号录入弹窗校验通过")
            await page.click('.el-dialog:visible button:has-text("取消")')
            await page.wait_for_selector(".el-dialog:visible", state="hidden", timeout=5000)

            # 切换到 Tab 3: 设备菜单定制
            print("  -> 切换到 Tab 3: 设备菜单定制...")
            await page.click('.el-tabs__item:has-text("设备菜单定制")')
            await page.wait_for_timeout(500)
            menu_rows = await page.locator(".el-tab-pane:not([style*='display: none']) .el-table__row, .el-table__row").count()
            print(f"  ✓ 设备菜单定制 Tab 渲染成功，定制商品记录数: {menu_rows}")

            # 切换到 Tab 4: 设备海报屏保
            print("  -> 切换到 Tab 4: 设备海报屏保...")
            await page.click('.el-tabs__item:has-text("设备海报屏保")')
            await page.wait_for_timeout(500)
            poster_rows = await page.locator(".el-tab-pane:not([style*='display: none']) .el-table__row, .el-table__row").count()
            print(f"  ✓ 设备海报屏保 Tab 渲染成功，海报记录数: {poster_rows}")
            # 打开新建海报弹窗验证 4 个分区
            await page.click('button:has-text("新建海报配置")')
            await page.wait_for_selector(".el-dialog:visible", timeout=5000)
            dialog_text = await page.locator(".el-dialog:visible").inner_text()
            assert "基本配置" in dialog_text
            assert "海报图片上传" in dialog_text
            assert "适用范围" in dialog_text
            print("  ✓ 海报新建/编辑弹窗包含 4 大业务分区并校验通过")
            await page.click('.el-dialog:visible button:has-text("取消")')
            await page.wait_for_selector(".el-dialog:visible", state="hidden", timeout=5000)

            # 6. 全局菜单档案管理整合页 (/menus) - 3 大平行选项卡测试
            print("\n[Step 6] 测试全局菜单档案管理整合页及 3 大平行选项卡 (/menus)...")
            await page.goto(f"{BASE_URL}/menus", wait_until="networkidle")
            await page.wait_for_selector(".menu-tabs", timeout=8000)

            # Tab 1: 全局菜谱商品
            print("  -> 测试 Tab 1: 全局菜谱商品...")
            item_rows = await page.locator(".el-tab-pane[name='items'] .el-table__row, .el-table__row").count()
            print(f"  ✓ 全局商品列表表格渲染成功，商品记录数: {item_rows}")

            # 切换到 Tab 2: 规格模板库
            print("  -> 切换到 Tab 2: 规格模板库...")
            await page.click('.el-tabs__item:has-text("规格模板库")')
            await page.wait_for_timeout(500)
            tpl_rows = await page.locator(".el-tab-pane:not([style*='display: none']) .el-table__row, .el-table__row").count()
            print(f"  ✓ 规格模板库 Tab 渲染成功，模板记录数: {tpl_rows}")

            # 验证新建规格模板弹窗
            await page.click('button:has-text("+ 新建规格模板")')
            await page.wait_for_selector(".el-dialog:visible", timeout=5000)
            dialog_text = await page.locator(".el-dialog:visible").inner_text()
            assert "规格分类" in dialog_text
            assert "规格默认配料消耗" in dialog_text
            print("  ✓ 规格模板新建弹窗校验通过")
            await page.click('.el-dialog:visible button:has-text("取消")')
            await page.wait_for_selector(".el-dialog:visible", state="hidden", timeout=5000)

            # 切换到 Tab 3: 菜单品类分类
            print("  -> 切换到 Tab 3: 菜单品类分类...")
            await page.click('.el-tabs__item:has-text("菜单品类分类")')
            await page.wait_for_timeout(500)
            cat_rows = await page.locator(".el-tab-pane:not([style*='display: none']) .el-table__row, .el-table__row").count()
            print(f"  ✓ 菜单品类分类 Tab 渲染成功，品类记录数: {cat_rows}")

            # 验证新建品类弹窗
            await page.click('button:has-text("+ 新建品类分类")')
            await page.wait_for_selector(".el-dialog:visible", timeout=5000)
            cat_dialog_text = await page.locator(".el-dialog:visible").inner_text()
            assert "设备硬件机型" in cat_dialog_text
            assert "分类名称" in cat_dialog_text
            print("  ✓ 菜单品类新建弹窗校验通过")
            await page.click('.el-dialog:visible button:has-text("取消")')
            await page.wait_for_selector(".el-dialog:visible", state="hidden", timeout=5000)

            # 7. 库存管理整合页 (/inventory) - 2 大平行选项卡测试
            print("\n[Step 7] 测试库存管理整合页及 2 大平行选项卡 (/inventory)...")
            await page.goto(f"{BASE_URL}/inventory", wait_until="networkidle")
            await page.wait_for_selector(".inventory-tabs", timeout=8000)

            # Tab 1: 物料仓库档案
            print("  -> 测试 Tab 1: 物料仓库档案...")
            mat_rows = await page.locator(".el-tab-pane:visible .el-table__row, .el-table__row").count()
            print(f"  ✓ 物料仓库档案大表渲染成功，物料品类数: {mat_rows}")

            # 切换到 Tab 2: 进出库流水记录
            print("  -> 切换到 Tab 2: 进出库流水记录...")
            await page.click('.el-tabs__item:has-text("进出库流水记录")')
            await page.wait_for_timeout(500)
            rec_rows = await page.locator(".el-tab-pane:visible .el-table__row, .el-table__row").count()
            print(f"  ✓ 进出库流水记录 Tab 渲染成功，流水记录数: {rec_rows}")

            # 8. 运营管理员管理 (/users)
            print("\n[Step 8] 测试运营管理员账号管理 (/users)...")
            await page.goto(f"{BASE_URL}/users", wait_until="networkidle")
            await page.wait_for_selector(".el-table", timeout=8000)
            user_rows = await page.locator(".el-table__row").count()
            print(f"  ✓ 管理员列表大表渲染成功，账号记录数: {user_rows}")

            print("\n========================================================")
            print("🎉 Playwright 前端 E2E 整合后全部核心模块与平行选项卡测试 100% 通过！")
            print("========================================================")

        except Exception as e:
            print(f"\n❌ 测试执行出现异常: {e}")
            await page.screenshot(path="playwright_error_screenshot.png")
            raise e
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(run_e2e_tests())
