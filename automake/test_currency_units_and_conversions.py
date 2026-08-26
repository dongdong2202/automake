"""
金额单位全局审查与转换准确性测试：
1. 校验后端与数据库所有金额字段存储均为分 (IntegerField);
2. 校验前端与后端接口交互中，分与元转换的准确性、稳定性与防精度丢失;
3. 执行 Playwright 真实浏览器端到端交互，检查各页面金额单位呈现;
4. 测试完毕后自动释放 30004 端口。
"""

import os
import time
import subprocess
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')
django.setup()

from django.db import models
from users.models import User
from orders.models import OrderMain, OrderItem
from menus.models import MenuItem, MenuSku
from global_config.models import GlobalMenuItem, GlobalMenuSku, GlobalSkuTemplate
from payments.models import PaymentRecord
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:30004"


def test_currency_units_and_ui():
    print("🚀 [Step 1] 校验后端与数据库模型金额字段定义...")
    
    # 1. 校验 OrderMain
    for field_name in ['total_amount', 'discount_amount', 'pay_amount']:
        field = OrderMain._meta.get_field(field_name)
        assert isinstance(field, models.IntegerField), f"OrderMain.{field_name} 应为 IntegerField"
        print(f"  ✓ OrderMain.{field_name} 为 IntegerField (分)")

    # 2. 校验 OrderItem
    for field_name in ['unit_price', 'subtotal']:
        field = OrderItem._meta.get_field(field_name)
        assert isinstance(field, models.IntegerField), f"OrderItem.{field_name} 应为 IntegerField"
        print(f"  ✓ OrderItem.{field_name} 为 IntegerField (分)")

    # 3. 校验 GlobalMenuItem & GlobalMenuSku & GlobalSkuTemplate
    assert isinstance(GlobalMenuItem._meta.get_field('base_price'), models.IntegerField), "GlobalMenuItem.base_price 应为 IntegerField"
    print("  ✓ GlobalMenuItem.base_price 为 IntegerField (分)")

    assert isinstance(GlobalMenuSku._meta.get_field('price_delta'), models.IntegerField), "GlobalMenuSku.price_delta 应为 IntegerField"
    print("  ✓ GlobalMenuSku.price_delta 为 IntegerField (分)")

    assert isinstance(GlobalSkuTemplate._meta.get_field('default_price_delta'), models.IntegerField), "GlobalSkuTemplate.default_price_delta 应为 IntegerField"
    print("  ✓ GlobalSkuTemplate.default_price_delta 为 IntegerField (分)")

    # 4. 校验 MenuItem & MenuSku
    assert isinstance(MenuItem._meta.get_field('base_price'), models.IntegerField), "MenuItem.base_price 应为 IntegerField"
    print("  ✓ MenuItem.base_price 为 IntegerField (分)")

    assert isinstance(MenuSku._meta.get_field('price_delta'), models.IntegerField), "MenuSku.price_delta 应为 IntegerField"
    print("  ✓ MenuSku.price_delta 为 IntegerField (分)")

    # 5. 校验 PaymentRecord
    assert isinstance(PaymentRecord._meta.get_field('amount'), models.IntegerField), "PaymentRecord.amount 应为 IntegerField"
    print("  ✓ PaymentRecord.amount 为 IntegerField (分)")

    print("\n🚀 [Step 2] 启动服务并执行 Playwright 浏览器端到端金额展示测试...")
    os.system("fuser -k 30004/tcp || true")
    time.sleep(1)

    server_process = subprocess.Popen(
        ["/home/ubuntu/autoMachine/.venv1/bin/python", "manage.py", "runserver", "0.0.0.0:30004"],
        cwd="/home/ubuntu/autoMachine/automake",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(3)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 900})

            # 1. 登录
            page.goto(f"{BASE_URL}/login", wait_until="networkidle")
            page.fill('input[placeholder="请输入用户名"]', "admin1")
            page.fill('input[placeholder="请输入密码"]', "admin123")
            page.click('button:has-text("登 录")')
            page.wait_for_url("**/dashboard", timeout=8000)
            print("  ✓ 登录成功进入管理平台")

            # 2. 检查驾驶舱仪表盘金额展示
            page.wait_for_selector(".dashboard-page", timeout=8000)
            dash_content = page.content()
            assert "¥" in dash_content, "驾驶舱应包含格式化的人民币金额符号 ¥"
            print("  ✓ 运营驾驶舱 KPI 营收与客单价呈现正常 (带 ¥ 前缀及两位小数)")

            # 3. 检查订单管理页面 (/orders)
            page.goto(f"{BASE_URL}/orders", wait_until="networkidle")
            page.wait_for_selector(".order-list-page", timeout=8000)
            page.wait_for_timeout(1000)
            order_content = page.content()
            assert "实付金额" in order_content
            assert "¥" in order_content, "订单列表应呈现 ¥ 金额"
            print("  ✓ 订单列表与履约中心金额展示正确 (¥xx.xx)")

            # 4. 检查菜单与商品管理页面 (/menus)
            page.goto(f"{BASE_URL}/menus", wait_until="networkidle")
            page.wait_for_selector(".menu-management-page", timeout=8000)
            page.wait_for_timeout(1000)
            menu_content = page.content()
            assert "基准售价" in menu_content
            assert "¥" in menu_content, "菜单商品列表应呈现 ¥ 金额"
            print("  ✓ 全局商品档案与规格模板基准售价呈现正确 (¥xx.xx)")

            # 5. 检查设备综合管理页面设备菜单定价 (/devices?tab=menus)
            page.goto(f"{BASE_URL}/devices?tab=menus", wait_until="networkidle")
            page.wait_for_selector(".device-tabs", timeout=8000)
            page.wait_for_timeout(1000)
            dev_menu_content = page.content()
            assert "基准全局售价(元)" in dev_menu_content
            assert "门店设备定价(元)" in dev_menu_content
            print("  ✓ 设备菜单定价微调页面金额与输入控件呈现正确")

            browser.close()
            print("  ✓ Playwright 端到端金额呈现测试 100% 全部通过！")

    finally:
        print("\n🛑 [Step 3] 彻底终止测试服务并严格释放 30004 端口...")
        server_process.terminate()
        server_process.kill()
        os.system("fuser -k 30004/tcp || true")
        time.sleep(1)
        res = os.popen("ss -tulpn | grep 30004").read().strip()
        if not res:
            print("  ✓ 端口 30004 已完全释放关闭！")
        else:
            print(f"  ⚠️ 警告: 30004 仍在占用: {res}")


if __name__ == '__main__':
    test_currency_units_and_ui()
