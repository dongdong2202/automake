/**
 * 全局环境与 API 基础配置
 */
let env = 'develop'
try {
  const accountInfo = wx.getAccountInfoSync ? wx.getAccountInfoSync() : null
  if (accountInfo && accountInfo.miniProgram) {
    env = accountInfo.miniProgram.envVersion || 'develop'
  }
} catch (e) {
  env = 'develop'
}

const CONFIG = {
  // 全局 API 基础路径
  BASE_URL: 'https://tinylab.store',
  
  // 请求超时时间 (毫秒)
  TIMEOUT: 15000,
  
  // 默认门店 ID (在未获取到定位时兜底)
  DEFAULT_STORE_ID: 100000,
  
  // 轮询订单状态间隔 (毫秒)
  POLL_ORDER_INTERVAL: 3000,
  
  // 默认模拟图片
  DEFAULT_IMAGES: {
    AVATAR: '/images/default_avatar.png',
    COFFEE: '/images/drink_coffee.png',
    TEA: '/images/drink_tea.png',
    FRUIT: '/images/drink_fruit.png',
    SPECIAL: '/images/drink_special.png',
    EMPTY_ORDER: '/images/empty_order.png',
    EMPTY_CART: '/images/empty_cart.png'
  }
}

module.exports = CONFIG
