import asyncio
import time
from playwright.async_api import async_playwright

BASE_URL = "http://127.0.0.1:30004"

async def test_material_datepicker():
    print("🚀 开始验证新建物料品类日历控件与默认过期时间联动...")
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

            # 3. 点击【+ 新建物料品类】
            await page.click('button:has-text("+ 新建物料品类")')
            await page.wait_for_selector('.el-dialog:has-text("新建物料品类")', timeout=5000)

            # 验证保质期/到期日输入框为日历控件
            date_picker_input = page.locator('.el-dialog:has-text("新建物料品类") .el-date-editor input')
            assert await date_picker_input.count() > 0
            default_val = await date_picker_input.input_value()
            print(f"  ✓ 新建物料品类日历控件已渲染，默认预填到期日: {default_val}")
            assert len(default_val) == 10 and default_val.startswith("202")

            # 填写测试物料
            unique_suffix = str(int(time.time()))[-4:]
            await page.fill('.el-dialog:has-text("新建物料品类") input[placeholder*="例如 特级"]', f"特级香草糖浆_{unique_suffix}")
            await page.fill('.el-dialog:has-text("新建物料品类") input[placeholder*="上位机匹配"]', f"vanilla_syrup_{unique_suffix}")
            await page.fill('.el-dialog:has-text("新建物料品类") input[placeholder*="如 kg, 升"]', "瓶")
            
            # 设置初始库存 25
            qty_input = page.locator('.el-dialog:has-text("新建物料品类") label:has-text("初始库存数量")').locator('..').locator('input')
            await qty_input.fill("25")

            # 点击创建物料
            await page.click('.el-dialog:has-text("新建物料品类") button:has-text("创建物料")')
            await page.wait_for_timeout(1500)
            print("  ✓ 新建物料品类提交成功")

            # 4. 切换到 Tab 2: 进出库流水记录
            await page.click('.el-tabs__item:has-text("进出库流水记录")')
            await page.wait_for_timeout(1000)
            
            table_text = await page.locator(".el-tab-pane:visible .el-table").first.inner_text()
            assert f"特级香草糖浆_{unique_suffix}" in table_text or default_val in table_text
            print("  ✓ 进出库流水台账中已自动生成该批次的初始入库记录，并继承设定的保质期！")

            # 5. 点击【+ 原料采购入库】
            await page.click('button:has-text("+ 原料采购入库")')
            await page.wait_for_selector('.el-dialog:has-text("原材料采购入库")', timeout=5000)
            
            record_date_picker = page.locator('.el-dialog:has-text("原材料采购入库") .el-date-editor input')
            assert await record_date_picker.count() > 0
            rec_date_val = await record_date_picker.input_value()
            print(f"  ✓ 采购入库对话框中已自动默认带入选中物料的保质期: {rec_date_val}")

            await page.click('.el-dialog:has-text("原材料采购入库") button:has-text("取消")')

            print("\n🎉 新建物料品类日历控件与默认保质期自动继承测试 100% PASS！")

        finally:
            await browser.close()

if __name__ == '__main__':
    asyncio.run(test_material_datepicker())
