// pages/index/index.js
const app = getApp()
const { getStoreList } = require('../../services/store')
const { getCurrentLocation, getDistance, formatDistance, openMapNavigation } = require('../../utils/location')
const { formatBusinessHours, getStoreBusinessStatus } = require('../../utils/time')

// 构造地图标注点 Helper 函数
function buildMarkers(stores) {
  return (stores || []).map((s, idx) => {
    const lat = Number(s.lat) || 39.9042
    const lng = Number(s.lng) || 116.4074
    const statusText = s.statusText || getStoreBusinessStatus(s).statusText
    return {
      id: s.marker_id !== undefined ? s.marker_id : idx,
      latitude: lat,
      longitude: lng,
      width: 32,
      height: 32,
      callout: {
        content: `${s.name} (${statusText})\n${s.distanceText || ''}`,
        color: '#2c352e',
        fontSize: 12,
        borderRadius: 8,
        bgColor: '#ffffff',
        padding: 6,
        display: idx === 0 ? 'ALWAYS' : 'BYCLICK'
      }
    }
  })
}

Page({
  data: {
    loading: true,
    viewMode: 'list',        // 'list' | 'map'
    hasLocationPermission: false,
    banners: [
      { id: 1, image: '/images/banner1.png', title: '秋季新品 · 桂花乌龙奶茶' },
      { id: 2, image: '/images/banner2.png', title: '大师现磨 · 100%阿拉比卡' },
      { id: 3, image: '/images/banner3.png', title: '鲜果手捣 · 现制清爽冰沙' }
    ],
    nearestStore: null,      // 距离最近的门店/设备
    otherStores: [],         // 其它周边门店
    filteredStores: [],      // 过滤搜索后的门店
    searchKeyword: '',
    selectedCity: '全部城市',
    cityList: ['全部城市', '北京市', '上海市', '深圳市', '广州市', '杭州市'],
    
    // 地图相关
    mapCenterLat: 39.9042,
    mapCenterLng: 116.4074,
    markers: [],
    selectedMarkerStore: null
  },

  onLoad() {
    this.initPageData()
  },

  onShow() {
    if (app.globalData.currentStore && this.data.nearestStore) {
      if (app.globalData.currentStore.id !== this.data.nearestStore.id) {
        this.setData({
          nearestStore: app.globalData.currentStore
        })
      }
    }
  },

  onPullDownRefresh() {
    this.initPageData().finally(() => {
      wx.stopPullDownRefresh()
    })
  },

  async initPageData() {
    this.setData({ loading: true })
    try {
      const storesRes = await getStoreList()
      let stores = []
      if (storesRes) {
        stores = Array.isArray(storesRes) ? storesRes : (storesRes.data || [])
      }

      // 同一门店若有多个设备，展开为每个独立的设备项，以各自的 address 进行展示
      let flattenedDevices = []
      stores.forEach(store => {
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
              address: dev.address || store.address || '',
              lat: dev.lat !== undefined && dev.lat !== null ? dev.lat : store.lat,
              lng: dev.lng !== undefined && dev.lng !== null ? dev.lng : store.lng,
              business_hours: store.business_hours,
              status: dev.status || store.status,
              is_in_business_hours: store.is_in_business_hours
            })
          })
        } else {
          if (store.device_status && store.device_status !== 'online') {
            return
          }
          flattenedDevices.push({
            ...store,
            address: store.address || ''
          })
        }
      })

      let loc = null
      let hasLoc = false
      try {
        loc = await getCurrentLocation()
        hasLoc = true
      } catch (e) {
        console.log('获取定位权限未开启或失败，采用城市与地图展示')
      }

      // 格式化设备与距离、营业状态
      const formattedStores = flattenedDevices.map((item, idx) => {
        let dist = 99999999
        let distText = '位置待获取'
        const lat = Number(item.lat) || (39.9042 + idx * 0.01)
        const lng = Number(item.lng) || (116.4074 + idx * 0.01)

        if (hasLoc && loc) {
          dist = getDistance(loc.latitude, loc.longitude, lat, lng)
          distText = formatDistance(dist)
        }
        const statusObj = getStoreBusinessStatus(item)
        return {
          ...item,
          marker_id: idx,
          unique_key: `${item.id}_${item.device_sn || idx}`,
          lat,
          lng,
          distance: dist,
          distanceText: distText,
          businessHoursText: formatBusinessHours(item.business_hours),
          isOpen: statusObj.isOpen,
          statusText: statusObj.statusText,
          isRestToday: statusObj.isRestToday,
          businessStatusText: statusObj.statusText
        }
      })

      if (hasLoc) {
        formattedStores.sort((a, b) => a.distance - b.distance)
      }

      // 动态提取支持的城市列表
      const citySet = new Set(['北京市', '上海市', '广州市', '深圳市', '杭州市'])
      formattedStores.forEach(s => {
        if (s.city) {
          citySet.add(s.city.endsWith('市') ? s.city : s.city + '市')
        } else if (s.address) {
          const match = s.address.match(/([^省市区县\s]+?[市|州])/g)
          if (match) {
            match.forEach(c => citySet.add(c))
          }
        }
      })
      const cityList = ['全部城市', ...Array.from(citySet)]

      const nearest = formattedStores.length > 0 ? formattedStores[0] : null
      const others = formattedStores.length > 1 ? formattedStores.slice(1) : []

      // 构建地图标记点
      const markers = buildMarkers(formattedStores)

      app.globalData.storeList = formattedStores
      if (nearest && !app.globalData.currentStore) {
        app.globalData.currentStore = nearest
      }

      this.setData({
        hasLocationPermission: hasLoc,
        cityList,
        mapCenterLat: loc ? loc.latitude : (nearest ? nearest.lat : 39.9042),
        mapCenterLng: loc ? loc.longitude : (nearest ? nearest.lng : 116.4074),
        nearestStore: app.globalData.currentStore || nearest,
        otherStores: others,
        filteredStores: formattedStores,
        markers,
        selectedMarkerStore: nearest,
        loading: false
      })

    } catch (err) {
      console.error('加载首页数据失败:', err)
      this.setData({ loading: false })
      wx.showToast({ title: '数据加载失败', icon: 'none' })
    }
  },

  /**
   * 切换 列表视图 / 地图视图
   */
  handleSwitchViewMode(e) {
    const mode = e.currentTarget.dataset.mode
    this.setData({ viewMode: mode })
  },

  /**
   * 地图标记点点击
   */
  handleMarkerTap(e) {
    const markerId = e.detail.markerId
    const store = (this.data.filteredStores || []).find((s, idx) => (s.marker_id !== undefined ? s.marker_id : idx) === markerId || s.id === markerId)
    if (store) {
      this.setData({
        selectedMarkerStore: store,
        mapCenterLat: store.lat,
        mapCenterLng: store.lng
      })
    }
  },

  /**
   * 搜索过滤
   */
  handleSearchInput(e) {
    const keyword = e.detail.value.trim().toLowerCase()
    const all = app.globalData.storeList || []
    const city = this.data.selectedCity

    let filtered = all
    if (city && city !== '全部城市') {
      const cleanCity = city.replace('市', '')
      filtered = all.filter(s => 
        (s.city && s.city.includes(cleanCity)) ||
        (s.address && s.address.includes(cleanCity)) ||
        (s.name && s.name.includes(cleanCity))
      )
    }

    if (keyword) {
      filtered = filtered.filter(s => 
        s.name.toLowerCase().includes(keyword) || 
        (s.address && s.address.toLowerCase().includes(keyword)) ||
        (s.device_sn && s.device_sn.toLowerCase().includes(keyword))
      )
    }

    const markers = buildMarkers(filtered)
    const firstStore = filtered.length > 0 ? filtered[0] : null

    this.setData({
      searchKeyword: keyword,
      filteredStores: filtered,
      otherStores: filtered.length > 1 ? filtered.slice(1) : [],
      nearestStore: firstStore || (city === '全部城市' ? (all[0] || null) : null),
      markers,
      selectedMarkerStore: firstStore,
      mapCenterLat: firstStore ? firstStore.lat : this.data.mapCenterLat,
      mapCenterLng: firstStore ? firstStore.lng : this.data.mapCenterLng
    })
  },

  /**
   * 城市筛选
   */
  handleCityChange(e) {
    const city = this.data.cityList[e.detail.value]
    const all = app.globalData.storeList || []
    const keyword = (this.data.searchKeyword || '').toLowerCase()
    
    let filtered = all
    if (city !== '全部城市') {
      const cleanCity = city.replace('市', '')
      filtered = all.filter(s => 
        (s.city && s.city.includes(cleanCity)) ||
        (s.address && s.address.includes(cleanCity)) ||
        (s.name && s.name.includes(cleanCity))
      )
    }

    if (keyword) {
      filtered = filtered.filter(s => 
        s.name.toLowerCase().includes(keyword) || 
        (s.address && s.address.toLowerCase().includes(keyword)) ||
        (s.device_sn && s.device_sn.toLowerCase().includes(keyword))
      )
    }

    const markers = buildMarkers(filtered)
    const firstStore = filtered.length > 0 ? filtered[0] : null

    this.setData({
      selectedCity: city,
      filteredStores: filtered,
      otherStores: filtered.length > 1 ? filtered.slice(1) : [],
      nearestStore: firstStore || (city === '全部城市' ? (all[0] || null) : null),
      markers,
      selectedMarkerStore: firstStore,
      mapCenterLat: firstStore ? firstStore.lat : this.data.mapCenterLat,
      mapCenterLng: firstStore ? firstStore.lng : this.data.mapCenterLng
    })
  },

  /**
   * 重新获取定位
   */
  async handleRelocate() {
    wx.showLoading({ title: '正在重新定位...' })
    try {
      await this.initPageData()
      wx.hideLoading()
      wx.showToast({ title: '定位已更新', icon: 'success' })
    } catch (e) {
      wx.hideLoading()
    }
  },

  /**
   * 打开导航
   */
  handleOpenNavigation(e) {
    const store = e.currentTarget.dataset.store || this.data.selectedMarkerStore || this.data.nearestStore
    if (!store || !store.lat || !store.lng) {
      wx.showToast({ title: '该门店未设置坐标', icon: 'none' })
      return
    }
    openMapNavigation(store.lat, store.lng, store.name, store.address)
  },

  /**
   * 选定门店进入点单（仅营业中状态可进入）
   */
  handleGoMenu(e) {
    const store = (e && e.currentTarget && e.currentTarget.dataset.store) || this.data.selectedMarkerStore || this.data.nearestStore
    if (!store) return

    const statusText = store.statusText || (getStoreBusinessStatus(store).statusText)
    if (statusText !== '营业中') {
      wx.showToast({
        title: statusText === '今日休息' ? '该设备今日休息中' : '该设备已打烊',
        icon: 'none'
      })
      return
    }

    app.globalData.currentStore = store
    wx.switchTab({
      url: '/pages/menu/menu'
    })
  },

  /**
   * 快捷入口跳转
   */
  handleQuickJump(e) {
    const type = e.currentTarget.dataset.type
    if (type === 'coupon') {
      wx.navigateTo({ url: '/pages/coupon/coupon' })
    } else if (type === 'points') {
      wx.navigateTo({ url: '/pages/points/points' })
    } else if (type === 'scan') {
      wx.scanCode({
        success: res => {
          wx.showToast({ title: '扫码成功', icon: 'success' })
        }
      })
    } else {
      this.handleGoMenu(e)
    }
  }
})
