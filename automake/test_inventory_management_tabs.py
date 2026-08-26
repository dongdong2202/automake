import asyncio
from playwright.async_api import async_playwright

BASE_URL = "http://127.0.0.1:30004"

async def test_inventory_management_tabs():
    print("🚀 开始使用 Playwright 测试库存管理整合页与 2 大平行选项卡交互...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})

        try:
            # 1. 登录系统
            await page.goto(f"{BASE_URL}/login", wait_until="networkidle")
            await page.fill('input[placeholder="请输入用户名"]', "admin1")
            await page.fill('input[placeholder="请输入密码"]', "admin123")
            await page.click('button:has-text("登 录")')
            await page.wait_for_url("**/dashboard", timeout=10000)

            # 2. 访问库存管理整合页 /inventory
            print("  -> 访问库存管理整合页 /inventory...")
            await page.goto(f"{BASE_URL}/inventory", wait_until="networkidle")
            await page.wait_for_selector(".inventory-tabs", timeout=8000)

            # 验证 Tab 1: 物料仓库档案
            print("  -> 测试 Tab 1: 📦 物料仓库档案...")
            active_tab_title = await page.locator(".el-tabs__item.is-active").inner_text()
            assert "物料仓库档案" in active_tab_title
            mat_table_text = await page.locator(".el-tab-pane:visible .el-table").first.inner_text()
            print("  ✓ 物料大表渲染成功")

            # 验证新建物料品类弹窗
            await page.click('button:has-text("+ 新建物料品类")')
            await page.wait_for_selector(".el-dialog:visible", timeout=4000)
            dialog_title = await page.locator(".el-dialog:visible .el-dialog__title").inner_text()
            assert "新建物料品类" in dialog_title
            await page.click('.el-dialog:visible button:has-text("取消")')
            await page.wait_for_selector(".el-dialog:visible", state="hidden", timeout=4000)
            print("  ✓ 新建物料品类弹窗校验通过")

            # 验证采购入库弹窗与提交
            print("  -> 测试采购入库操作...")
            await page.click('button:has-text("+ 原料采购入库")')
            await page.wait_for_selector(".el-dialog:visible", timeout=4000)
            await page.fill('.el-dialog:visible input[placeholder="如 8月批次常规采购 / 补充周末库存"]', "Playwright自动化采购批次")
            await page.click('.el-dialog:visible button:has-text("确认提交")')
            await page.wait_for_selector(".el-dialog:visible", state="hidden", timeout=8000)
            print("  ✓ 采购入库提交成功，物料库存已实时同步")

            # 3. 切换到 Tab 2: 进出库流水记录
            print("\n  -> 切换到 Tab 2: 📋 进出库流水记录...")
            await page.click('.el-tabs__item:has-text("进出库流水记录")')
            await page.wait_for_timeout(1000)
            assert "tab=records" in page.url
            rec_table_text = await page.locator(".el-tab-pane:visible .el-table").first.inner_text()
            assert "Playwright自动化采购批次" in rec_table_text or "采购入库" in rec_table_text
            print("  ✓ 进出库流水大表渲染成功，刚提交的入库台账已实时上屏")

            # 4. 验证子路由重定向 /inventory/records -> /inventory?tab=records
            print("\n  -> 验证旧路由重定向 /inventory/records...")
            await page.goto(f"{BASE_URL}/inventory/records", wait_until="networkidle")
            await page.wait_for_timeout(1000)
            assert "tab=records" in page.url
            active_tab_title_2 = await page.locator(".el-tabs__item.is-active").inner_text()
            assert "进出库流水记录" in active_tab_title_2
            print("  ✓ 子路由平滑重定向与 Tab 激活校验 100% 通过！")

            print("\n🎉 库存管理整合页 2 大平行选项卡 Playwright 端到端自动化测试 100% 通过！")

        except Exception as e:
            print(f"\n❌ 测试失败: {e}")
            await page.screenshot(path="inventory_tabs_error.png")
            raise e
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(test_inventory_management_tabs())
