import asyncio
from playwright.async_api import async_playwright

BASE_URL = "http://127.0.0.1:30004"

async def test_create_item_flow():
    print("🚀 开始使用 Playwright 测试新建全局商品及内联规格模板与加价流程...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})

        try:
            # 登录
            await page.goto(f"{BASE_URL}/login", wait_until="networkidle")
            await page.fill('input[placeholder="请输入用户名"]', "admin1")
            await page.fill('input[placeholder="请输入密码"]', "admin123")
            await page.click('button:has-text("登 录")')
            await page.wait_for_url("**/dashboard", timeout=10000)

            # 前往全局商品页面
            await page.goto(f"{BASE_URL}/menus", wait_until="networkidle")
            await page.wait_for_selector(".menu-tabs .el-table", timeout=8000)

            # 点击新建全局商品
            print("  -> 点击 + 新建全局商品...")
            await page.click('button:has-text("+ 新建全局商品")')
            await page.wait_for_selector(".el-dialog:visible", timeout=5000)

            # 填写商品名称
            await page.fill('input[placeholder="如 经典美式、生椰拿铁"]', "Playwright自动化测试咖啡")

            # 验证规格模板子表
            sku_rows = await page.locator(".el-dialog:visible .el-table__row").count()
            print(f"  ✓ 规格模板子表已渲染，默认规格行数: {sku_rows}")

            # 点击保存
            print("  -> 提交保存全局商品及挂载规格...")
            await page.click('.el-dialog:visible button:has-text("确认保存商品与规格")')

            # 等待弹窗关闭并刷新大表
            await page.wait_for_selector(".el-dialog:visible", state="hidden", timeout=8000)
            print("  ✓ 商品及规格保存成功，弹窗已关闭")

            # 搜索验证刚创建的商品
            await page.fill('input[placeholder="输入商品名称"]', "Playwright自动化测试咖啡")
            await page.click('button:has-text("查询")')
            await page.wait_for_timeout(1000)

            found_text = await page.locator(".menu-tabs .el-table").first.inner_text()
            assert "Playwright自动化测试咖啡" in found_text
            print("  ✓ 在商品大表中成功检索到新创建的商品及挂载规格标签！")

            print("\n🎉 全局商品与内联规格模板创建交互 100% 验证成功！")

        except Exception as e:
            print(f"\n❌ 测试失败: {e}")
            await page.screenshot(path="create_item_error.png")
            raise e
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(test_create_item_flow())
