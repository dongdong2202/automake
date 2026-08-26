// pages/coupon/coupon.js
const { getCoupons, claimCoupon } = require('../../services/user')
const { fenToYuan } = require('../../utils/price')

Page({
  data: {
    activeTab: 'available',   // 'available' | 'used' | 'expired' | 'claim'
    coupons: [],
    loading: true,
    claimableList: [
      { id: 101, title: '周末特惠立减券', amount: 400, min_spend: 2000, desc: '满 ¥20 可用' },
      { id: 102, title: '下午茶专享 ¥8 优惠券', amount: 800, min_spend: 3000, desc: '满 ¥30 可用' },
      { id: 103, title: '无门槛饮品尝鲜券', amount: 300, min_spend: 0, desc: '全场无门槛立减' }
    ]
  },

  onShow() {
    this.fetchCoupons()
  },

  onPullDownRefresh() {
    this.fetchCoupons().finally(() => {
      wx.stopPullDownRefresh()
    })
  },

  handleTabChange(e) {
    const tab = e.currentTarget.dataset.tab
    if (tab === this.data.activeTab) return
    this.setData({ activeTab: tab }, () => {
      if (tab !== 'claim') {
        this.fetchCoupons()
      }
    })
  },

  async fetchCoupons() {
    this.setData({ loading: true })
    try {
      const res = await getCoupons(this.data.activeTab)
      const list = Array.isArray(res) ? res : (res.data || [])
      
      const formatted = list.map(c => ({
        ...c,
        amountYuan: fenToYuan(c.amount),
        minSpendYuan: fenToYuan(c.min_spend)
      }))

      this.setData({
        coupons: formatted,
        loading: false
      })
    } catch (e) {
      console.error('获取优惠券失败:', e)
      this.setData({ loading: false })
    }
  },

  /**
   * 领取优惠券
   */
  async handleClaim(e) {
    const item = e.currentTarget.dataset.item
    if (!item) return

    try {
      await claimCoupon({
        title: item.title,
        amount: item.amount,
        min_spend: item.min_spend
      })
      wx.showToast({ title: '领取成功！', icon: 'success' })
      this.setData({ activeTab: 'available' }, () => {
        this.fetchCoupons()
      })
    } catch (e) {
      wx.showToast({ title: e.message || '领取失败', icon: 'none' })
    }
  },

  handleUseCoupon() {
    wx.switchTab({
      url: '/pages/menu/menu'
    })
  }
})
