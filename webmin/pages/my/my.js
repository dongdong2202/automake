// pages/my/my.js
const app = getApp()
const { fetchUserProfile, updateProfile, logout, silentLogin } = require('../../services/auth')
const { getCoupons } = require('../../services/user')
const { post } = require('../../services/request')
const { getOrderList } = require('../../services/order')
const { fenToYuan } = require('../../utils/price')

Page({
  data: {
    userInfo: null,
    isLoggedIn: false,
    isStaff: false,
    orderStats: { unpaidCount: 0, makingCount: 0 },
    couponCount: 0,

    // 购物车业务数据
    cartList: [],
    cartCount: 0,
    cartTotalYuan: '0.00',

    // 内嵌资料完善状态
    showOnboarding: false,
    onboardAvatar: '',
    onboardNickname: ''
  },

  onShow() {
    this.initUserData()
    this.syncCartData()
  },

  onPullDownRefresh() {
    Promise.allSettled([
      this.initUserData(),
      this.syncCartData()
    ]).finally(() => {
      wx.stopPullDownRefresh()
    })
  },

  /**
   * 同步全局购物车数据并格式化展示
   */
  syncCartData() {
    const cart = app.globalData.cart || []
    const cartCount = app.getCartCount()
    const totalAmount = app.getCartTotalAmount()

    const formattedCart = cart.map((item, index) => {
      const unitPrice = item.unitPrice || 0
      const qty = item.quantity || 0
      return {
        ...item,
        index,
        unitPriceYuan: fenToYuan(unitPrice),
        subtotalYuan: fenToYuan(unitPrice * qty),
        skuDesc: (item.selectedSkus || []).map(s => s.name).join(' / ')
      }
    })

    this.setData({
      cartList: formattedCart,
      cartCount,
      cartTotalYuan: fenToYuan(totalAmount)
    })
  },

  /**
   * 个人中心购物车商品加减数量
   */
  handleCartQuantityChange(e) {
    const { index, delta } = e.currentTarget.dataset
    if (index === undefined || delta === undefined) return
    app.updateCartQuantity(Number(index), Number(delta))
    this.syncCartData()
  },

  /**
   * 个人中心一键清空购物车
   */
  handleClearCart() {
    wx.showModal({
      title: '清空确认',
      content: '确定要清空购物车中的所有饮品吗？',
      confirmColor: '#dc2626',
      success: res => {
        if (res.confirm) {
          app.clearCart()
          this.syncCartData()
          wx.showToast({ title: '已清空', icon: 'none' })
        }
      }
    })
  },

  /**
   * 跳转至购物车/结算页面
   */
  handleGoCart() {
    if (this.data.cartCount === 0) {
      wx.switchTab({ url: '/pages/menu/menu' })
      return
    }
    wx.navigateTo({ url: '/pages/cart/cart' })
  },

  handleGoCheckout() {
    if (this.data.cartCount === 0) {
      wx.showToast({ title: '购物车为空', icon: 'none' })
      return
    }
    wx.navigateTo({ url: '/pages/cart/cart' })
  },

  handleGoMenu() {
    wx.switchTab({ url: '/pages/menu/menu' })
  },

  async initUserData() {
    const token = wx.getStorageSync('access_token')
    if (!token) {
      this.setData({ isLoggedIn: false, userInfo: null, isStaff: false, showOnboarding: false })
      return
    }
    try {
      const user = await fetchUserProfile()
      app.globalData.userInfo = user
      const isStaff = user.role && ['admin', 'material_admin', 'super_admin'].includes(user.role)
      this.setData({ userInfo: user, isLoggedIn: true, isStaff: !!isStaff })
      
      this.checkProfileCompleteness(user)
      this.fetchOrderStats()
      this.fetchMarketingData()
    } catch (err) {
      console.warn('获取个人资料失败:', err)
      this.setData({ isLoggedIn: false, userInfo: null, isStaff: false, showOnboarding: false })
    }
  },

  // 检查是否需要展示内嵌完善资料
  checkProfileCompleteness(user) {
    if (!user || !user.profile) return
    const { nickname, avatar_url } = user.profile
    if (!nickname || nickname === '微信用户' || !avatar_url) {
      this.setData({
        showOnboarding: true,
        onboardAvatar: avatar_url || '',
        onboardNickname: (nickname && nickname !== '微信用户') ? nickname : ''
      })
    } else {
      this.setData({ showOnboarding: false }) // 两者都有，立刻关闭 onboarding，变成欢迎页
    }
  },

  async fetchMarketingData() {
    try {
      const couponRes = await getCoupons('available')
      let cCount = 0
      if (couponRes) {
        const list = Array.isArray(couponRes) ? couponRes : (couponRes.data || [])
        cCount = list.length
      }
      this.setData({ couponCount: cCount })
    } catch (e) {
      console.warn('获取营销数据失败:', e)
    }
  },

  async fetchOrderStats() {
    try {
      const [unpaidRes, makingRes] = await Promise.allSettled([
        getOrderList({ status: 'created', page_size: 1 }),
        getOrderList({ status: 'making', page_size: 1 })
      ])
      let unpaidCount = 0, makingCount = 0
      if (unpaidRes.status === 'fulfilled' && unpaidRes.value) {
        const d = unpaidRes.value.data || unpaidRes.value
        unpaidCount = d.count || (Array.isArray(d) ? d.length : 0)
      }
      if (makingRes.status === 'fulfilled' && makingRes.value) {
        const d = makingRes.value.data || makingRes.value
        makingCount = d.count || (Array.isArray(d) ? d.length : 0)
      }
      this.setData({ orderStats: { unpaidCount, makingCount } })
    } catch (e) {
      console.warn('获取订单统计失败:', e)
    }
  },

  /**
   * 静默登录入口
   */
  async handleLoginFlow() {
    wx.showLoading({ title: '登录中...' })
    try {
      const user = await silentLogin()
      app.globalData.userInfo = user
      const isStaff = user.role && ['admin', 'material_admin', 'super_admin'].includes(user.role)
      wx.hideLoading()
      this.setData({ userInfo: user, isLoggedIn: true, isStaff: !!isStaff })
      
      this.checkProfileCompleteness(user)
      this.fetchOrderStats()
      this.fetchMarketingData()
    } catch (e) {
      wx.hideLoading()
      wx.showToast({ title: '登录失败，请重试', icon: 'none' })
    }
  },

  /**
   * 头像更新 (无论在 Onboarding 还是 Welcome 状态都通用)
   * 选完立即保存，保存后如果昵称也有了，UI就会自动切换
   */
  async handleUpdateAvatar(e) {
    const { avatarUrl } = e.detail
    if (!avatarUrl) return
    wx.showLoading({ title: '保存中...' })
    try {
      const updatedUser = await updateProfile({ avatar_url: avatarUrl })
      wx.hideLoading()
      app.globalData.userInfo = updatedUser
      this.setData({ userInfo: updatedUser })
      this.checkProfileCompleteness(updatedUser)
    } catch (err) {
      wx.hideLoading()
    }
  },

  /**
   * 昵称更新
   * 失去焦点时自动保存，保存后如果头像也有了，UI就会自动切换
   */
  async handleNicknameInputBlur(e) {
    const newNickname = (e.detail.value || '').trim()
    if (!newNickname) return
    
    // 如果没有实质改变，不需要发请求
    const currentName = (this.data.userInfo && this.data.userInfo.profile && this.data.userInfo.profile.nickname) || ''
    if (newNickname === currentName) {
      this.setData({ onboardNickname: newNickname })
      return
    }

    wx.showLoading({ title: '保存中...' })
    try {
      const updatedUser = await updateProfile({ nickname: newNickname })
      wx.hideLoading()
      app.globalData.userInfo = updatedUser
      this.setData({ userInfo: updatedUser })
      this.checkProfileCompleteness(updatedUser)
    } catch (err) {
      wx.hideLoading()
    }
  },

  /**
   * 绑定手机号 (可选)
   */
  async handleBindPhone(e) {
    if (!e.detail.code || (e.detail.errMsg && e.detail.errMsg.includes('fail'))) return
    wx.showLoading({ title: '绑定中...' })
    try {
      await post('/api/user/phone/bind', { phone: e.detail.code })
      wx.hideLoading()
      wx.showToast({ title: '绑定成功', icon: 'success' })
      this.initUserData()
    } catch (err) {
      wx.hideLoading()
    }
  },

  handleGoOrders() { wx.switchTab({ url: '/pages/orders/orders' }) },
  handleGoCoupons() { wx.navigateTo({ url: '/pages/coupon/coupon' }) },
  handleGoStaffWorkbench() { wx.navigateTo({ url: '/pages/staff/staff' }) },

  handleLogout() {
    wx.showModal({
      title: '确认登出',
      content: '确定要退出当前账号吗？',
      success: res => {
        if (res.confirm) {
          logout()
          this.setData({
            isLoggedIn: false,
            userInfo: null,
            isStaff: false,
            showOnboarding: false,
            orderStats: { unpaidCount: 0, makingCount: 0 }
          })
          wx.showToast({ title: '已退出', icon: 'none' })
        }
      }
    })
  },

  handleAbout() {
    wx.showModal({
      title: '关于全自动饮料机系统',
      content: '现制茶饮系统，涵盖前端点单、精准温控、动态多规格用料。',
      showCancel: false
    })
  }
})
