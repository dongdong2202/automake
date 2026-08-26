// pages/orders/orders.js
const { getOrderList, cancelOrder } = require('../../services/order')
const { mockSuccessPayment } = require('../../services/pay')
const { fenToYuan } = require('../../utils/price')
const { formatDateTime } = require('../../utils/time')

const STATUS_TABS = [
  { key: 'all', label: '全部' },
  { key: 'created', label: '待支付' },
  { key: 'making', label: '制作中' },
  { key: 'success', label: '已完成' },
  { key: 'cancelled', label: '已取消/退款' }
]

const STATUS_MAP = {
  created: { text: '待支付', class: 'tag-warning', canPay: true, canCancel: true },
  pending_dispense: { text: '等待出货', class: 'tag-primary', isMaking: true },
  making: { text: '制作中...', class: 'tag-success', isMaking: true },
  success: { text: '出货完成', class: 'tag-default', isDone: true },
  cancelled: { text: '已取消', class: 'tag-muted' },
  refunding: { text: '退款中', class: 'tag-warning' },
  refunded: { text: '已退款', class: 'tag-muted' },
  failed: { text: '制作失败', class: 'tag-danger' }
}

Page({
  data: {
    tabs: STATUS_TABS,
    activeTab: 'all',
    orderList: [],
    loading: true,
    page: 1,
    pageSize: 15,
    hasMore: true
  },

  onShow() {
    this.refreshOrders()
  },

  onPullDownRefresh() {
    this.refreshOrders().finally(() => {
      wx.stopPullDownRefresh()
    })
  },

  onReachBottom() {
    if (this.data.hasMore && !this.data.loading) {
      this.loadMoreOrders()
    }
  },

  handleTabChange(e) {
    const tab = e.currentTarget.dataset.tab
    if (tab === this.data.activeTab) return
    this.setData({
      activeTab: tab,
      orderList: [],
      page: 1,
      hasMore: true
    }, () => {
      this.fetchOrders()
    })
  },

  async refreshOrders() {
    this.setData({ page: 1, hasMore: true })
    return this.fetchOrders()
  },

  async fetchOrders() {
    this.setData({ loading: true })
    try {
      const params = {
        page: this.data.page,
        page_size: this.data.pageSize
      }
      if (this.data.activeTab !== 'all') {
        params.status = this.data.activeTab
      }

      const res = await getOrderList(params)
      const data = res.data || res
      const rawList = Array.isArray(data) ? data : (data.results || data.list || [])

      const formatted = rawList.map(order => {
        const statusMeta = STATUS_MAP[order.status] || { text: order.status_display || order.status, class: 'tag' }
        return {
          ...order,
          payAmountYuan: fenToYuan(order.pay_amount || order.total_amount),
          createdAtFormatted: formatDateTime(order.created_at),
          statusMeta
        }
      })

      this.setData({
        orderList: this.data.page === 1 ? formatted : [...this.data.orderList, ...formatted],
        hasMore: formatted.length >= this.data.pageSize,
        loading: false
      })

    } catch (err) {
      console.error('获取订单列表失败:', err)
      this.setData({ loading: false })
    }
  },

  async loadMoreOrders() {
    this.setData({ page: this.data.page + 1 })
    await this.fetchOrders()
  },

  /**
   * 跳转订单详情
   */
  handleGoDetail(e) {
    const orderNo = e.currentTarget.dataset.orderNo
    if (orderNo) {
      wx.navigateTo({
        url: `/pages/order-detail/order-detail?order_no=${orderNo}`
      })
    }
  },

  /**
   * 待支付订单快捷模拟支付
   */
  async handleQuickPay(e) {
    const orderNo = e.currentTarget.dataset.orderNo
    if (!orderNo) return

    wx.showModal({
      title: '模拟支付确认',
      content: `确定为订单 ${orderNo} 完成模拟支付测试吗？`,
      confirmText: '立即支付',
      success: async (res) => {
        if (res.confirm) {
          try {
            await mockSuccessPayment(orderNo)
            wx.showToast({ title: '模拟支付成功！', icon: 'success' })
            this.refreshOrders()
          } catch (e) {
            console.error('支付失败:', e)
          }
        }
      }
    })
  },

  /**
   * 取消订单
   */
  async handleCancelOrder(e) {
    const orderNo = e.currentTarget.dataset.orderNo
    if (!orderNo) return

    wx.showModal({
      title: '取消订单',
      content: '确定要取消该订单吗？',
      success: async (res) => {
        if (res.confirm) {
          try {
            await cancelOrder(orderNo)
            wx.showToast({ title: '订单已取消', icon: 'success' })
            this.refreshOrders()
          } catch (e) {
            console.error('取消订单失败:', e)
          }
        }
      }
    })
  },

  /**
   * 去点单
   */
  handleGoMenu() {
    wx.switchTab({
      url: '/pages/menu/menu'
    })
  }
})
