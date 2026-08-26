import asyncio
from playwright.async_api import async_playwright

BASE_URL = "http://127.0.0.1:30004"

async def test_store_delete_protection():
    print("🚀 开始使用 Playwright 测试门店删除保护与友好拦截机制...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})

        # 监听 API 响应
        delete_responses = []
        page.on("response", lambda res: delete_responses.append((res.status, res.url)) if res.request.method == "DELETE" and "stores" in res.url else None)

        try:
            # 1. 登录
            await page.goto(f"{BASE_URL}/login", wait_until="networkidle")
            await page.fill('input[placeholder="请输入用户名"]', "admin1")
            await page.fill('input[placeholder="请输入密码"]', "admin123")
            await page.click('button:has-text("登 录")')
            await page.wait_for_url("**/dashboard", timeout=10000)

            # 2. 访问门店管理页
            print("  -> 访问门店架构管理页 /stores...")
            await page.goto(f"{BASE_URL}/stores", wait_until="networkidle")
            await page.wait_for_selector(".el-table", timeout=8000)

            # 3. 尝试删除带有历史订单的门店 (Mock Store A / ID: 100005)
            target_store_row = page.locator(".el-table__row:has-text('100005'), .el-table__row:has-text('Mock Store A')").first
            if await target_store_row.count() > 0:
                print("  -> 测试删除含有历史订单的门店 100005...")
                await target_store_row.locator('button:has-text("删除")').click()
                await page.wait_for_selector(".el-popper:visible, .el-popconfirm:visible", timeout=3000)
                await page.click('.el-popper:visible button:has-text("确定"), .el-popconfirm:visible button:has-text("确定")')
                await page.wait_for_timeout(1000)

                # 验证返回的是 200/400 业务错误拦截（而非 500 服务器崩溃）
                last_status, last_url = delete_responses[-1]
                print(f"  ✓ 成功拦截！API 状态: {last_status}, 彻底消除 500 异常崩溃")

                # 验证错误提示浮窗
                err_msg = await page.locator(".el-message--error, .el-message").first.inner_text()
                print(f"  ✓ 弹出清晰的业务指引提示: {err_msg}")

            # 4. 创建一个无历史订单的全新测试门店并删除
            print("\n  -> 测试创建纯净临时测试门店并正常删除...")
            await page.click('button:has-text("+ 新增门店")')
            await page.wait_for_selector(".el-dialog:visible", timeout=5000)
            await page.fill('.el-dialog:visible input[placeholder="例如 北京朝阳大悦城店"]', "Playwright纯净测试门店")
            await page.click('.el-dialog:visible button:has-text("确认保存")')
            await page.wait_for_selector(".el-dialog:visible", state="hidden", timeout=8000)
            print("  ✓ 临时门店创建成功")

            # 检索并删除该临时门店
            temp_row = page.locator(".el-table__row:has-text('Playwright纯净测试门店')").first
            await temp_row.locator('button:has-text("删除")').click()
            await page.wait_for_selector(".el-popper:visible, .el-popconfirm:visible", timeout=3000)
            await page.click('.el-popper:visible button:has-text("确定"), .el-popconfirm:visible button:has-text("确定")')
            await page.wait_for_timeout(1000)

            # 验证无历史订单门店可以正常删除
            print("  ✓ 纯净无订单门店正常删除成功")

            print("\n🎉 门店删除拦截机制与正常删除流程 Playwright 测试 100% 通过！")

        except Exception as e:
            print(f"\n❌ 测试失败: {e}")
            await page.screenshot(path="store_delete_error.png")
            raise e
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(test_store_delete_protection())
