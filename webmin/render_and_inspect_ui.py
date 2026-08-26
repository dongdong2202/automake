"""
AutoMake 微信小程序全页面高保真视觉渲染与 Playwright 自动截图审查引擎
"""

import os
import re
import json
import asyncio
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading
from playwright.async_api import async_playwright

WORKSPACE_DIR = "/home/ubuntu/autoMachine"
WEBMIN_DIR = "/home/ubuntu/autoMachine/webmin"
ARTIFACTS_DIR = "/home/ubuntu/.gemini/antigravity-cli/brain/d4d72c2a-627e-480f-aea5-921f9dbcb2c4"
PREVIEW_DIR = "/home/ubuntu/autoMachine/webmin/.preview_build"

os.makedirs(PREVIEW_DIR, exist_ok=True)
os.makedirs(ARTIFACTS_DIR, exist_ok=True)


def rpx_to_px(css_text):
    """
    将 WXSS 中的 rpx 转换为标准的 px (以 390px 视口为基准: 1rpx = 390/750 = 0.52px)
    """
    def replace_rpx(match):
        num = float(match.group(1))
        px = round(num * (390.0 / 750.0), 2)
        return f"{px}px"
    
    converted = re.sub(r'(\d+(?:\.\d+)?)rpx', replace_rpx, css_text)
    converted = re.sub(r'\bpage\b', 'body, .page-container', converted)
    return converted


def load_all_css():
    """合并 app.wxss 和公共样式"""
    app_wxss_path = os.path.join(WEBMIN_DIR, "app.wxss")
    css_content = ""
    if os.path.exists(app_wxss_path):
        with open(app_wxss_path, 'r', encoding='utf-8') as f:
            css_content += rpx_to_px(f.read()) + "\n"
    
    base_reset = """
    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      -webkit-tap-highlight-color: transparent;
    }
    body {
      width: 100%;
      max-width: 390px;
      margin: 0 auto;
      background-color: #f6f7f9;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      color: #1e293b;
      -webkit-font-smoothing: antialiased;
      overflow-x: hidden;
    }
    view, scroll-view, swiper, swiper-item, block {
      display: block;
      box-sizing: border-box;
    }
    text {
      display: inline;
    }
    image {
      display: inline-block;
      overflow: hidden;
      object-fit: cover;
    }
    button {
      border: none;
      background: none;
      padding: 0;
      margin: 0;
      font-size: inherit;
      color: inherit;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      white-space: nowrap;
      flex-shrink: 0;
    }
    button::after {
      display: none;
    }
    input {
      border: none;
      outline: none;
      background: transparent;
      font-family: inherit;
    }
    /* 底部导航 TabBar 模拟 */
    .mock-tabbar {
      position: fixed;
      bottom: 0;
      left: 50%;
      transform: translateX(-50%);
      width: 100%;
      max-width: 390px;
      height: 54px;
      background: #ffffff;
      border-top: 1px solid #e2e8f0;
      display: flex;
      justify-content: space-around;
      align-items: center;
      z-index: 999;
      box-shadow: 0 -2px 10px rgba(0,0,0,0.03);
    }
    .mock-tab-item {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      flex: 1;
      font-size: 11px;
      color: #94a3b8;
      cursor: pointer;
    }
    .mock-tab-item.active {
      color: #ff6b00;
      font-weight: 600;
    }
    .mock-tab-icon {
      width: 22px;
      height: 22px;
      margin-bottom: 2px;
    }
    /* 顶部导航条模拟 */
    .mock-navbar {
      position: sticky;
      top: 0;
      width: 100%;
      height: 48px;
      background: #ffffff;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 16px;
      font-size: 16px;
      font-weight: 700;
      color: #0f172a;
      border-bottom: 1px solid #f1f5f9;
      z-index: 998;
    }
    .mock-nav-title {
      font-size: 16px;
      font-weight: 700;
    }
    .mock-nav-actions {
      display: flex;
      gap: 12px;
      font-size: 14px;
    }
    """
    return base_reset + "\n" + css_content


def generate_html(title, page_css, body_html, active_tab="home"):
    all_css = load_all_css() + "\n" + rpx_to_px(page_css)
    
    tabs = [
        {"key": "home", "title": "首页", "icon": "/images/tab_home.png", "active_icon": "/images/tab_home_active.png"},
        {"key": "menu", "title": "点餐", "icon": "/images/tab_menu.png", "active_icon": "/images/tab_menu_active.png"},
        {"key": "orders", "title": "订单", "icon": "/images/tab_order.png", "active_icon": "/images/tab_order_active.png"},
        {"key": "my", "title": "我的", "icon": "/images/tab_user.png", "active_icon": "/images/tab_user_active.png"},
    ]
    
    tabbar_html = '<div class="mock-tabbar">'
    for t in tabs:
        is_active = (t["key"] == active_tab)
        cls = "mock-tab-item active" if is_active else "mock-tab-item"
        icon_src = t["active_icon"] if is_active else t["icon"]
        tabbar_html += f'''
        <div class="{cls}">
          <img class="mock-tab-icon" src="{icon_src}" alt="{t['title']}" />
          <span>{t['title']}</span>
        </div>
        '''
    tabbar_html += '</div>'
    
    full_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>{title}</title>
  <style>
    {all_css}
  </style>
</head>
<body>
  <div class="mock-navbar">
    <span class="mock-nav-title">{title}</span>
    <div class="mock-nav-actions">
      <span>•••</span>
      <span>⭕</span>
    </div>
  </div>
  <div class="page-container">
    {body_html}
  </div>
  {tabbar_html if active_tab else ""}
</body>
</html>"""
    return full_html


# 针对各个页面的高保真渲染模板
PAGES_TO_RENDER = {
    # 1. 首页列表模式
    "ui_01_index_list": {
        "title": "AutoMake 智能现制茶饮",
        "active_tab": "home",
        "css_file": "pages/index/index.wxss",
        "html": """
        <div class="container index-page safe-bottom">
          <!-- 搜索与城市 -->
          <div class="header-search-bar flex-between">
            <div class="city-selector flex-row">
              <span class="city-name">北京市</span>
              <span class="arrow-down">▼</span>
            </div>
            <div class="search-input-wrap flex-row">
              <span class="search-icon">🔍</span>
              <input class="search-input" placeholder="搜索附近设备、门店或写字楼" value="" />
            </div>
            <div class="view-switch-btns flex-row">
              <div class="switch-btn active"><span>列表</span></div>
              <div class="switch-btn"><span>地图</span></div>
            </div>
          </div>

          <!-- Banner 轮播 -->
          <div class="banner-section">
            <div class="banner-swiper" style="height: 156px; border-radius: 12px; overflow: hidden; position: relative;">
              <img class="banner-image" src="/images/banner1.png" style="width: 100%; height: 100%; object-fit: cover;" />
            </div>
          </div>

          <!-- 离我最近门店 Hero 卡片 -->
          <div class="store-hero-card card">
            <div class="store-header flex-between">
              <div class="store-title-wrap">
                <div class="store-name-row flex-row">
                  <span class="store-name">模拟智能自营店</span>
                  <span class="tag tag-success">营业中</span>
                </div>
                <span class="store-address">北京市海淀区西二旗软件园中关村软件园二期</span>
              </div>
              <div class="distance-pill flex-col flex-center">
                <span class="dist-num">120m</span>
                <span class="dist-label">离我最近</span>
              </div>
            </div>

            <div class="store-meta-row flex-between">
              <div class="meta-item flex-row">
                <span class="meta-icon">⏰</span>
                <span class="meta-text">营业时间: 08:00 - 22:00</span>
              </div>
              <div class="meta-item flex-row">
                <span class="meta-icon">🤖</span>
                <span class="meta-text">智能无人现制茶饮机</span>
              </div>
            </div>

            <div class="store-actions flex-row">
              <button class="btn-nav flex-center">
                <span class="btn-icon">🧭</span>
                <span>地图导航</span>
              </button>
              <button class="btn-order flex-center btn-primary">
                <span class="btn-icon">☕</span>
                <span>进入点餐</span>
              </button>
            </div>
          </div>

          <!-- 快捷功能四大入口 -->
          <div class="quick-nav-card card flex-between">
            <div class="quick-item flex-col flex-center">
              <div class="quick-icon-bg bg-orange">☕</div>
              <span class="quick-label">点单自提</span>
            </div>
            <div class="quick-item flex-col flex-center">
              <div class="quick-icon-bg bg-green">⚡</div>
              <span class="quick-label">扫码取餐</span>
            </div>
            <div class="quick-item flex-col flex-center">
              <div class="quick-icon-bg bg-blue">🎁</div>
              <span class="quick-label">领券中心</span>
            </div>
            <div class="quick-item flex-col flex-center">
              <div class="quick-icon-bg bg-purple">👑</div>
              <span class="quick-label">会员积分</span>
            </div>
          </div>

          <!-- 周边设备列表 -->
          <div class="other-stores-section">
            <div class="section-title-row flex-between">
              <span class="section-title">周边智能设备与门店 (3)</span>
              <div class="relocate-text flex-row"><span>🎯 重新定位</span></div>
            </div>

            <div class="other-store-card card">
              <div class="flex-between">
                <div class="other-store-info">
                  <div class="other-store-title-row">
                    <span class="other-store-name">西二旗智能咖啡店</span>
                    <span class="tag tag-primary">营业中</span>
                  </div>
                  <span class="other-store-addr">北京市海淀区西二旗软件园 10 号楼</span>
                  <span class="other-store-time">⏰ 09:00 - 21:30</span>
                </div>
                <div class="other-store-side flex-col">
                  <span class="side-dist">450m</span>
                  <div class="side-actions flex-row">
                    <button class="btn-sm btn-outline" style="margin-right: 4px;">导航</button>
                    <button class="btn-sm btn-primary">去点餐</button>
                  </div>
                </div>
              </div>
            </div>

            <div class="other-store-card card">
              <div class="flex-between">
                <div class="other-store-info">
                  <div class="other-store-title-row">
                    <span class="other-store-name">北京1店 (望京SOHO设备)</span>
                    <span class="tag tag-primary">营业中</span>
                  </div>
                  <span class="other-store-addr">北京市朝阳区望京SOHO T1 智能售饮区</span>
                  <span class="other-store-time">⏰ 08:00 - 22:00</span>
                </div>
                <div class="other-store-side flex-col">
                  <span class="side-dist">1.2km</span>
                  <div class="side-actions flex-row">
                    <button class="btn-sm btn-outline" style="margin-right: 4px;">导航</button>
                    <button class="btn-sm btn-primary">去点餐</button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div class="brand-footer flex-col flex-center" style="margin-bottom: 60px;">
            <span class="footer-title">AutoMake 智能无人现制茶饮</span>
            <span class="footer-desc">全自动化萃取 · 毫秒级精准控温 · 30秒立等可取</span>
          </div>
        </div>
        """
    },

    # 2. 菜单点餐页 (Menu)
    "ui_02_menu_catalog": {
        "title": "在线点单",
        "active_tab": "menu",
        "css_file": "pages/menu/menu.wxss",
        "html": """
        <div class="container menu-page" style="height: 100vh; display: flex; flex-direction: column; overflow: hidden;">
          <!-- 顶部门店信息 -->
          <div class="store-top-bar flex-between">
            <div class="store-info flex-row">
              <span class="store-icon">🏬</span>
              <div class="store-title-box">
                <div class="flex-row">
                  <span class="store-name">模拟智能自营店</span>
                  <span class="tag tag-success">营业中</span>
                </div>
                <span class="store-hours">⏰ 营业时间: 08:00 - 22:00</span>
              </div>
            </div>
            <div class="store-top-right flex-row">
              <div class="hide-sold-btn"><span>隐藏售罄</span></div>
              <div class="switch-store-btn flex-row"><span>切换</span><span class="arrow-right">›</span></div>
            </div>
          </div>

          <!-- 活动专区横幅 -->
          <div class="menu-campaign-bar flex-between">
            <div class="campaign-chip flex-row">
              <span class="chip-icon">🔥</span>
              <span class="chip-text">秋季新品专区 · 现制鲜爽</span>
            </div>
            <span class="campaign-badge">自提免打包费</span>
          </div>

          <!-- 左右联动菜单主体 -->
          <div class="menu-main-wrap" style="flex: 1; display: flex; overflow: hidden; margin-bottom: 54px;">
            <!-- 左侧分类 -->
            <div class="category-sidebar">
              <div class="category-item flex-row active">
                <span class="cat-active-bar"></span>
                <span class="category-name">人气咖啡</span>
              </div>
              <div class="category-item flex-row">
                <span class="category-name">现萃原叶茶</span>
              </div>
              <div class="category-item flex-row">
                <span class="category-name">鲜果现榨</span>
              </div>
              <div class="category-item flex-row">
                <span class="category-name">特调冰沙</span>
              </div>
            </div>

            <!-- 右侧商品列表 -->
            <div class="product-scroll" style="flex: 1; background: #ffffff; padding: 10px; overflow-y: auto;">
              <div class="category-group-header">
                <span class="group-title">人气咖啡</span>
              </div>

              <!-- 商品 1 -->
              <div class="product-card card flex-row">
                <img class="product-thumb" src="/images/drink_coffee.png" />
                <div class="product-info flex-col">
                  <div class="product-title-row"><span class="product-name">生椰拿铁 (经典爆款)</span></div>
                  <span class="product-desc">100% 阿拉比卡咖啡豆，搭配鲜榨厚椰乳，醇香丝滑。</span>
                  <div class="product-bottom-row flex-between">
                    <div class="price-box">
                      <span class="symbol">¥</span>
                      <span class="integer">18</span>
                      <span class="decimal">.00</span>
                      <span class="price-suffix">起</span>
                    </div>
                    <button class="btn-sku-select">选规格</button>
                  </div>
                </div>
              </div>

              <!-- 商品 2 -->
              <div class="product-card card flex-row">
                <img class="product-thumb" src="/images/drink_tea.png" />
                <div class="product-info flex-col">
                  <div class="product-title-row"><span class="product-name">美式浓缩 (深度烘焙)</span></div>
                  <span class="product-desc">微酸微苦，焦糖香气浓郁，提神醒脑无负担。</span>
                  <div class="product-bottom-row flex-between">
                    <div class="price-box">
                      <span class="symbol">¥</span>
                      <span class="integer">12</span>
                      <span class="decimal">.00</span>
                    </div>
                    <button class="btn-sku-select">选规格</button>
                  </div>
                </div>
              </div>

              <div class="category-group-header" style="margin-top: 15px;">
                <span class="group-title">现萃原叶茶</span>
              </div>

              <!-- 商品 3 -->
              <div class="product-card card flex-row">
                <img class="product-thumb" src="/images/drink_fruit.png" />
                <div class="product-info flex-col">
                  <div class="product-title-row"><span class="product-name">鸭屎香柠檬茶 (手打鲜作)</span></div>
                  <span class="product-desc">精选广东高山乌龙茶，现切香水柠檬手捣暴打。</span>
                  <div class="product-bottom-row flex-between">
                    <div class="price-box">
                      <span class="symbol">¥</span>
                      <span class="integer">15</span>
                      <span class="decimal">.00</span>
                    </div>
                    <button class="btn-sku-select">选规格</button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 底部悬浮购物车 -->
          <div class="cart-floating-bar-wrap safe-bottom" style="position: fixed; bottom: 58px; left: 0; right: 0; z-index: 990;">
            <div class="cart-floating-bar flex-between">
              <div class="cart-bar-left flex-row">
                <div class="cart-icon-wrap">
                  <span class="cart-icon">🛒</span>
                  <span class="cart-badge">2</span>
                </div>
                <div class="cart-price-info flex-col">
                  <div class="price-box">
                    <span class="symbol">¥</span>
                    <span class="integer">33</span>
                    <span class="decimal">.00</span>
                  </div>
                  <span class="cart-delivery-tip">自提免包装费</span>
                </div>
              </div>
              <button class="btn-checkout btn-primary">去结算 ›</button>
            </div>
          </div>
        </div>
        """
    },

    # 3. 商品大图详情页 (Product Detail)
    "ui_03_product_detail": {
        "title": "商品详情",
        "active_tab": "",
        "css_file": "pages/product-detail/product-detail.wxss",
        "html": """
        <div class="container product-detail-page safe-bottom">
          <!-- 顶部大图轮播 -->
          <div class="detail-gallery-wrap" style="height: 220px; border-radius: 16px; overflow: hidden; margin-bottom: 12px; background: #ffffff; display: flex; align-items: center; justify-content: center;">
            <img class="gallery-image" src="/images/drink_coffee.png" style="width: 200px; height: 200px; object-fit: contain;" />
          </div>

          <!-- 基础信息卡片 -->
          <div class="product-base-card card">
            <div class="flex-between">
              <span class="detail-title">生椰拿铁 (经典爆款)</span>
              <span class="tag tag-primary">现制精萃</span>
            </div>
            <span class="detail-desc">精选 100% 阿拉比卡咖啡豆，搭配鲜榨厚椰乳与天然纯净水，毫秒级精准控温萃取，现点现制立享香浓。</span>
            <div class="price-row flex-between">
              <div class="price-box">
                <span class="symbol">¥</span>
                <span class="integer">18</span>
                <span class="decimal">.00</span>
              </div>
              <span class="price-desc-text">💡 规格差价将在选择后实时计算</span>
            </div>
          </div>

          <!-- 原料与品质说明卡片 -->
          <div class="product-info-card card">
            <span class="card-section-title">🌿 原料与品质说明</span>
            <div class="ingredients-box">
              <span class="ing-label">主要原料：</span>
              <span class="ing-content">阿拉比卡浓缩咖啡液、特调生椰厚乳、纯净水、天然果糖</span>
            </div>
            <div class="feature-tags-wrap flex-row">
              <div class="feature-tag">✔ 0 反式脂肪酸</div>
              <div class="feature-tag">✔ 100% 真奶现萃</div>
              <div class="feature-tag">✔ 现点现磨</div>
            </div>
          </div>

          <!-- 规格与定制卡片 -->
          <div class="sku-selector-card card">
            <span class="card-section-title">⚙️ 专属定制规格</span>

            <div class="sku-group">
              <span class="group-name">杯型规格</span>
              <div class="pills-container flex-row">
                <div class="pill-item active"><span class="pill-title">中杯 (450ml)</span></div>
                <div class="pill-item"><span class="pill-title">大杯 (650ml)</span><span class="pill-delta">+¥3.00</span></div>
              </div>
            </div>

            <div class="sku-group">
              <span class="group-name">温度选择</span>
              <div class="pills-container flex-row">
                <div class="pill-item active"><span class="pill-title">标准冰</span></div>
                <div class="pill-item"><span class="pill-title">少冰</span></div>
                <div class="pill-item"><span class="pill-title">温热 (55℃)</span></div>
              </div>
            </div>

            <div class="sku-group">
              <span class="group-name">甜度选择</span>
              <div class="pills-container flex-row">
                <div class="pill-item"><span class="pill-title">标准糖</span></div>
                <div class="pill-item active"><span class="pill-title">半糖 (推荐)</span></div>
                <div class="pill-item"><span class="pill-title">不加糖</span></div>
              </div>
            </div>

            <div class="quantity-row flex-between">
              <span class="group-name" style="margin-bottom: 0;">购买数量</span>
              <div class="quantity-stepper flex-row">
                <div class="step-btn step-minus">-</div>
                <span class="step-num">1</span>
                <div class="step-btn step-plus">+</div>
              </div>
            </div>
          </div>

          <!-- 底部固定结算条 -->
          <div class="detail-bottom-bar-wrap safe-bottom" style="position: fixed; bottom: 0; left: 0; right: 0; background: #fff; padding: 12px 16px; border-top: 1px solid #e2e8f0; z-index: 100;">
            <div class="detail-bottom-bar flex-between">
              <div class="total-price-box flex-row">
                <span class="total-label">合计:</span>
                <div class="price-box">
                  <span class="symbol">¥</span>
                  <span class="integer">18</span>
                  <span class="decimal">.00</span>
                </div>
              </div>
              <div class="action-btn-group flex-row" style="gap: 8px;">
                <button class="btn-outline btn-add">加入购物车</button>
                <button class="btn-primary btn-buy">立即购买</button>
              </div>
            </div>
          </div>
        </div>
        """
    },

    # 4. 购物车与结算页 (Cart)
    "ui_04_cart_checkout": {
        "title": "确认订单",
        "active_tab": "",
        "css_file": "pages/cart/cart.wxss",
        "html": """
        <div class="container cart-page safe-bottom">
          <!-- 自提门店卡片 -->
          <div class="store-card card">
            <div class="flex-between">
              <div class="store-info flex-col">
                <div class="flex-row">
                  <span class="tag tag-primary">到店自提</span>
                  <span class="store-name">模拟智能自营店</span>
                </div>
                <span class="store-address">北京市海淀区西二旗软件园中关村软件园二期</span>
              </div>
              <span class="store-badge">🤖 智能现制</span>
            </div>
          </div>

          <!-- 商品明细卡片 -->
          <div class="goods-card card">
            <div class="goods-header flex-between">
              <span class="section-title">点单明细 (2 件)</span>
              <div class="clear-btn flex-row">
                <span class="clear-icon">🗑️</span>
                <span>清空</span>
              </div>
            </div>

            <div class="goods-list">
              <div class="goods-item-row flex-between">
                <img class="goods-thumb" src="/images/drink_coffee.png" />
                <div class="goods-main flex-col">
                  <span class="goods-name">生椰拿铁 (经典爆款)</span>
                  <span class="goods-sku">大杯 (650ml) / 少冰 / 半糖</span>
                  <span class="goods-unit-price">¥21.00</span>
                </div>
                <div class="goods-right flex-col">
                  <span class="goods-subtotal">¥21.00</span>
                  <div class="quantity-stepper flex-row">
                    <div class="step-btn step-minus">-</div>
                    <span class="step-num">1</span>
                    <div class="step-btn step-plus">+</div>
                  </div>
                </div>
              </div>

              <div class="goods-item-row flex-between">
                <img class="goods-thumb" src="/images/drink_tea.png" />
                <div class="goods-main flex-col">
                  <span class="goods-name">美式浓缩 (深度烘焙)</span>
                  <span class="goods-sku">中杯 (450ml) / 标准冰 / 不加糖</span>
                  <span class="goods-unit-price">¥12.00</span>
                </div>
                <div class="goods-right flex-col">
                  <span class="goods-subtotal">¥12.00</span>
                  <div class="quantity-stepper flex-row">
                    <div class="step-btn step-minus">-</div>
                    <span class="step-num">1</span>
                    <div class="step-btn step-plus">+</div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 优惠券选择卡片 -->
          <div class="coupon-select-card card flex-between">
            <div class="flex-row">
              <span class="coupon-icon">🎁</span>
              <span class="coupon-title">优惠卡券</span>
            </div>
            <div class="flex-row">
              <span class="coupon-selected-text text-danger">-¥5.00 (新人专享立减券)</span>
              <span class="arrow-right">›</span>
            </div>
          </div>

          <!-- 订单备注 -->
          <div class="remark-card card flex-between">
            <span class="remark-label">订单备注</span>
            <input class="remark-input" placeholder="如有特殊需求请输入 (例如: 不放吸管)" value="少放冰块，谢谢" />
          </div>

          <!-- 电子发票卡片 -->
          <div class="invoice-section-card card">
            <div class="invoice-switch-row flex-between">
              <div class="flex-row">
                <span class="invoice-icon">🧾</span>
                <span class="invoice-title">开具电子发票</span>
              </div>
              <span class="tag tag-primary" style="background:#ff6b00; color:#fff;">已开启</span>
            </div>

            <div class="invoice-form-box">
              <div class="invoice-type-group flex-row" style="margin-bottom: 8px;">
                <label class="radio-label flex-row" style="margin-right: 15px;">
                  <span style="color:#ff6b00; margin-right:4px;">●</span> 个人
                </label>
                <label class="radio-label flex-row">
                  <span style="color:#94a3b8; margin-right:4px;">○</span> 企业单位
                </label>
              </div>
              <input class="invoice-input" placeholder="发票抬头名称" value="张三" />
              <input class="invoice-input" placeholder="电子发票接收邮箱" value="zhangsan@example.com" />
            </div>
          </div>

          <!-- 金额明细 -->
          <div class="amount-card card" style="margin-bottom: 40px;">
            <div class="amount-row flex-between">
              <span class="amount-label">商品总额</span>
              <span class="amount-value">¥33.00</span>
            </div>
            <div class="amount-row flex-between">
              <span class="amount-label">打包耗材费</span>
              <span class="amount-value text-free">免费</span>
            </div>
            <div class="amount-row flex-between">
              <span class="amount-label">优惠抵扣</span>
              <span class="amount-value text-discount">-¥5.00</span>
            </div>
            <div class="amount-divider"></div>
            <div class="amount-total-row flex-between">
              <span class="total-label">实付总额</span>
              <div class="price-box">
                <span class="symbol">¥</span>
                <span class="integer">28</span>
                <span class="decimal">.00</span>
              </div>
            </div>
          </div>

          <!-- 底部支付条 -->
          <div class="checkout-footer-wrap safe-bottom">
            <div class="checkout-footer flex-between">
              <div class="footer-price-info flex-row">
                <span class="pay-text">应付:</span>
                <div class="price-box">
                  <span class="symbol">¥</span>
                  <span class="integer">28</span>
                  <span class="decimal">.00</span>
                </div>
                <span class="discount-tip">已省¥5.00</span>
              </div>
              <button class="btn-primary btn-submit-pay">立即支付</button>
            </div>
          </div>
        </div>
        """
    },

    # 5. 订单列表页 (Orders)
    "ui_05_orders_list": {
        "title": "我的订单",
        "active_tab": "orders",
        "css_file": "pages/orders/orders.wxss",
        "html": """
        <div class="container orders-page safe-bottom">
          <!-- 状态筛选 Tab -->
          <div class="order-tabs-wrap flex-row" style="background:#fff; padding: 12px 16px; border-bottom: 1px solid #f1f5f9; justify-content: space-around;">
            <div class="tab-item active" style="color: #ff6b00; font-weight: 700;"><span>全部</span></div>
            <div class="tab-item" style="color: #64748b;"><span>待支付</span></div>
            <div class="tab-item" style="color: #64748b;"><span>制作中</span></div>
            <div class="tab-item" style="color: #64748b;"><span>已完成</span></div>
            <div class="tab-item" style="color: #64748b;"><span>退款</span></div>
          </div>

          <div class="order-list-body" style="padding: 12px 14px;">
            <!-- 订单卡片 1 (制作中) -->
            <div class="order-card card">
              <div class="order-card-header flex-between">
                <div class="store-name-box flex-row">
                  <span class="store-icon">🏬</span>
                  <span class="order-store-name">模拟智能自营店</span>
                  <span class="arrow-right">›</span>
                </div>
                <span class="tag tag-primary">☕ 制作中 (排队1杯)</span>
              </div>

              <div class="order-goods-summary flex-between" style="padding: 10px 0;">
                <div class="goods-thumbnails flex-row" style="gap: 8px;">
                  <img class="goods-thumb" src="/images/drink_coffee.png" />
                  <img class="goods-thumb" src="/images/drink_tea.png" />
                </div>
                <div class="goods-count-price flex-col" style="align-items: flex-end;">
                  <div class="price-box">
                    <span class="symbol">¥</span>
                    <span class="integer">28</span>
                    <span class="decimal">.00</span>
                  </div>
                  <span class="total-count-text" style="font-size: 11px; color: #64748b;">共 2 杯</span>
                </div>
              </div>

              <div class="order-card-footer flex-between">
                <span class="order-time" style="font-size: 11px; color: #94a3b8;">下单: 2026-08-23 23:05</span>
                <div class="order-action-btns flex-row" style="gap: 8px;">
                  <button class="btn-sm btn-outline">取餐码: A088</button>
                  <button class="btn-sm btn-primary">查看进度</button>
                </div>
              </div>
            </div>

            <!-- 订单卡片 2 (已完成) -->
            <div class="order-card card">
              <div class="order-card-header flex-between">
                <div class="store-name-box flex-row">
                  <span class="store-icon">🏬</span>
                  <span class="order-store-name">西二旗智能咖啡店</span>
                  <span class="arrow-right">›</span>
                </div>
                <span class="tag tag-success">✅ 已完成</span>
              </div>

              <div class="order-goods-summary flex-between" style="padding: 10px 0;">
                <div class="goods-thumbnails flex-row">
                  <img class="goods-thumb" src="/images/drink_fruit.png" />
                </div>
                <div class="goods-count-price flex-col" style="align-items: flex-end;">
                  <div class="price-box">
                    <span class="symbol">¥</span>
                    <span class="integer">15</span>
                    <span class="decimal">.00</span>
                  </div>
                  <span class="total-count-text" style="font-size: 11px; color: #64748b;">共 1 杯</span>
                </div>
              </div>

              <div class="order-card-footer flex-between">
                <span class="order-time" style="font-size: 11px; color: #94a3b8;">下单: 2026-08-22 15:30</span>
                <div class="order-action-btns flex-row" style="gap: 8px;">
                  <button class="btn-sm btn-outline">申请发票</button>
                  <button class="btn-sm btn-primary">再来一单</button>
                </div>
              </div>
            </div>
          </div>
        </div>
        """
    },

    # 6. 订单详情与出餐追踪 (Order Detail)
    "ui_06_order_detail_tracking": {
        "title": "订单详情",
        "active_tab": "",
        "css_file": "pages/order-detail/order-detail.wxss",
        "html": """
        <div class="container order-detail-page safe-bottom">
          <!-- 状态与进度步骤条 -->
          <div class="order-status-hero card flex-col flex-center">
            <span class="making-title">☕ 饮品制作中，请稍候</span>
            <span class="making-wait-tip">智能设备正在萃取现制，预计等待 1 分钟</span>

            <!-- 大字取餐码 PASS 卡片 -->
            <div class="pickup-code-box flex-col flex-center" style="margin-top: 14px;">
              <span class="pickup-label">自提取餐码 (核销凭证)</span>
              <span class="pickup-code">A088</span>
              <span class="pickup-tip">出餐口: 01 号口 · 制作完成时将亮灯开仓</span>
            </div>

            <div class="steps-container flex-row" style="width: 100%; margin-top: 10px;">
              <div class="step-node flex-col flex-center active">
                <div class="node-circle flex-center">✓</div>
                <span class="node-title">已下单</span>
              </div>
              <div class="step-node flex-col flex-center active">
                <div class="node-circle flex-center">✓</div>
                <span class="node-title">已支付</span>
              </div>
              <div class="step-node flex-col flex-center active">
                <div class="node-circle flex-center">⚙️</div>
                <span class="node-title">制作中</span>
              </div>
              <div class="step-node flex-col flex-center">
                <div class="node-circle flex-center">4</div>
                <span class="node-title">待取餐</span>
              </div>
            </div>
          </div>

          <!-- 门店与自提信息 -->
          <div class="store-nav-card card flex-between">
            <div class="store-nav-info flex-col">
              <span class="store-nav-name">模拟智能自营店</span>
              <span class="store-nav-address">北京市海淀区西二旗软件园中关村软件园二期</span>
            </div>
            <button class="btn-sm btn-outline flex-row" style="min-width: 60px;">
              <span style="margin-right: 2px;">🧭</span>
              <span>导航</span>
            </button>
          </div>

          <!-- 商品明细卡片 -->
          <div class="goods-detail-card card">
            <div class="goods-header flex-between">
              <span class="section-title">点单商品清单</span>
              <span class="goods-count-label">共 2 件商品</span>
            </div>
            <div class="goods-item flex-between">
              <div class="goods-info flex-col">
                <span class="goods-name">生椰拿铁 (经典爆款)</span>
                <span class="goods-sku">大杯 (650ml) / 少冰 / 半糖</span>
              </div>
              <div class="goods-qty-sub flex-col" style="align-items: flex-end;">
                <span class="goods-subtotal">¥21.00</span>
                <span class="goods-qty">x1</span>
              </div>
            </div>
            <div class="goods-item flex-between">
              <div class="goods-info flex-col">
                <span class="goods-name">美式浓缩 (深度烘焙)</span>
                <span class="goods-sku">中杯 (450ml) / 标准冰 / 不加糖</span>
              </div>
              <div class="goods-qty-sub flex-col" style="align-items: flex-end;">
                <span class="goods-subtotal">¥12.00</span>
                <span class="goods-qty">x1</span>
              </div>
            </div>

            <div class="price-summary-box">
              <div class="summary-row flex-between"><span class="summary-label">商品总额</span><span class="summary-value">¥33.00</span></div>
              <div class="summary-row flex-between"><span class="summary-label">优惠抵扣</span><span class="summary-value text-discount">-¥5.00</span></div>
              <div class="summary-divider"></div>
              <div class="summary-total-row flex-between"><span class="total-text">实付总额</span><span class="total-price text-orange" style="font-size: 18px; font-weight: 700; color: #ff6b00;">¥28.00</span></div>
            </div>
          </div>

          <!-- 订单元信息 -->
          <div class="meta-card card">
            <div class="meta-row flex-between"><span class="meta-label">订单编号</span><span class="meta-value">2026082323050188</span></div>
            <div class="meta-row flex-between"><span class="meta-label">下单时间</span><span class="meta-value">2026-08-23 23:05:12</span></div>
            <div class="meta-row flex-between"><span class="meta-label">支付时间</span><span class="meta-value">2026-08-23 23:05:18</span></div>
            <div class="meta-row flex-between"><span class="meta-label">电子发票</span><span class="text-orange" style="font-weight: 600; color: #ff6b00;">已开具 (点击查看凭据) ›</span></div>
          </div>

          <!-- 底部固定操作按钮 -->
          <div class="order-action-footer-wrap safe-bottom">
            <div class="order-action-footer flex-between">
              <button class="btn-outline flex-center" style="color: #ef4444; border-color: #fecaca;">申请退款</button>
              <button class="btn-primary flex-center">再来一单</button>
            </div>
          </div>
        </div>
        """
    },

    # 7. 电子发票管理页 (Invoice)
    "ui_07_invoice_view": {
        "title": "电子发票",
        "active_tab": "",
        "css_file": "pages/invoice/invoice.wxss",
        "html": """
        <div class="container invoice-page safe-bottom">
          <div class="invoice-summary-card card">
            <div class="flex-between">
              <span class="card-title" style="font-weight: 700;">订单开票信息</span>
              <span class="tag tag-primary">已开具 (issued)</span>
            </div>
            <div class="summary-meta-row flex-between" style="margin-top: 10px; font-size: 13px;"><span class="meta-label">订单号</span><span class="meta-value">2026082323050188</span></div>
            <div class="summary-meta-row flex-between" style="margin-top: 6px; font-size: 13px;"><span class="meta-label">开票金额</span><span class="meta-value font-bold" style="color: #ff6b00; font-size: 16px;">¥28.00</span></div>
          </div>

          <div class="invoice-detail-card card">
            <span class="card-title" style="font-weight: 700;">🧾 电子发票凭据</span>
            <div class="detail-row flex-between" style="margin-top: 10px; font-size: 13px;"><span class="row-label" style="color:#64748b;">发票类型</span><span class="row-value">企业单位 (增值税电子普通发票)</span></div>
            <div class="detail-row flex-between" style="margin-top: 8px; font-size: 13px;"><span class="row-label" style="color:#64748b;">发票抬头</span><span class="row-value">北京智能自动化科技有限公司</span></div>
            <div class="detail-row flex-between" style="margin-top: 8px; font-size: 13px;"><span class="row-label" style="color:#64748b;">企业税号</span><span class="row-value">91110108MA00000000</span></div>
            <div class="detail-row flex-between" style="margin-top: 8px; font-size: 13px;"><span class="row-label" style="color:#64748b;">接收邮箱</span><span class="row-value">finance@automake.cn</span></div>
            <div class="detail-row flex-between" style="margin-top: 8px; font-size: 13px;"><span class="row-label" style="color:#64748b;">开具时间</span><span class="row-value">2026-08-23 23:05:22</span></div>

            <button class="btn-primary btn-download flex-center" style="width: 100%; margin-top: 18px;">
              <span>📋 复制电子发票 PDF 下载链接</span>
            </button>
          </div>
        </div>
        """
    },

    # 8. 优惠券中心 (Coupon)
    "ui_08_coupon_center": {
        "title": "优惠券中心",
        "active_tab": "",
        "css_file": "pages/coupon/coupon.wxss",
        "html": """
        <div class="container coupon-page safe-bottom">
          <div class="coupon-tabs-wrap flex-row" style="background:#fff; padding: 12px 16px; border-bottom: 1px solid #f1f5f9; justify-content: space-around;">
            <div class="tab-item active" style="color: #ff6b00; font-weight: 700;"><span>可用优惠券 (3)</span></div>
            <div class="tab-item" style="color: #64748b;"><span>🎁 领券中心</span></div>
            <div class="tab-item" style="color: #64748b;"><span>已使用</span></div>
            <div class="tab-item" style="color: #64748b;"><span>已过期</span></div>
          </div>

          <div class="coupon-list-body" style="padding: 12px 14px;">
            <div class="coupon-item card flex-between">
              <div class="coupon-left flex-row" style="gap: 12px;">
                <div class="amount-box flex-col flex-center" style="background: #fff7ed; padding: 10px 14px; border-radius: 12px;">
                  <span class="amount-num" style="font-size: 20px; font-weight: 800; color: #ff6b00;">¥5.00</span>
                  <span class="amount-type" style="font-size: 10px; color: #c2410c;">立减券</span>
                </div>
                <div class="coupon-meta flex-col">
                  <span class="coupon-title" style="font-weight: 700; font-size: 14px;">新人专享立减券</span>
                  <span class="coupon-desc" style="font-size: 11px; color: #64748b; margin-top: 2px;">全场无门槛立减</span>
                  <span class="coupon-validity" style="font-size: 10px; color: #94a3b8; margin-top: 2px;">有效期至: 2026-09-23</span>
                </div>
              </div>
              <button class="btn-sm btn-outline">去使用</button>
            </div>

            <div class="coupon-item card flex-between">
              <div class="coupon-left flex-row" style="gap: 12px;">
                <div class="amount-box flex-col flex-center" style="background: #fff7ed; padding: 10px 14px; border-radius: 12px;">
                  <span class="amount-num" style="font-size: 20px; font-weight: 800; color: #ff6b00;">8.5折</span>
                  <span class="amount-type" style="font-size: 10px; color: #c2410c;">折扣券</span>
                </div>
                <div class="coupon-meta flex-col">
                  <span class="coupon-title" style="font-weight: 700; font-size: 14px;">全场 8.5 折限时特惠</span>
                  <span class="coupon-desc" style="font-size: 11px; color: #64748b; margin-top: 2px;">满 ¥15.00 可用</span>
                  <span class="coupon-validity" style="font-size: 10px; color: #94a3b8; margin-top: 2px;">有效期至: 2026-09-01</span>
                </div>
              </div>
              <button class="btn-sm btn-outline">去使用</button>
            </div>

            <div class="coupon-item card flex-between">
              <div class="coupon-left flex-row" style="gap: 12px;">
                <div class="amount-box flex-col flex-center" style="background: #fff7ed; padding: 10px 14px; border-radius: 12px;">
                  <span class="amount-num" style="font-size: 20px; font-weight: 800; color: #ff6b00;">¥10.00</span>
                  <span class="amount-type" style="font-size: 10px; color: #c2410c;">满减券</span>
                </div>
                <div class="coupon-meta flex-col">
                  <span class="coupon-title" style="font-weight: 700; font-size: 14px;">下午茶满减大礼包</span>
                  <span class="coupon-desc" style="font-size: 11px; color: #64748b; margin-top: 2px;">满 ¥35.00 可用</span>
                  <span class="coupon-validity" style="font-size: 10px; color: #94a3b8; margin-top: 2px;">有效期至: 2026-08-30</span>
                </div>
              </div>
              <button class="btn-sm btn-outline">去使用</button>
            </div>
          </div>
        </div>
        """
    },

    # 9. 会员积分中心 (Points)
    "ui_09_points_center": {
        "title": "会员积分中心",
        "active_tab": "",
        "css_file": "pages/points/points.wxss",
        "html": """
        <div class="container points-page safe-bottom">
          <div class="points-hero-card card flex-between" style="background: linear-gradient(135deg, #1e293b 0%, #334155 100%); color: #ffffff; padding: 24px;">
            <div class="points-meta flex-col">
              <span class="hero-label" style="font-size: 12px; color: #94a3b8;">当前可用积分</span>
              <span class="hero-points" style="font-size: 36px; font-weight: 900; color: #f59e0b; margin: 4px 0;">128</span>
              <span class="hero-sub" style="font-size: 11px; color: #cbd5e1;">每消费 ¥1 可积 1 积分</span>
            </div>
            <div class="hero-badge flex-col flex-center" style="background: rgba(255,255,255,0.1); padding: 10px 16px; border-radius: 12px;">
              <span class="badge-icon" style="font-size: 24px;">👑</span>
              <span class="badge-title" style="font-size: 12px; font-weight: 600; color: #fef08a; margin-top: 2px;">VIP 黄金会员</span>
            </div>
          </div>

          <div class="exchange-section card">
            <span class="card-title" style="font-weight: 700;">🎁 积分好礼兑换</span>
            <div class="reward-list" style="margin-top: 10px;">
              <div class="reward-item flex-between" style="padding: 12px 0; border-bottom: 1px dashed #f1f5f9;">
                <div class="reward-info flex-col">
                  <span class="reward-title" style="font-weight: 600; font-size: 14px;">¥5 无门槛立减券</span>
                  <span class="reward-cost" style="font-size: 12px; color: #64748b; margin-top: 2px;">所需积分: <span style="color: #ff6b00; font-weight: 700;">50</span> 分</span>
                </div>
                <button class="btn-sm btn-primary">立即兑换</button>
              </div>
              <div class="reward-item flex-between" style="padding: 12px 0;">
                <div class="reward-info flex-col">
                  <span class="reward-title" style="font-weight: 600; font-size: 14px;">¥10 满减券 (满¥35可用)</span>
                  <span class="reward-cost" style="font-size: 12px; color: #64748b; margin-top: 2px;">所需积分: <span style="color: #ff6b00; font-weight: 700;">90</span> 分</span>
                </div>
                <button class="btn-sm btn-primary">立即兑换</button>
              </div>
            </div>
          </div>

          <div class="point-logs-section card">
            <span class="card-title" style="font-weight: 700;">📋 积分变动明细</span>
            <div class="log-list" style="margin-top: 10px;">
              <div class="log-item flex-between" style="padding: 10px 0; border-bottom: 1px dashed #f1f5f9;">
                <div class="log-info flex-col">
                  <span class="log-action" style="font-size: 13px; font-weight: 500;">点单消费奖励 (订单 202608232305)</span>
                  <span class="log-time" style="font-size: 11px; color: #94a3b8;">2026-08-23 23:05:18</span>
                </div>
                <span class="log-change font-bold" style="color: #10b981; font-size: 16px;">+28</span>
              </div>
              <div class="log-item flex-between" style="padding: 10px 0;">
                <div class="log-info flex-col">
                  <span class="log-action" style="font-size: 13px; font-weight: 500;">新会员注册赠送</span>
                  <span class="log-time" style="font-size: 11px; color: #94a3b8;">2026-08-20 10:00:00</span>
                </div>
                <span class="log-change font-bold" style="color: #10b981; font-size: 16px;">+100</span>
              </div>
            </div>
          </div>
        </div>
        """
    },

    # 10. 物料员与协调员工作台 (Staff)
    "ui_10_staff_workbench": {
        "title": "员工移动工作台",
        "active_tab": "",
        "css_file": "pages/staff/staff.wxss",
        "html": """
        <div class="container staff-page safe-bottom">
          <div class="role-switch-wrap flex-row">
            <div class="role-tab active"><span>📦 物料员 (补货录入)</span></div>
            <div class="role-tab"><span>🛠️ 协调员 (设备运维)</span></div>
          </div>

          <!-- 设备选择卡片 -->
          <div class="device-picker-card card">
            <div class="flex-between">
              <div class="device-info flex-col">
                <div class="device-selector flex-row">
                  <span class="device-name-text">北京1店 · 智能01号机</span>
                  <span class="arrow-down">▼</span>
                </div>
                <span class="device-meta-text">序列号: sn003 · 所属门店: 北京1店</span>
              </div>
              <button class="btn-sm btn-outline flex-row">
                <span style="margin-right: 2px;">📷</span>
                <span>扫码锁定</span>
              </button>
            </div>
            <div class="device-status-row flex-between">
              <span class="status-indicator online">● 在线运行中</span>
              <span class="heartbeat-text">心跳: 2026-08-23 23:06:09</span>
            </div>
          </div>

          <!-- 物料员耗材补料表格 -->
          <div class="material-mode-wrap">
            <div class="consumable-card card">
              <div class="flex-between" style="margin-bottom: 12px;">
                <span class="section-title">🥤 杯子与包装耗材补料</span>
                <span class="tip-text">补货后录入最新数量</span>
              </div>

              <div class="consumable-table">
                <div class="table-header flex-between">
                  <span class="col-name" style="flex: 2;">耗材品类</span>
                  <span class="col-curr" style="flex: 1.5; text-align: center;">当前剩余</span>
                  <span class="col-input" style="flex: 2; text-align: right;">补货后数量</span>
                </div>

                <div class="table-row flex-between">
                  <div class="col-name flex-col" style="flex: 2;">
                    <span class="c-name">大号纸杯 (650ml)</span>
                    <span class="c-code">paperL</span>
                  </div>
                  <div class="col-curr flex-row" style="flex: 1.5; justify-content: center;">
                    <span class="curr-num">120</span>
                    <span class="curr-unit">个</span>
                  </div>
                  <div class="col-input flex-row" style="flex: 2; justify-content: flex-end;">
                    <input class="stock-input" value="120" />
                    <span class="input-unit">个</span>
                  </div>
                </div>

                <div class="table-row flex-between warning-row" style="background: #fffbeb;">
                  <div class="col-name flex-col" style="flex: 2;">
                    <span class="c-name" style="color: #b45309;">中号纸杯 (450ml)</span>
                    <span class="c-code">paperM (低库存告警)</span>
                  </div>
                  <div class="col-curr flex-row" style="flex: 1.5; justify-content: center;">
                    <span class="curr-num" style="color: #ef4444;">15</span>
                    <span class="curr-unit">个</span>
                  </div>
                  <div class="col-input flex-row" style="flex: 2; justify-content: flex-end;">
                    <input class="stock-input" value="150" />
                    <span class="input-unit">个</span>
                  </div>
                </div>

                <div class="table-row flex-between">
                  <div class="col-name flex-col" style="flex: 2;">
                    <span class="c-name">杯盖耗材</span>
                    <span class="c-code">lid</span>
                  </div>
                  <div class="col-curr flex-row" style="flex: 1.5; justify-content: center;">
                    <span class="curr-num">180</span>
                    <span class="curr-unit">个</span>
                  </div>
                  <div class="col-input flex-row" style="flex: 2; justify-content: flex-end;">
                    <input class="stock-input" value="180" />
                    <span class="input-unit">个</span>
                  </div>
                </div>

                <div class="table-row flex-between">
                  <div class="col-name flex-col" style="flex: 2;">
                    <span class="c-name">封口膜 (整卷)</span>
                    <span class="c-code">membrane</span>
                  </div>
                  <div class="col-curr flex-row" style="flex: 1.5; justify-content: center;">
                    <span class="curr-num">250</span>
                    <span class="curr-unit">次</span>
                  </div>
                  <div class="col-input flex-row" style="flex: 2; justify-content: flex-end;">
                    <input class="stock-input" value="250" />
                    <span class="input-unit">次</span>
                  </div>
                </div>
              </div>

              <button class="btn-primary btn-save-stock" style="width: 100%;">
                确认提交并同步云端库存
              </button>
            </div>
          </div>
        </div>
        """
    },

    # 11. 个人中心 (My)
    "ui_11_user_profile": {
        "title": "个人中心",
        "active_tab": "my",
        "css_file": "pages/my/my.wxss",
        "html": """
        <div class="container profile-page safe-bottom">
          <!-- 用户 Hero 卡片 -->
          <div class="user-hero-card card flex-between">
            <div class="user-info-main flex-row">
              <img class="user-avatar" src="/images/default_avatar.png" />
              <div class="user-meta flex-col">
                <div class="user-name-row flex-row">
                  <span class="user-nickname">AutoMake VIP 用户</span>
                  <span class="edit-icon">✏️</span>
                </div>
                <div class="phone-row flex-row">
                  <span class="user-phone">📱 13812345678</span>
                </div>
                <div class="flex-row" style="margin-top: 4px;">
                  <span class="tag tag-primary user-role-tag">✨ VIP 会员 ▾</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 会员资产栏 -->
          <div class="member-assets-card card flex-between">
            <div class="asset-item flex-col flex-center">
              <span class="asset-num">128</span>
              <span class="asset-label">会员积分 ›</span>
            </div>
            <div class="asset-divider"></div>
            <div class="asset-item flex-col flex-center">
              <span class="asset-num text-orange" style="color: #ff6b00;">3 张</span>
              <span class="asset-label">优惠卡券 ›</span>
            </div>
            <div class="asset-divider"></div>
            <div class="asset-item flex-col flex-center">
              <span class="asset-num">全部</span>
              <span class="asset-label">我的订单 ›</span>
            </div>
          </div>

          <!-- 员工工作台入口 -->
          <div class="staff-portal-card card flex-between">
            <div class="portal-left flex-row">
              <span class="portal-icon">🛠️</span>
              <div class="portal-text flex-col">
                <span class="portal-title">物料员与协调员移动工作台</span>
                <span class="portal-desc">杯子耗材手动补料录入 · 设备重启与开仓取餐</span>
              </div>
            </div>
            <button class="btn-sm btn-primary">进入工作台</button>
          </div>

          <!-- 订单状态入口 -->
          <div class="order-nav-card card">
            <div class="order-nav-header flex-between">
              <span class="card-title">我的订单</span>
              <div class="flex-row">
                <span class="view-all-text">全部订单</span>
                <span class="arrow-right">›</span>
              </div>
            </div>

            <div class="order-nav-grid flex-between">
              <div class="order-nav-item flex-col flex-center">
                <div class="nav-icon-wrap">
                  <span class="nav-icon">⏳</span>
                </div>
                <span class="nav-label">待支付</span>
              </div>
              <div class="order-nav-item flex-col flex-center">
                <div class="nav-icon-wrap">
                  <span class="nav-icon">☕</span>
                  <span class="badge-dot bg-green">1</span>
                </div>
                <span class="nav-label">制作中/待取</span>
              </div>
              <div class="order-nav-item flex-col flex-center">
                <div class="nav-icon-wrap">
                  <span class="nav-icon">📋</span>
                </div>
                <span class="nav-label">历史订单</span>
              </div>
              <div class="order-nav-item flex-col flex-center">
                <div class="nav-icon-wrap">
                  <span class="nav-icon">🔄</span>
                </div>
                <span class="nav-label">退款/售后</span>
              </div>
            </div>
          </div>

          <!-- 服务列表 -->
          <div class="service-list-card card">
            <div class="service-cell flex-between">
              <div class="cell-left flex-row"><span class="cell-icon">🎁</span><span class="cell-text">领券中心与活动优惠</span></div>
              <span class="arrow-right">›</span>
            </div>
            <div class="service-cell flex-between">
              <div class="cell-left flex-row"><span class="cell-icon">👑</span><span class="cell-text">会员积分兑换好礼</span></div>
              <span class="arrow-right">›</span>
            </div>
            <div class="service-cell flex-between">
              <div class="cell-left flex-row"><span class="cell-icon">💬</span><span class="cell-text">在线客服与帮助</span></div>
              <span class="arrow-right">›</span>
            </div>
            <div class="service-cell flex-between">
              <div class="cell-left flex-row"><span class="cell-icon">ℹ️</span><span class="cell-text">关于 AutoMake 智能系统</span></div>
              <span class="arrow-right">›</span>
            </div>
          </div>

          <div class="logout-wrap" style="margin-bottom: 60px;">
            <button class="btn-logout" style="width: 100%;">退出当前登录</button>
          </div>
        </div>
        """
    }
}


class CustomHTTPHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEBMIN_DIR, **kwargs)
    
    def log_message(self, format, *args):
        pass


def start_static_server(port=30005):
    server = HTTPServer(('127.0.0.1', port), CustomHTTPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


async def capture_all_pages():
    print("==================================================================")
    print("🚀 启动静态预览服务器与 Playwright 移动端视觉审查渲染器...")
    print("==================================================================")
    
    server = start_static_server(30005)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        )
        context = await browser.new_context(
            viewport={'width': 390, 'height': 844},
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True
        )
        page = await context.new_page()

        for page_key, config in PAGES_TO_RENDER.items():
            print(f"📸 渲染并截取 UI: {config['title']} ({page_key})...")
            
            wxss_path = os.path.join(WEBMIN_DIR, config["css_file"])
            page_css = ""
            if os.path.exists(wxss_path):
                with open(wxss_path, 'r', encoding='utf-8') as f:
                    page_css = f.read()

            html_content = generate_html(
                title=config["title"],
                page_css=page_css,
                body_html=config["html"],
                active_tab=config.get("active_tab", "")
            )

            html_file = os.path.join(PREVIEW_DIR, f"{page_key}.html")
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(html_content)

            await page.goto(f"http://127.0.0.1:30005/.preview_build/{page_key}.html", wait_until="networkidle")
            await page.wait_for_timeout(300)

            screenshot_path = os.path.join(ARTIFACTS_DIR, f"{page_key}.png")
            await page.screenshot(path=screenshot_path, full_page=False)
            print(f"  ✓ 截图已保存至: {screenshot_path}")

        await browser.close()
    
    server.shutdown()
    print("\n🎉 全部 11 个核心页面 UI 视觉截图已生成完毕！")


if __name__ == '__main__':
    asyncio.run(capture_all_pages())
