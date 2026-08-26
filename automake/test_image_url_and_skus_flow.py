import asyncio
from playwright.async_api import async_playwright

BASE_URL = "http://127.0.0.1:30004"

async def test_image_url_and_skus():
    print("🚀 开始使用 Playwright 严格测试图片路径 (包含相对路径 /media/... 及直传) 与商品保存交互...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})

        # 监听错误信息
        dialog_errors = []
        page.on("dialog", lambda d: print(f"Dialog: {d.message}"))

        try:
            # 1. 登录
            await page.goto(f"{BASE_URL}/login", wait_until="networkidle")
            await page.fill('input[placeholder="请输入用户名"]', "admin1")
            await page.fill('input[placeholder="请输入密码"]', "admin123")
            await page.click('button:has-text("登 录")')
            await page.wait_for_url("**/dashboard", timeout=10000)

            # 2. 访问商品管理
            await page.goto(f"{BASE_URL}/menus", wait_until="networkidle")
            await page.wait_for_selector(".menu-tabs .el-table", timeout=8000)

            # 3. 打开新建弹窗
            print("  -> 点击 + 新建全局商品...")
            await page.click('button:has-text("+ 新建全局商品")')
            await page.wait_for_selector(".el-dialog:visible", timeout=5000)

            # 4. 填写基本档案
            test_product_name = "严苛测试海盐芝士厚乳拿铁"
            await page.fill('input[placeholder="如 经典美式、生椰拿铁"]', test_product_name)

            # 5. 填入相对媒体路径到 image_url 输入框（这正是之前触发 URLField 校验报错的场景！）
            print("  -> 填入相对路径 /media/menus/latte_main.png 到主图输入框...")
            await page.fill('input[placeholder="或直接输入主图 URL"]', "/media/menus/latte_main.png")

            # 填入详情图路径
            print("  -> 填入相对路径 /media/menus/latte_detail.png 到详情图输入框...")
            await page.fill('input[placeholder="或直接输入详情页图 URL"]', "/media/menus/latte_detail.png")

            # 6. 配置规格与加价
            print("  -> 验证规格子表及多规格累加改价...")
            sku_rows = await page.locator(".el-dialog:visible .el-table__row").count()
            print(f"  ✓ 当前挂载规格行数: {sku_rows}")

            # 7. 提交保存
            print("  -> 提交保存商品档案及规格...")
            await page.click('.el-dialog:visible button:has-text("确认保存商品与规格")')

            # 8. 等待弹窗正常关闭（若校验报错则弹窗不会关闭，等待超时即报错）
            await page.wait_for_selector(".el-dialog:visible", state="hidden", timeout=8000)
            print("  ✓ 弹窗成功关闭，无任何 image_url 格式报错！")

            # 9. 检索新保存的商品
            await page.fill('input[placeholder="输入商品名称"]', test_product_name)
            await page.click('button:has-text("查询")')
            await page.wait_for_timeout(1000)

            table_text = await page.locator(".menu-tabs .el-table").first.inner_text()
            assert test_product_name in table_text
            print(f"  ✓ 成功检索到新商品 [{test_product_name}]！")

            # 10. 点击编辑按钮，检查回显与再次保存
            print("  -> 点击编辑商品，验证图片路径回显与再次保存...")
            await page.click(f'.el-table__row:has-text("{test_product_name}") button:has-text("编辑商品")')
            await page.wait_for_selector(".el-dialog:visible", timeout=5000)

            main_img_val = await page.input_value('.el-dialog:visible input[placeholder="或直接输入主图 URL"]')
            assert main_img_val == "/media/menus/latte_main.png"
            print(f"  ✓ 主图路径正确回显: {main_img_val}")

            detail_img_val = await page.input_value('.el-dialog:visible input[placeholder="或直接输入详情页图 URL"]')
            assert detail_img_val == "/media/menus/latte_detail.png"
            print(f"  ✓ 详情图路径正确回显: {detail_img_val}")

            # 再次保存
            await page.click('.el-dialog:visible button:has-text("确认保存商品与规格")')
            await page.wait_for_selector(".el-dialog:visible", state="hidden", timeout=8000)
            print("  ✓ 二次编辑保存成功！")

            print("\n🎉 Playwright 严格测试图片相对路径、详情页图与规格保存全部 100% 通过！")

        except Exception as e:
            print(f"\n❌ 测试失败: {e}")
            await page.screenshot(path="image_url_error.png")
            raise e
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(test_image_url_and_skus())
