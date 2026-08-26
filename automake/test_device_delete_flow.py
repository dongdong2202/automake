import asyncio
from playwright.async_api import async_playwright

BASE_URL = "http://127.0.0.1:30004"

async def test_device_delete_flow():
    print("🚀 开始使用 Playwright 测试设备新增与删除流程...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})

        # 监听 DELETE 请求
        delete_requests = []
        page.on("request", lambda req: delete_requests.append(req.url) if req.method == "DELETE" and "devices" in req.url else None)

        try:
            # 1. 登录
            await page.goto(f"{BASE_URL}/login", wait_until="networkidle")
            await page.fill('input[placeholder="请输入用户名"]', "admin1")
            await page.fill('input[placeholder="请输入密码"]', "admin123")
            await page.click('button:has-text("登 录")')
            await page.wait_for_url("**/dashboard", timeout=10000)

            # 2. 访问设备综合管理页
            print("  -> 访问设备管理页 /devices?tab=devices...")
            await page.goto(f"{BASE_URL}/devices?tab=devices", wait_until="networkidle")
            await page.wait_for_selector(".device-tabs", timeout=8000)

            # 监听网络和控制台
            page.on("console", lambda msg: print(f"  [Browser Console] {msg.text}"))
            async def on_response(res):
                if "/api/admin/" in res.url:
                    text = ""
                    try:
                        text = await res.text()
                    except:
                        pass
                    print(f"  [API {res.status}] {res.url} -> {text}")
            page.on("response", on_response)

            # 3. 录入一台临时测试设备
            test_sn = "SN_DEL_TEST_999"
            test_name = "待删除自动化测试咖啡机"
            print(f"  -> 点击 + 录入新设备 [{test_sn}]...")
            await page.click('button:has-text("+ 录入新设备")')
            await page.wait_for_selector(".el-dialog:visible", timeout=5000)

            await page.fill('.el-dialog:visible input[placeholder="出厂唯一编码，如 SN001"]', test_sn)
            await page.fill('.el-dialog:visible input[placeholder="如 朝阳大悦城1号咖啡机"]', test_name)
            await page.click('.el-dialog:visible button:has-text("确认保存")')
            await page.wait_for_selector(".el-dialog:visible", state="hidden", timeout=8000)
            print("  ✓ 临时测试设备录入成功")

            # 4. 搜索检索刚创建的设备
            await page.fill('input[placeholder="输入 SN 或名称"]', test_sn)
            await page.click('button:has-text("查询")')
            await page.wait_for_timeout(1000)

            found_text = await page.locator(".el-tab-pane[name='devices'] .el-table, .el-table").first.inner_text()
            assert test_sn in found_text
            print(f"  ✓ 成功检索到设备 [{test_sn}]")

            # 5. 点击操作列的“删除”按钮并确认 Popconfirm
            print("  -> 点击该设备的 [删除] 按钮...")
            row = page.locator(f".el-table__row:has-text('{test_sn}')")
            await row.locator('button:has-text("删除")').click()
            await page.wait_for_selector(".el-popconfirm:visible, .el-popper:visible", timeout=5000)

            # 确认删除
            print("  -> 点击 Popconfirm 确认按钮...")
            await page.click('.el-popper:visible button:has-text("确定"), .el-popconfirm:visible button:has-text("确定")')

            await page.wait_for_timeout(1500)
            assert len(delete_requests) > 0
            print(f"  ✓ 成功捕获 DELETE 请求: {delete_requests[-1]}")

            # 6. 验证已被删除
            await page.click('button:has-text("查询")')
            await page.wait_for_timeout(1000)
            table_after_del = await page.locator(".el-tab-pane[name='devices'] .el-table, .el-table").first.inner_text()
            assert test_sn not in table_after_del
            print(f"  ✓ 确认设备 [{test_sn}] 已从列表中彻底移除！")

            print("\n🎉 设备删除功能 Playwright 自动化测试 100% 通过！")

        except Exception as e:
            print(f"\n❌ 测试失败: {e}")
            await page.screenshot(path="device_delete_error.png")
            raise e
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(test_device_delete_flow())
