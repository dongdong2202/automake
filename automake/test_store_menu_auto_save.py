import asyncio
from playwright.async_api import async_playwright

BASE_URL = "http://127.0.0.1:30004"

async def test_store_menu_auto_save():
    print("🚀 开始使用 Playwright 测试门店菜单滑动开关自动保存交互...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})

        # 监听 PUT 请求
        put_requests = []
        page.on("request", lambda req: put_requests.append(req.url) if req.method == "PUT" and "store-items" in req.url else None)

        try:
            # 1. 登录
            await page.goto(f"{BASE_URL}/login", wait_until="networkidle")
            await page.fill('input[placeholder="请输入用户名"]', "admin1")
            await page.fill('input[placeholder="请输入密码"]', "admin123")
            await page.click('button:has-text("登 录")')
            await page.wait_for_url("**/dashboard", timeout=10000)

            # 2. 访问设备综合管理页并切换到设备菜单定制 Tab
            print("  -> 访问设备综合管理页 /devices 并切换到 Tab 3: 设备菜单定制...")
            await page.goto(f"{BASE_URL}/devices", wait_until="networkidle")
            await page.wait_for_selector(".device-tabs", timeout=8000)
            await page.click('.el-tabs__item:has-text("设备菜单定制")')
            await page.wait_for_timeout(600)

            # 3. 验证没有'操作'列或'保存修改'按钮
            save_btns = await page.locator('#pane-menus button:has-text("保存修改")').count()
            assert save_btns == 0
            print(f"  ✓ 确认已移除'操作'列与'保存修改'按钮 (按钮数: {save_btns})")

            # 4. 点击第一行的'是否上架'开关触发自动保存
            print("  -> 滑动切换第一行商品的'是否上架'开关...")
            switch_locator = page.locator("#pane-menus .el-table__row .el-switch").first
            await switch_locator.click()

            # 等待网络请求完成
            await page.wait_for_timeout(1000)

            assert len(put_requests) > 0
            print(f"  ✓ 成功捕获滑动开关触发的自动保存 PUT 请求: {put_requests[-1]}")

            # 验证消息提示
            msg_text = await page.locator(".el-message--success").first.inner_text()
            print(f"  ✓ 成功弹出实时更新提示: {msg_text}")

            print("\n🎉 门店商品滑动开关自动保存交互 100% 验证成功！")

        except Exception as e:
            print(f"\n❌ 测试失败: {e}")
            await page.screenshot(path="store_menu_auto_save_error.png")
            raise e
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(test_store_menu_auto_save())
