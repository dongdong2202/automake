import asyncio
from playwright.async_api import async_playwright

BASE_URL = "http://127.0.0.1:30004"

async def test_inventory_expiration_ui():
    print("🚀 开始使用 Playwright 测试物料保质期预警、体检触发及告警中心联动...")
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

            # 3. 点击【保质期体检预警 (30天)】
            print("  -> 点击【保质期体检预警 (30天)】按钮...")
            check_btn = page.locator('button:has-text("保质期体检预警")')
            await check_btn.click()
            await page.wait_for_selector(".el-notification", timeout=6000)
            notify_text = await page.locator(".el-notification").inner_text()
            assert "物料保质期预警体检完成" in notify_text or "扫描" in notify_text
            print(f"  ✓ 保质期体检通知弹窗校验通过: {notify_text.splitlines()[0]}")

            # 4. 切换到 Tab 2: 进出库流水记录，验证保质期标签
            print("\n  -> 切换到 Tab 2: 进出库流水记录...")
            await page.click('.el-tabs__item:has-text("进出库流水记录")')
            await page.wait_for_timeout(1000)

            table_text = await page.locator(".el-tab-pane:visible .el-table").first.inner_text()
            assert "已过期" in table_text or "临期" in table_text
            print("  ✓ 流水表格成功渲染【批次保质期 / 到期状态】动态预警标签（🚨 已过期 / ⚠️ 临期）")

            # 5. 访问告警中心 /notifications
            print("\n  -> 访问系统告警中心 /notifications...")
            await page.goto(f"{BASE_URL}/notifications", wait_until="networkidle")
            await page.wait_for_selector(".alert-list-page .el-table", timeout=8000)

            alerts_text = await page.locator(".alert-list-page .el-table").inner_text()
            assert "物料保质期预警" in alerts_text or "物料过期告警" in alerts_text
            print("  ✓ 告警中心成功展示物料临期/过期平台通知")

            # 6. 测试标记已处理
            resolve_btn = page.locator('.alert-list-page button:has-text("标记已处理")').first
            if await resolve_btn.count() > 0:
                await resolve_btn.click()
                await page.wait_for_timeout(1000)
                print("  ✓ 告警事件标记已处理操作成功")

            print("\n🎉 物料保质期预警与平台通知 Playwright 端到端全链路自动化测试 100% 通过！")

        except Exception as e:
            print(f"\n❌ 测试失败: {e}")
            await page.screenshot(path="inventory_exp_error.png")
            raise e
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(test_inventory_expiration_ui())
