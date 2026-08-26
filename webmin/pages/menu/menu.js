const app = getApp()
const { getStoreMenu, getSoldOutItems } = require('../../services/menu')
const { getStoreList } = require('../../services/store')
const { fenToYuan, calculateUnitPrice } = require('../../utils/price')
const { formatBusinessHours, getStoreBusinessStatus } = require('../../utils/time')
const { formatImageUrl } = require('../../utils/util')

Page({
  data: {
    loading: true,
    currentStore: null,
    categories: [],
    activeCategoryIndex: 0,
    rightScrollIntoView: 'category-0',
    hideSoldOut: false,      // 是否折叠隐藏已售罄商品
    soldOutItemIds: [],      // 已售罄商品 ID 列表
    
    // SKU 弹窗状态
    showSkuModal: false,
    selectedProduct: null,
    skuGroups: [],
    selectedSkuMap: {},
    buyQuantity: 1,
    currentUnitPrice: 0,
    currentUnitPriceYuan: '0.00',
    currentTotalPriceYuan: '0.00',
    
    // 购物车状态
    cartCount: 0,
    cartTotalYuan: '0.00',
    showCartDetail: false,
    cartList: []
  },

  onLoad(options) {
    if (options && options.store_id) {
      const storeId = Number(options.store_id)
      const found = (app.globalData.storeList || []).find(s => s.id === storeId)
      if (found) {
        app.globalData.currentStore = found
      }
    }
    this.initMenuData()
  },

  onShow() {
    const targetStore = app.globalData.currentStore || (app.globalData.storeList && app.globalData.storeList[0])
    const currentStore = this.data.currentStore

    const needReload = !currentStore || 
                       !this.data.categories || 
                       this.data.categories.length === 0 || 
                       (targetStore && (
                         currentStore.id !== targetStore.id || 
                         currentStore.device_sn !== targetStore.device_sn
                       ))

    if (targetStore) {
      app.globalData.currentStore = targetStore
    }

    if (needReload) {
      this.initMenuData()
    } else {
      this.syncCartState()
    }
  },

  onPullDownRefresh() {
    this.initMenuData().finally(() => {
      wx.stopPullDownRefresh()
    })
  },

  async initMenuData() {
    this.setData({ loading: true })
    const store = app.globalData.currentStore || (app.globalData.storeList && app.globalData.storeList[0])
    
    if (!store) {
      try {
        const listRes = await getStoreList()
        const list = Array.isArray(listRes) ? listRes : (listRes.data || [])
        if (list.length > 0) {
          app.globalData.storeList = list
          app.globalData.currentStore = list[0]
          return this.initMenuData()
        }
      } catch (e) {
        console.error('获取门店失败:', e)
      }
      this.setData({ loading: false })
      return
    }

    const statusObj = getStoreBusinessStatus(store)
    this.setData({
      currentStore: {
        ...store,
        isOpen: statusObj.isOpen,
        statusText: statusObj.statusText,
        businessHoursText: formatBusinessHours(store.business_hours)
      }
    })

    try {
      const targetDeviceSn = store.device_sn || store.code || store.id
      const [menuRes, soldOutRes] = await Promise.allSettled([
        getStoreMenu(targetDeviceSn),
        getSoldOutItems(targetDeviceSn)
      ])

      const menuData = (menuRes.status === 'fulfilled' && (menuRes.value.data || menuRes.value)) || {}
      const rawCategories = menuData.categories || []

      const soldOutIdSet = new Set()
      if (soldOutRes.status === 'fulfilled' && soldOutRes.value) {
        const soldOutData = soldOutRes.value.data || soldOutRes.value
        const ids = (soldOutData && (soldOutData.sold_out_item_ids || soldOutData.item_ids)) || []
        if (Array.isArray(ids)) {
          ids.forEach(id => soldOutIdSet.add(Number(id)))
        }
      }
      if (Array.isArray(menuData.sold_out_item_ids)) {
        menuData.sold_out_item_ids.forEach(id => soldOutIdSet.add(Number(id)))
      }

      const defaultDrinkImages = [
        '/images/drink_coffee.png',
        '/images/drink_tea.png',
        '/images/drink_fruit.png',
        '/images/drink_special.png'
      ]
 
      const formattedCategories = rawCategories.map((cat, catIdx) => {
        const items = (cat.items || []).map((item, itemIdx) => {
          const fallbackImg = defaultDrinkImages[(catIdx + itemIdx) % defaultDrinkImages.length]
          const displayBasePrice = (item.global_base_price !== undefined && item.global_base_price !== null && item.global_base_price > 0)
            ? item.global_base_price
            : item.base_price
          const isSoldOut = !item.is_active || soldOutIdSet.has(Number(item.id)) || item.is_sold_out === true
          return {
            ...item,
            displayImage: formatImageUrl(item.image_url) || fallbackImg,
            basePriceYuan: fenToYuan(displayBasePrice),
            isSoldOut
          }
        })
        return {
          ...cat,
          items
        }
      })

      this.setData({
        categories: formattedCategories,
        soldOutItemIds: Array.from(soldOutIdSet),
        loading: false
      })
      this.syncCartState()

    } catch (err) {
      console.error('加载菜单失败:', err)
      this.setData({ loading: false })
      wx.showToast({ title: '菜单加载失败', icon: 'none' })
    }
  },

  syncCartState() {
    const cart = app.globalData.cart || []
    const count = app.getCartCount()
    const totalFen = app.getCartTotalAmount()
    
    const formattedCart = cart.map((item, index) => ({
      ...item,
      index,
      unitPriceYuan: fenToYuan(item.unitPrice),
      subtotalYuan: fenToYuan(item.subtotal),
      skuDesc: (item.selectedSkus || []).map(s => s.name).join(' / ')
    }))

    this.setData({
      cartList: formattedCart,
      cartCount: count,
      cartTotalYuan: fenToYuan(totalFen),
      showCartDetail: count === 0 ? false : this.data.showCartDetail
    })
  },

  handleCategoryTap(e) {
    const index = e.currentTarget.dataset.index
    this.setData({
      activeCategoryIndex: index,
      rightScrollIntoView: `category-${index}`
    })
  },

  /**
   * 跳转进入商品大图详情页
   */
  handleGoProductDetail(e) {
    const item = e.currentTarget.dataset.item
    if (item) {
      wx.navigateTo({
        url: `/pages/product-detail/product-detail?id=${item.id}`
      })
    }
  },

  /**
   * 打开快速选规格弹窗
   */
  handleOpenSkuModal(e) {
    const item = e.currentTarget.dataset.item
    if (!item || item.isSoldOut) return

    const skus = (item.skus || []).filter(s => s.is_active)
    const groupsMap = {}
    
    skus.forEach(sku => {
      const groupName = sku.category || '规格'
      if (!groupsMap[groupName]) {
        groupsMap[groupName] = []
      }
      const delta = Number(sku.price_delta) || 0
      groupsMap[groupName].push({
        ...sku,
        price_delta: delta,
        priceDeltaText: delta > 0 ? `+¥${fenToYuan(delta)}` : (delta < 0 ? `-¥${fenToYuan(Math.abs(delta))}` : '')
      })
    })

    const skuGroups = Object.keys(groupsMap).map(category => {
      const sortedSkus = groupsMap[category].sort((a, b) => {
        const deltaA = Number(a.price_delta) || 0
        const deltaB = Number(b.price_delta) || 0
        if (deltaA !== deltaB) {
          return deltaA - deltaB
        }
        return (Number(a.sort_order) || 0) - (Number(b.sort_order) || 0)
      })
      return {
        category,
        skus: sortedSkus
      }
    })

    const selectedSkuMap = {}
    skuGroups.forEach(g => {
      if (g.skus && g.skus.length > 0) {
        selectedSkuMap[g.category] = g.skus[0]
      }
    })

    const selectedSkus = Object.values(selectedSkuMap)
    const unitPrice = calculateUnitPrice(item.base_price, selectedSkus)

    this.setData({
      selectedProduct: item,
      skuGroups,
      selectedSkuMap,
      buyQuantity: 1,
      currentUnitPrice: unitPrice,
      currentUnitPriceYuan: fenToYuan(unitPrice),
      currentTotalPriceYuan: fenToYuan(unitPrice * 1),
      showSkuModal: true
    })
  },

  handleSelectSkuOption(e) {
    const { category, sku } = e.currentTarget.dataset
    const newMap = {
      ...this.data.selectedSkuMap,
      [category]: sku
    }

    const selectedSkus = Object.values(newMap)
    const unitPrice = calculateUnitPrice(this.data.selectedProduct.base_price, selectedSkus)

    this.setData({
      selectedSkuMap: newMap,
      currentUnitPrice: unitPrice,
      currentUnitPriceYuan: fenToYuan(unitPrice),
      currentTotalPriceYuan: fenToYuan(unitPrice * this.data.buyQuantity)
    })
  },

  handleModalQuantityChange(e) {
    const delta = Number(e.currentTarget.dataset.delta)
    let newQty = this.data.buyQuantity + delta
    if (newQty < 1) newQty = 1
    if (newQty > 99) newQty = 99

    this.setData({
      buyQuantity: newQty,
      currentTotalPriceYuan: fenToYuan(this.data.currentUnitPrice * newQty)
    })
  },

  handleConfirmAddToCart() {
    const { selectedProduct, selectedSkuMap, buyQuantity, currentUnitPrice } = this.data
    const selectedSkus = Object.values(selectedSkuMap)

    app.addToCart(selectedProduct, selectedSkus, buyQuantity, currentUnitPrice)
    
    this.setData({
      showSkuModal: false
    })
    this.syncCartState()
    wx.showToast({ title: '已加入购物车', icon: 'success' })
  },

  handleCloseSkuModal() {
    this.setData({
      showSkuModal: false
    })
  },

  handleToggleCartDetail() {
    if (this.data.cartCount === 0) return
    this.setData({
      showCartDetail: !this.data.showCartDetail
    })
  },

  handleCartItemQuantity(e) {
    const { index, delta } = e.currentTarget.dataset
    app.updateCartQuantity(index, Number(delta))
    this.syncCartState()
  },

  handleClearCart() {
    wx.showModal({
      title: '提示',
      content: '确定清空购物车吗？',
      success: res => {
        if (res.confirm) {
          app.clearCart()
          this.syncCartState()
        }
      }
    })
  },

  handleToggleHideSoldOut() {
    this.setData({
      hideSoldOut: !this.data.hideSoldOut
    })
  },

  handleGoCheckout() {
    if (this.data.cartCount === 0) {
      wx.showToast({ title: '请先选择商品', icon: 'none' })
      return
    }
    wx.navigateTo({
      url: '/pages/cart/cart'
    })
  },

  handleSwitchStore() {
    wx.switchTab({
      url: '/pages/index/index'
    })
  }
})
