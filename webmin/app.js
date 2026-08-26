// app.js
const { silentLogin, fetchUserProfile } = require('./services/auth')
const { getStoreList } = require('./services/store')
const { getCurrentLocation, getDistance } = require('./utils/location')

App({
  onLaunch() {
    console.log('🚀 AutoMake 智能茶饮小程序启动')
    // 1. 初始化静默登录
    this.initAuth()
    // 2. 初始化门店定位
    this.initStoreLocation()
  },

  globalData: {
    userInfo: null,
    currentStore: null,      // 当前选择的门店对象
    storeList: [],           // 营业门店列表
    cart: [],                // 购物车列表 [{ item, selectedSkus, quantity, unitPrice, subtotal }]
    userLocation: null       // 用户经纬度 { latitude, longitude }
  },

  /**
   * 初始化登录态
   */
  async initAuth() {
    const token = wx.getStorageSync('access_token')
    if (token) {
      fetchUserProfile()
        .then(user => {
          this.globalData.userInfo = user
        })
        .catch(() => {
          silentLogin().then(user => {
            this.globalData.userInfo = user
          })
        })
    } else {
      silentLogin().then(user => {
        this.globalData.userInfo = user
      }).catch(err => {
        console.warn('初次静默登录跳过:', err)
      })
    }
  },

  /**
   * 初始化门店列表并按距离排序
   */
  async initStoreLocation() {
    try {
      const stores = await getStoreList()
      const list = Array.isArray(stores) ? stores : (stores.data || [])

      let flattenedDevices = []
      list.forEach(store => {
        if (store.devices && Array.isArray(store.devices) && store.devices.length > 0) {
          store.devices.forEach(dev => {
            if (dev.status && dev.status !== 'online') {
              return
            }
            flattenedDevices.push({
              ...store,
              id: store.id,
              device_id: dev.id,
              device_sn: dev.device_sn || store.device_sn,
              device_status: dev.status || 'online',
              name: dev.device_name || dev.name || store.name,
              store_name: store.name,
              address: dev.address || store.address,
              lat: dev.lat || store.lat,
              lng: dev.lng || store.lng
            })
          })
        } else {
          if (store.device_status && store.device_status !== 'online') {
            return
          }
          flattenedDevices.push({
            ...store,
            device_sn: store.device_sn || (store.devices && store.devices[0] && store.devices[0].device_sn) || ''
          })
        }
      })

      this.globalData.storeList = flattenedDevices

      // 尝试获取位置计算距离
      getCurrentLocation()
        .then(loc => {
          this.globalData.userLocation = loc
          // 计算各门店距离
          const sorted = flattenedDevices.map(s => {
            const dist = (s.lat && s.lng) ? getDistance(loc.latitude, loc.longitude, s.lat, s.lng) : 99999999
            return { ...s, distance: dist }
          }).sort((a, b) => a.distance - b.distance)

          this.globalData.storeList = sorted
          if (sorted.length > 0 && !this.globalData.currentStore) {
            this.globalData.currentStore = sorted[0]
          }
        })
        .catch(() => {
          if (flattenedDevices.length > 0 && !this.globalData.currentStore) {
            this.globalData.currentStore = flattenedDevices[0]
          }
        })
    } catch (e) {
      console.warn('获取门店列表失败:', e)
    }
  },

  // ==========================================
  // 购物车全局管理方法
  // ==========================================

  /**
   * 获取购物车商品总件数
   */
  getCartCount() {
    return this.globalData.cart.reduce((sum, i) => sum + (i.quantity || 0), 0)
  },

  /**
   * 获取购物车总金额（分）
   */
  getCartTotalAmount() {
    return this.globalData.cart.reduce((sum, i) => sum + ((i.unitPrice || 0) * (i.quantity || 0)), 0)
  },

  /**
   * 添加商品到购物车
   * @param {Object} item 商品对象
   * @param {Array} selectedSkus 所选规格对象数组
   * @param {number} quantity 数量
   * @param {number} unitPrice 单价（分）
   */
  addToCart(item, selectedSkus = [], quantity = 1, unitPrice = 0) {
    const skuIds = (selectedSkus || []).map(s => s.id).sort().join(',')
    const existingIndex = this.globalData.cart.findIndex(
      cartItem => cartItem.item.id === item.id && cartItem.skuKey === skuIds
    )

    if (existingIndex > -1) {
      this.globalData.cart[existingIndex].quantity += quantity
    } else {
      this.globalData.cart.push({
        item,
        selectedSkus,
        skuKey: skuIds,
        quantity,
        unitPrice,
        subtotal: unitPrice * quantity
      })
    }
    this.saveCartToStorage()
  },

  /**
   * 变更购物车某项数量
   */
  updateCartQuantity(index, delta) {
    if (index >= 0 && index < this.globalData.cart.length) {
      const target = this.globalData.cart[index]
      target.quantity += delta
      if (target.quantity <= 0) {
        this.globalData.cart.splice(index, 1)
      }
      this.saveCartToStorage()
    }
  },

  /**
   * 清空购物车
   */
  clearCart() {
    this.globalData.cart = []
    this.saveCartToStorage()
  },

  saveCartToStorage() {
    wx.setStorageSync('cart_cache', this.globalData.cart)
  }
})
