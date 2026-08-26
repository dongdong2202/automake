// pages/product-detail/product-detail.js
const app = getApp()
const { getStoreMenu, getSoldOutItems } = require('../../services/menu')
const { fenToYuan, calculateUnitPrice } = require('../../utils/price')
const { formatImageUrl } = require('../../utils/util')

Page({
  data: {
    productId: null,
    product: null,
    loading: true,
    skuGroups: [],
    selectedSkuMap: {},
    buyQuantity: 1,
    currentUnitPrice: 0,
    currentUnitPriceYuan: '0.00',
    currentTotalPriceYuan: '0.00',
    cartCount: 0,
    detailImages: [],
    recommendedProducts: [],
    
    // 制作工艺与品质故事（以鲜橙汁为默认标杆）
    craftStories: [
      {
        icon: '🍊',
        title: '阳光果园直采',
        desc: '精选黄金糖酸比优质脐橙，原果整颗现榨'
      },
      {
        icon: '❄️',
        title: '4°C 恒温锁鲜',
        desc: '智能温控冷榨，保留 98% 鲜活天然维生素 C'
      },
      {
        icon: '⚡',
        title: '30秒洁净现制',
        desc: '密封无菌管道萃取，全程无人工接触更安心'
      }
    ],

    // 品质承诺标签
    qualityFeatures: [
      '✔ 100% NFC 鲜榨',
      '✔ 0 蔗糖添加',
      '✔ 0 勾兑浓缩汁',
      '✔ 0 防腐剂',
      '✔ 现点现萃'
    ],

    // 风味与营养维度
    flavorMetrics: [
      { name: '新鲜果香', percent: 95, desc: '天然浓郁柑橘香气' },
      { name: '酸甜平衡', percent: 90, desc: '12:1 黄金糖酸比，酸甜适口' },
      { name: '清爽回甘', percent: 98, desc: '入口清冽多汁，无涩味' }
    ],

    // 营养成分表
    nutritionInfo: [
      { label: '天然维生素C', value: '≥ 45mg/杯' },
      { label: '天然果糖', value: '100% 原果自带' },
      { label: '能量参考', value: '约 165 kcal' },
      { label: '反式脂肪酸', value: '0 g' }
    ]
  },

  onLoad(options) {
    if (options && options.id) {
      this.setData({ productId: Number(options.id) })
    }
    this.fetchProductDetail()
  },

  onShow() {
    this.updateCartBadge()
  },

  updateCartBadge() {
    const count = app.getCartCount ? app.getCartCount() : (app.globalData.cart || []).reduce((sum, i) => sum + (i.quantity || 0), 0)
    this.setData({ cartCount: count })
  },

  onPullDownRefresh() {
    this.fetchProductDetail().finally(() => {
      wx.stopPullDownRefresh()
    })
  },

  async fetchProductDetail() {
    this.setData({ loading: true })
    const store = app.globalData.currentStore || (app.globalData.storeList && app.globalData.storeList[0])
    
    try {
      let foundProduct = null
      let allItems = []

      if (store) {
        const targetDeviceSn = store.device_sn || store.code || store.id
        const [res, soldOutRes] = await Promise.allSettled([
          getStoreMenu(targetDeviceSn),
          getSoldOutItems(targetDeviceSn)
        ])
        const data = (res.status === 'fulfilled' && (res.value.data || res.value)) || {}
        const categories = data.categories || []

        const soldOutIdSet = new Set()
        if (soldOutRes.status === 'fulfilled' && soldOutRes.value) {
          const soldOutData = soldOutRes.value.data || soldOutRes.value
          const ids = (soldOutData && (soldOutData.sold_out_item_ids || soldOutData.item_ids)) || []
          if (Array.isArray(ids)) {
            ids.forEach(id => soldOutIdSet.add(Number(id)))
          }
        }
        if (Array.isArray(data.sold_out_item_ids)) {
          data.sold_out_item_ids.forEach(id => soldOutIdSet.add(Number(id)))
        }
        
        for (const cat of categories) {
          for (const itm of (cat.items || [])) {
            const isSoldOut = !itm.is_active || soldOutIdSet.has(Number(itm.id)) || itm.is_sold_out === true
            const enrichedItem = { ...itm, isSoldOut }
            allItems.push(enrichedItem)
            if (this.data.productId && itm.id === this.data.productId) {
              foundProduct = enrichedItem
            }
          }
        }
      }

      // 如果未指定或未匹配到，默认优先选用鲜橙汁或第一件商品
      if (!foundProduct && allItems.length > 0) {
        foundProduct = allItems.find(i => i.name && i.name.includes('鲜橙汁')) || allItems[0]
      }

      // 兜底默认鲜橙汁演示数据
      if (!foundProduct) {
        foundProduct = {
          id: 101,
          name: '100% NFC鲜橙汁',
          category_name: '鲜榨果汁',
          base_price: 1500,
          description: '阳光黄金脐橙整颗冷榨，不加一滴水与蔗糖，满满天然活性高维C，鲜爽酸甜。',
          price_description: '现榨冷萃饮品 · 建议30分钟内饮用口感最佳',
          main_ingredients: '优质新鲜脐橙、纯净冰块',
          image_url: '/images/drink_fruit.png',
          detail_page: null,
          skus: [
            { id: 1, name: '标准杯 (450ml)', category: '杯型', price_delta: 0, is_active: true },
            { id: 2, name: '大杯 (600ml)', category: '杯型', price_delta: 300, is_active: true },
            { id: 3, name: '常规冰', category: '温度', price_delta: 0, is_active: true },
            { id: 4, name: '少冰', category: '温度', price_delta: 0, is_active: true },
            { id: 5, name: '去冰 (冷藏)', category: '温度', price_delta: 0, is_active: true },
            { id: 6, name: '原味 (不加糖)', category: '甜度', price_delta: 0, is_active: true },
            { id: 7, name: '微甜 (+少许天然果糖)', category: '甜度', price_delta: 0, is_active: true }
          ]
        }
        allItems = [
          foundProduct,
          { id: 102, name: '大师美式咖啡', base_price: 1200, image_url: '/images/drink_coffee.png' },
          { id: 103, name: '原叶白桃乌龙', base_price: 1400, image_url: '/images/drink_tea.png' },
          { id: 104, name: '生椰拿铁咖啡', base_price: 1600, image_url: '/images/drink_special.png' }
        ]
      }
 
      const defaultImages = [
        '/images/orange_juice_main.png',
        '/images/drink_fruit.png',
        '/images/drink_tea.png',
        '/images/drink_coffee.png',
        '/images/drink_special.png'
      ]
      const fallbackImg = defaultImages[0]
      const displayImg = formatImageUrl(foundProduct.image_url) || fallbackImg
      const detailImg = formatImageUrl(foundProduct.detail_page) || (foundProduct.name && foundProduct.name.includes('橙') ? '/images/orange_juice_detail.png' : '')

      // SKU 分组解析与按加价金额升序排序 (没有增加价格按0计算)
      const skus = (foundProduct.skus || []).filter(s => s.is_active !== false)
      const groupsMap = {}
      skus.forEach(sku => {
        const groupName = sku.category || '规格'
        if (!groupsMap[groupName]) groupsMap[groupName] = []
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

      // 默认选中各组第一个
      const selectedSkuMap = {}
      skuGroups.forEach(g => {
        if (g.skus && g.skus.length > 0) {
          selectedSkuMap[g.category] = g.skus[0]
        }
      })

      const selectedSkus = Object.values(selectedSkuMap)
      const unitPrice = calculateUnitPrice(foundProduct.base_price, selectedSkus)

      // 推荐商品列表
      const recommendedProducts = allItems
        .filter(i => i.id !== foundProduct.id)
        .slice(0, 3)
        .map((it, idx) => ({
          ...it,
          displayImage: formatImageUrl(it.image_url) || defaultImages[(idx + 1) % defaultImages.length],
          basePriceYuan: fenToYuan(it.base_price)
        }))

      this.setData({
        product: {
          ...foundProduct,
          displayImage: displayImg,
          detail_page: detailImg,
          basePriceYuan: fenToYuan(foundProduct.base_price)
        },
        detailImages: [displayImg],
        skuGroups,
        selectedSkuMap,
        currentUnitPrice: unitPrice,
        currentUnitPriceYuan: fenToYuan(unitPrice),
        currentTotalPriceYuan: fenToYuan(unitPrice * this.data.buyQuantity),
        recommendedProducts,
        loading: false
      })

      this.updateCartBadge()

    } catch (e) {
      console.error('加载商品详情失败:', e)
      this.setData({ loading: false })
    }
  },

  handleSelectSkuOption(e) {
    const { category, sku } = e.currentTarget.dataset
    const newMap = {
      ...this.data.selectedSkuMap,
      [category]: sku
    }

    const selectedSkus = Object.values(newMap)
    const unitPrice = calculateUnitPrice(this.data.product.base_price, selectedSkus)

    this.setData({
      selectedSkuMap: newMap,
      currentUnitPrice: unitPrice,
      currentUnitPriceYuan: fenToYuan(unitPrice),
      currentTotalPriceYuan: fenToYuan(unitPrice * this.data.buyQuantity)
    })
  },

  handleQuantityChange(e) {
    const delta = Number(e.currentTarget.dataset.delta)
    let newQty = this.data.buyQuantity + delta
    if (newQty < 1) newQty = 1
    if (newQty > 99) newQty = 99

    this.setData({
      buyQuantity: newQty,
      currentTotalPriceYuan: fenToYuan(this.data.currentUnitPrice * newQty)
    })
  },

  handleAddToCart() {
    const { product, selectedSkuMap, buyQuantity, currentUnitPrice } = this.data
    if (product && product.isSoldOut) {
      wx.showToast({ title: '该饮品原料不足，已售罄', icon: 'none' })
      return
    }
    const selectedSkus = Object.values(selectedSkuMap)
    app.addToCart(product, selectedSkus, buyQuantity, currentUnitPrice)
    this.updateCartBadge()
    wx.showToast({ title: '已加入购物车', icon: 'success' })
  },

  handleBuyNow() {
    this.handleAddToCart()
    wx.navigateTo({
      url: '/pages/cart/cart'
    })
  },

  handleGoHome() {
    wx.switchTab({
      url: '/pages/index/index'
    })
  },

  handleGoCart() {
    wx.navigateTo({
      url: '/pages/cart/cart'
    })
  },

  handleSelectRecommend(e) {
    const item = e.currentTarget.dataset.item
    if (item) {
      this.setData({ productId: item.id })
      this.fetchProductDetail()
      wx.pageScrollTo({ scrollTop: 0, duration: 300 })
    }
  }
})

