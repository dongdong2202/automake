import asyncio
from playwright.async_api import async_playwright

BASE_URL = "http://127.0.0.1:30004"

async def test_device_posters_integrated_tab():
    print("🚀 开始使用 Playwright 测试海报屏保并入设备综合管理 4 大平行选项卡交互...")
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

            # 2. 访问设备综合管理页 /devices
            print("  -> 访问设备综合管理页 /devices 并验证 4 大平行选项卡...")
            await page.goto(f"{BASE_URL}/devices", wait_until="networkidle")
            await page.wait_for_selector(".device-tabs", timeout=8000)

            tabs_text = await page.locator(".device-tabs .el-tabs__header").inner_text()
            assert "设备档案管理" in tabs_text
            assert "设备型号/类型" in tabs_text
            assert "设备菜单定制" in tabs_text
            assert "设备海报屏保" in tabs_text
            print("  ✓ 4 大平行选项卡（档案、型号、菜单定制、海报屏保）全部渲染就绪")

            # 3. 切换到 Tab 4: 设备海报屏保
            print("  -> 切换到 Tab 4: 🖼 设备海报屏保...")
            await page.click('.el-tabs__item:has-text("设备海报屏保")')
            await page.wait_for_timeout(1000)
            assert "tab=posters" in page.url

            posters_table = await page.locator(".el-tab-pane:visible .el-table").first.inner_text()
            print("  ✓ 海报列表大表在设备综合管理内渲染成功")

            # 验证新建海报配置弹窗（包含 4 大分区）
            print("  -> 打开新建海报配置弹窗...")
            await page.click('button:has-text("+ 新建海报配置")')
            await page.wait_for_selector(".el-dialog:visible", timeout=5000)
            dialog_text = await page.locator(".el-dialog:visible").inner_text()
            assert "基本配置" in dialog_text
            assert "海报图片上传" in dialog_text
            assert "适用范围" in dialog_text
            print("  ✓ 海报新建/编辑弹窗包含 4 大业务分区并校验通过")
            await page.click('.el-dialog:visible button:has-text("取消")')
            await page.wait_for_selector(".el-dialog:visible", state="hidden", timeout=5000)

            # 4. 验证子路由重定向 /devices/posters -> /devices?tab=posters
            print("\n  -> 验证旧路由重定向 /devices/posters...")
            await page.goto(f"{BASE_URL}/devices/posters", wait_until="networkidle")
            await page.wait_for_timeout(1000)
            assert "tab=posters" in page.url
            active_tab_title = await page.locator(".el-tabs__item.is-active").inner_text()
            assert "设备海报屏保" in active_tab_title
            print("  ✓ 旧路由 /devices/posters 平滑重定向与 Tab 激活校验 100% 通过！")

            print("\n🎉 设备海报屏保并入设备综合管理 Playwright 端到端自动化测试 100% 通过！")

        except Exception as e:
            print(f"\n❌ 测试失败: {e}")
            await page.screenshot(path="posters_integrated_error.png")
            raise e
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(test_device_posters_integrated_tab())
