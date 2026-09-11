import asyncio
import os
from playwright.async_api import async_playwright

SCREENSHOT_DIR_1 = "/home/ubuntu/autoMachine/automake/docs/images/guide"
SCREENSHOT_DIR_2 = "/home/ubuntu/autoMachine/docs/images/guide"

async def save_screenshot(page, filename, selector=None):
    path1 = os.path.join(SCREENSHOT_DIR_1, filename)
    path2 = os.path.join(SCREENSHOT_DIR_2, filename)
    try:
        if selector:
            el = page.locator(selector)
            await el.screenshot(path=path1)
            await el.screenshot(path=path2)
        else:
            await page.screenshot(path=path1, full_page=False)
            await page.screenshot(path=path2, full_page=False)
        print(f"  ✓ Saved screenshot: {filename}")
    except Exception as e:
        print(f"  ❌ Failed to save {filename}: {e}")

async def run():
    print("🚀 开始通过 Playwright 截取操作手册关键界面图...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # 1440x920 桌面高清视口
        context = await browser.new_context(
            viewport={"width": 1440, "height": 920},
            ignore_https_errors=True
        )
        page = await context.new_page()

        # ==========================================
        # 1. Kiosk 触控大屏模拟器截屏
        # ==========================================
        print("\n[Step 1] 访问上位机触控终端 Kiosk...")
        try:
            await page.goto("http://127.0.0.1:8000/simulator/kiosk/", wait_until="networkidle", timeout=15000)
            await page.wait_for_timeout(2000)
            await save_screenshot(page, "01_kiosk_main.png")

            # 注入菜单确保数据丰富
            btn_seed = page.locator("#btnSeedMenu")
            if await btn_seed.count() > 0:
                print("  -> 点击注入真实测试菜单...")
                await btn_seed.click()
                await page.wait_for_timeout(2000)
                await save_screenshot(page, "01_kiosk_seeded.png")

            # 选规格
            print("[Step 2] 打开商品规格定制弹窗...")
            spec_btns = page.locator('button:has-text("选规格")')
            if await spec_btns.count() > 0:
                await spec_btns.first.click()
                await page.wait_for_selector("#specModal:not(.hidden)", timeout=5000)
                await page.wait_for_timeout(800)
                await save_screenshot(page, "02_kiosk_sku_modal.png")

                # 加入购物车
                print("  -> 确认加入购物车...")
                confirm_btn = page.locator('button:has-text("确认加入购物车")')
                if await confirm_btn.count() > 0:
                    await confirm_btn.click()
                    await page.wait_for_selector("#specModal.hidden", timeout=5000)
                    await page.wait_for_timeout(1000)
                    await save_screenshot(page, "03_kiosk_cart.png")

                # 去结算 / 唤起真实微信收银台
                print("  -> 点击去结算唤起收银台...")
                btn_checkout = page.locator("#btnCheckout")
                if await btn_checkout.count() > 0 and await btn_checkout.is_enabled():
                    await btn_checkout.click()
                    await page.wait_for_selector("#payModal:not(.hidden)", timeout=8000)
                    # 等待微信 Native 二维码生成
                    await page.wait_for_timeout(2500)
                    await save_screenshot(page, "04_kiosk_pay_modal.png")

                    # 关闭支付弹窗
                    close_btn = page.locator('button:has-text("关闭支付"), #btnClosePay')
                    if await close_btn.count() > 0:
                        await close_btn.first.click()
                        await page.wait_for_timeout(500)

            # 滚动到底部查看日志
            print("[Step 3] 截取运行黑匣子与设备日志...")
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(800)
            await save_screenshot(page, "05_kiosk_logs.png")

        except Exception as e:
            print(f"  ❌ Kiosk 截屏发生异常: {e}")

        # ==========================================
        # 2. 运营管理后台截屏
        # ==========================================
        print("\n[Step 4] 访问运营管理后台...")
        admin_url = "https://127.0.0.1"
        try:
            await page.goto(f"{admin_url}/login", wait_until="networkidle", timeout=10000)
        except Exception:
            admin_url = "https://tinylab.store"
            await page.goto(f"{admin_url}/login", wait_until="networkidle", timeout=10000)

        await page.wait_for_timeout(1000)
        await save_screenshot(page, "06_admin_login.png")

        # 登录
        print("  -> 执行后台登录 (admin1 / admin123)...")
        try:
            await page.fill('input[placeholder*="用户名"]', "admin1")
            await page.fill('input[placeholder*="密码"]', "admin123")
            await page.click('button:has-text("登 录")')
            await page.wait_for_url("**/dashboard", timeout=10000)
            await page.wait_for_timeout(2000)

            # 2.1 运营驾驶舱
            print("[Step 5] 截取运营驾驶舱...")
            await save_screenshot(page, "07_admin_dashboard.png")

            # 2.2 设备综合管理
            print("[Step 6] 截取设备综合管理...")
            await page.goto(f"{admin_url}/devices", wait_until="networkidle")
            await page.wait_for_timeout(1500)
            await save_screenshot(page, "08_admin_devices.png")

            # 2.3 全局菜单档案管理
            print("[Step 7] 截取全局菜单档案管理...")
            await page.goto(f"{admin_url}/menus", wait_until="networkidle")
            await page.wait_for_timeout(1500)
            await save_screenshot(page, "09_admin_menus.png")

            # 2.4 库存管理
            print("[Step 8] 截取库存管理...")
            await page.goto(f"{admin_url}/inventory", wait_until="networkidle")
            await page.wait_for_timeout(1500)
            await save_screenshot(page, "10_admin_inventory.png")

            # 2.5 订单中心
            print("[Step 9] 截取订单中心...")
            await page.goto(f"{admin_url}/orders", wait_until="networkidle")
            await page.wait_for_timeout(1500)
            await save_screenshot(page, "11_admin_orders.png")

        except Exception as e:
            print(f"  ❌ 管理后台截屏发生异常: {e}")

        print("\n🎉 全部关键界面截图流程执行完毕！")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
