// pages/points/points.js
const { getPoints, claimCoupon } = require('../../services/user')

Page({
  data: {
    points: 0,
    pointLogs: [],
    loading: true,
    exchangeRewards: [
      { id: 1, title: '¥5 无门槛立减券', pointsCost: 50, amount: 500, min_spend: 0 },
      { id: 2, title: '¥10 满减券 (满¥35可用)', pointsCost: 90, amount: 1000, min_spend: 3500 },
      { id: 3, title: '全场 8 折限时特惠券', pointsCost: 120, amount: 0, min_spend: 2000 }
    ]
  },

  onShow() {
    this.fetchPointsData()
  },

  onPullDownRefresh() {
    this.fetchPointsData().finally(() => {
      wx.stopPullDownRefresh()
    })
  },

  async fetchPointsData() {
    this.setData({ loading: true })
    try {
      const res = await getPoints()
      const data = res.data || res
      this.setData({
        points: data.points || 0,
        pointLogs: data.logs || [],
        loading: false
      })
    } catch (e) {
      console.error('获取积分失败:', e)
      this.setData({ loading: false })
    }
  },

  async handleExchange(e) {
    const item = e.currentTarget.dataset.item
    if (!item) return

    if (this.data.points < item.pointsCost) {
      wx.showToast({ title: '积分不足，无法兑换', icon: 'none' })
      return
    }

    wx.showModal({
      title: '确认兑换',
      content: `确定消耗 ${item.pointsCost} 积分兑换【${item.title}】吗？`,
      success: async res => {
        if (res.confirm) {
          try {
            await claimCoupon({
              title: item.title,
              amount: item.amount,
              min_spend: item.min_spend
            })
            wx.showToast({ title: '兑换成功！已发至券包', icon: 'success' })
            this.fetchPointsData()
          } catch (err) {
            wx.showToast({ title: '兑换失败，请重试', icon: 'none' })
          }
        }
      }
    })
  }
})
