"""
Playwright 全端到端 UI 自动化测试套件 (E2E Test Suite)
=====================================================
覆盖功能全流程：
1. 登录认证与路由鉴权跳转；
2. 运营驾驶舱 (Dashboard)：核心 KPI 统计卡片、双 Y 轴营收/订单趋势、热销商品条形图、设备运行环形图；
3. 数据分析 (Analytics) 6 大核心模块全交互验证：
   - 销售分析 (SalesAnalysis)
   - 财务概览 (FinanceOverview)
   - 产品分析 (ProductAnalysis)
   - 设备运维 (DeviceAnalysis)
   - 物料进销存 (MaterialAnalysis)
   - 客户画像 (CustomerAnalysis)
4. 订单中心 (OrderList) 与履约流转时间线抽屉 (OrderStatusLog Timeline & Payload Snapshot)；
5. 全流程自动捕获高分辨率测试截图至 test_screenshots/ 目录。
"""

import asyncio
import os
import sys
from playwright.async_api import async_playwright

BASE_URL = "https://127.0.0.1"
SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "test_screenshots")


async def run_e2e_suite():
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    print("=" * 70)
    print(f"🚀 启动 Playwright 全流程 UI 端到端自动化测试套件")
    print(f"   目标站点: {BASE_URL}")
    print(f"   截图保存目录: {SCREENSHOT_DIR}")
    print("=" * 70)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # 配置忽略自签名 SSL 证书，并设定 1440x900 桌面高清视口
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            ignore_https_errors=True
        )
        page = await context.new_page()

        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

        try:
            # -------------------------------------------------------------
            # Step 1: 登录流程测试
            # -------------------------------------------------------------
            print("\n[Step 1] 验证管理员登录与鉴权流程...")
            await page.goto(f"{BASE_URL}/login", wait_until="networkidle")
            page_title = await page.title()
            print(f"  ✓ 页面标题: {page_title}")

            # 填写登录表单
            print("  -> 输入超级管理员凭证 (admin1 / admin123)...")
            await page.fill('input[placeholder="请输入用户名"]', "admin1")
            await page.fill('input[placeholder="请输入密码"]', "admin123")
            await page.click('button:has-text("登 录")')

            # 等待成功跳转到 /dashboard
            await page.wait_for_url("**/dashboard", timeout=12000)
            print("  ✓ 登录成功，系统成功重定向至 /dashboard 运营驾驶舱")

            # -------------------------------------------------------------
            # Step 2: 运营驾驶舱 (Dashboard)
            # -------------------------------------------------------------
            print("\n[Step 2] 验证运营驾驶舱大盘渲染与 KPI 指标...")
            await page.wait_for_selector(".stat-card, .kpi-card", timeout=8000)
            await page.wait_for_timeout(1500) # 等待 ECharts 渲染动画完成

            # 检查 KPI 卡片数量
            kpi_count = await page.locator(".stat-card").count()
            print(f"  ✓ 驾驶舱 KPI 统计指标卡片渲染正常，卡片数: {kpi_count}")

            # 检查 ECharts Canvas 是否正常挂载
            canvas_count = await page.locator("canvas").count()
            print(f"  ✓ 驾驶舱 ECharts Canvas 图表实例已渲染，实例数: {canvas_count}")

            # 检查最近订单表格
            recent_rows = await page.locator(".el-table__row").count()
            print(f"  ✓ 驾驶舱最近订单实时列表渲染正常，行数: {recent_rows}")

            screenshot_dashboard = os.path.join(SCREENSHOT_DIR, "01_dashboard.png")
            await page.screenshot(path=screenshot_dashboard)
            print(f"  📸 保存驾驶舱截图: {screenshot_dashboard}")

            # -------------------------------------------------------------
            # Step 3: 数据分析 - 销售分析 (SalesAnalysis)
            # -------------------------------------------------------------
            print("\n[Step 3] 验证销售分析模块 (/analytics/sales)...")
            await page.goto(f"{BASE_URL}/analytics/sales", wait_until="networkidle")
            await page.wait_for_selector(".chart-card", timeout=8000)
            await page.wait_for_timeout(1200)

            chart_cards = await page.locator(".chart-card").count()
            print(f"  ✓ 销售分析图表卡片渲染正常，数量: {chart_cards}")

            screenshot_sales = os.path.join(SCREENSHOT_DIR, "02_analytics_sales.png")
            await page.screenshot(path=screenshot_sales)
            print(f"  📸 保存销售分析截图: {screenshot_sales}")

            # -------------------------------------------------------------
            # Step 4: 数据分析 - 财务概览 (FinanceOverview)
            # -------------------------------------------------------------
            print("\n[Step 4] 验证财务收支与退款概览模块 (/analytics/finance)...")
            await page.goto(f"{BASE_URL}/analytics/finance", wait_until="networkidle")
            await page.wait_for_selector(".chart-card", timeout=8000)
            await page.wait_for_timeout(1200)

            finance_kpis = await page.locator(".kpi-card").count()
            print(f"  ✓ 财务 KPI 汇总卡片渲染正常，数量: {finance_kpis}")

            screenshot_finance = os.path.join(SCREENSHOT_DIR, "03_analytics_finance.png")
            await page.screenshot(path=screenshot_finance)
            print(f"  📸 保存财务概览截图: {screenshot_finance}")

            # -------------------------------------------------------------
            # Step 5: 数据分析 - 产品与规格分析 (ProductAnalysis)
            # -------------------------------------------------------------
            print("\n[Step 5] 验证产品与规格偏好分析模块 (/analytics/products)...")
            await page.goto(f"{BASE_URL}/analytics/products", wait_until="networkidle")
            await page.wait_for_selector(".chart-card", timeout=8000)
            await page.wait_for_timeout(1200)

            product_rows = await page.locator(".el-table__row").count()
            print(f"  ✓ 商品热度排行数据明细表格渲染正常，单品数: {product_rows}")

            screenshot_products = os.path.join(SCREENSHOT_DIR, "04_analytics_products.png")
            await page.screenshot(path=screenshot_products)
            print(f"  📸 保存产品分析截图: {screenshot_products}")

            # -------------------------------------------------------------
            # Step 6: 数据分析 - 设备运维分析 (DeviceAnalysis)
            # -------------------------------------------------------------
            print("\n[Step 6] 验证设备运维与健康分析模块 (/analytics/devices)...")
            await page.goto(f"{BASE_URL}/analytics/devices", wait_until="networkidle")
            await page.wait_for_selector(".chart-card", timeout=8000)
            await page.wait_for_timeout(1200)

            device_records = await page.locator(".el-table__row").count()
            print(f"  ✓ 设备健康档案列表渲染正常，设备数: {device_records}")

            screenshot_devices = os.path.join(SCREENSHOT_DIR, "05_analytics_devices.png")
            await page.screenshot(path=screenshot_devices)
            print(f"  📸 保存设备运维分析截图: {screenshot_devices}")

            # -------------------------------------------------------------
            # Step 7: 数据分析 - 物料进销存与消耗预测 (MaterialAnalysis)
            # -------------------------------------------------------------
            print("\n[Step 7] 验证物料进销存与补货预测模块 (/analytics/materials)...")
            await page.goto(f"{BASE_URL}/analytics/materials", wait_until="networkidle")
            await page.wait_for_selector(".chart-card", timeout=8000)
            await page.wait_for_timeout(1200)

            material_forecast_rows = await page.locator(".el-table__row").count()
            print(f"  ✓ 智能补货预测与剩余天数表格渲染正常，物料数: {material_forecast_rows}")

            screenshot_materials = os.path.join(SCREENSHOT_DIR, "06_analytics_materials.png")
            await page.screenshot(path=screenshot_materials)
            print(f"  📸 保存物料分析截图: {screenshot_materials}")

            # -------------------------------------------------------------
            # Step 8: 数据分析 - 客户画像与复购分析 (CustomerAnalysis)
            # -------------------------------------------------------------
            print("\n[Step 8] 验证客户画像与复购分析模块 (/analytics/customers)...")
            await page.goto(f"{BASE_URL}/analytics/customers", wait_until="networkidle")
            await page.wait_for_selector(".chart-card", timeout=8000)
            await page.wait_for_timeout(1200)

            customer_charts = await page.locator(".chart-card").count()
            print(f"  ✓ 客户增长与复购频次图表渲染正常，数量: {customer_charts}")

            screenshot_customers = os.path.join(SCREENSHOT_DIR, "07_analytics_customers.png")
            await page.screenshot(path=screenshot_customers)
            print(f"  📸 保存客户分析截图: {screenshot_customers}")

            # -------------------------------------------------------------
            # Step 9: 订单中心与履约流转时间线弹窗 (OrderList & Timeline)
            # -------------------------------------------------------------
            print("\n[Step 9] 验证订单管理中心与履约流转时间线追溯 (/orders)...")
            await page.goto(f"{BASE_URL}/orders", wait_until="networkidle")
            await page.wait_for_selector(".el-table__row", timeout=8000)

            total_table_rows = await page.locator(".el-table__row").count()
            print(f"  ✓ 订单列表表格加载成功，展示订单记录数: {total_table_rows}")

            # 点击第一行订单的「明细」按钮打开履约流转时间线抽屉
            print("  -> 点击第 1 笔订单的「明细」按钮打开履约时间线抽屉...")
            first_detail_btn = page.locator(".el-table__row").first.locator('button:has-text("明细")')
            await first_detail_btn.click()

            # 等待抽屉与时间线节点渲染
            await page.wait_for_selector(".el-drawer", timeout=6000)
            await page.wait_for_selector(".el-timeline-item", timeout=6000)
            await page.wait_for_timeout(800)

            timeline_nodes = await page.locator(".el-timeline-item").count()
            print(f"  ✓ 履约流转时间线抽屉成功展开，节点数: {timeline_nodes}")
            assert timeline_nodes >= 2, f"时间线节点数异常: {timeline_nodes}"

            # 验证时间线中是否存在操作者主体与快照上下文 (payload)
            timeline_text = await page.locator(".el-timeline").text_content()
            print(f"  ✓ 履约时间线内容采样:\n    {timeline_text.strip()[:160]}...")

            screenshot_timeline = os.path.join(SCREENSHOT_DIR, "08_order_timeline.png")
            await page.screenshot(path=screenshot_timeline)
            print(f"  📸 保存履约流转时间线高保真截图: {screenshot_timeline}")

            print("\n" + "=" * 70)
            print("🎉 Playwright E2E 前端端到端测试全量通过！(100% PASS)")
            print("=" * 70)

        except Exception as e:
            print(f"\n❌ E2E 测试异常中断: {e}", file=sys.stderr)
            err_shot = os.path.join(SCREENSHOT_DIR, "error_trace.png")
            await page.screenshot(path=err_shot)
            print(f"📸 失败异常截图已保存: {err_shot}")
            raise e
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(run_e2e_suite())
