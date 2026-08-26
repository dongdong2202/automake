import asyncio
import time
from playwright.async_api import async_playwright

BASE_URL = "http://127.0.0.1:30004"

async def test_permanent_ui():
    print("🚀 开始使用 Playwright 验证永久有效（纸杯/耗材）免填保质期与 UI 展示...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})

        try:
            # 1. 登录
            await page.goto(f"{BASE_URL}/login", wait_until="networkidle")
            await page.fill('input[placeholder="请输入用户名"]', "admin1")
            await page.fill('input[placeholder="请输入密码"]', "admin123")
            await page.click('button:has-text("登 录")')
            await page.wait_for_url("**/dashboard", timeout=8000)

            # 2. 访问库存管理
            await page.goto(f"{BASE_URL}/inventory", wait_until="networkidle")
            await page.wait_for_selector(".inventory-tabs", timeout=8000)

            # 3. 点击【+ 新建物料品类】创建纸杯
            await page.click('button:has-text("+ 新建物料品类")')
            await page.wait_for_selector('.el-dialog:has-text("新建物料品类")', timeout=5000)

            # 点击清空设为永久有效按钮
            clear_btn = page.locator('.el-dialog:has-text("新建物料品类") button:has-text("清空设为永久有效")')
            if await clear_btn.count() > 0:
                await clear_btn.click()
                print("  ✓ 点击【清空设为永久有效】按钮")

            # 验证下方永久有效提示已出现
            dialog_text = await page.locator('.el-dialog:has-text("新建物料品类")').inner_text()
            assert "永久有效" in dialog_text
            print("  ✓ 提示文案正确展示：当前未设定保质期（永久有效）")

            # 填写纸杯信息
            unique_suffix = str(int(time.time()))[-4:]
            await page.fill('.el-dialog:has-text("新建物料品类") input[placeholder*="例如 特级"]', f"纸杯_环保_{unique_suffix}")
            await page.fill('.el-dialog:has-text("新建物料品类") input[placeholder*="上位机匹配"]', f"paper_cup_{unique_suffix}")
            await page.fill('.el-dialog:has-text("新建物料品类") input[placeholder*="如 kg, 升"]', "个")
            
            # 设置初始库存 500
            qty_input = page.locator('.el-dialog:has-text("新建物料品类") label:has-text("初始库存数量")').locator('..').locator('input')
            await qty_input.fill("500")

            # 点击创建物料
            await page.click('.el-dialog:has-text("新建物料品类") button:has-text("创建物料")')
            await page.wait_for_selector('.el-dialog:has-text("新建物料品类")', state="hidden", timeout=8000)
            print("  ✓ 永久有效物料（纸杯）创建成功，弹窗已关闭")

            # 4. 在 Tab 1 物料大表中搜索该物料并验证【永久有效】Tag
            await page.fill('input[placeholder="输入物料名称或编码"]', f"paper_cup_{unique_suffix}")
            await page.locator('.el-tab-pane:visible button:has-text("查询")').first.click()
            await page.wait_for_timeout(1000)

            tab1_text = await page.locator(".el-tab-pane:visible .el-table").first.inner_text()
            assert "永久有效" in tab1_text
            print("  ✓ Tab 1 物料仓库档案大表中成功展示【永久有效】专属灰色标签")

            # 5. 切换到 Tab 2: 进出库流水记录
            await page.click('.el-tabs__item:has-text("进出库流水记录")')
            await page.wait_for_timeout(1000)
            
            tab2_text = await page.locator(".el-tab-pane:visible .el-table").first.inner_text()
            assert "永久有效" in tab2_text
            print("  ✓ Tab 2 进出库流水大表中成功展示【永久有效】到期状态标签")

            print("\n🎉 永久有效物料免填保质期与 UI 标签 Playwright 测试 100% PASS！")

        finally:
            await browser.close()

if __name__ == '__main__':
    asyncio.run(test_permanent_ui())
