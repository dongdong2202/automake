// pages/order-detail/order-detail.js
const { getOrderDetail, cancelOrder, getOrderStatusAndPickup } = require('../../services/order')
const { mockSuccessPayment, requestRefund } = require('../../services/pay')
const { fenToYuan } = require('../../utils/price')
const { formatDateTime } = require('../../utils/time')
const { openMapNavigation } = require('../../utils/location')

let pollTimer = null

Page({
  data: {
    orderNo: '',
    order: null,
    loading: true,
    pickupInfo: null,         // 取餐码与等候信息 { pickup_code, wait_minutes, status, slot_no }
    statusSteps: [
      { key: 'created', title: '已下单', desc: '等待付款' },
      { key: 'pending_dispense', title: '已支付', desc: '等待排队' },
      { key: 'making', title: '制作中', desc: '正在调配' },
      { key: 'success', title: '制作完成', desc: '请凭码取餐' }
    ],
    currentStepIndex: 0
  },

  onLoad(options) {
    if (options && options.order_no) {
      this.setData({ orderNo: options.order_no })
      this.fetchDetail()
    }
  },

  onShow() {
    if (this.data.orderNo && !this.data.loading) {
      this.fetchDetail()
    }
  },

  onUnload() {
    this.stopPolling()
  },

  onHide() {
    this.stopPolling()
  },

  onPullDownRefresh() {
    this.fetchDetail().finally(() => {
      wx.stopPullDownRefresh()
    })
  },

  /**
   * 获取订单详情
   */
  async fetchDetail() {
    if (!this.data.orderNo) return
    try {
      const res = await getOrderDetail(this.data.orderNo)
      const data = res.data || res
      
      const items = (data.items || []).map(item => ({
        ...item,
        unitPriceYuan: fenToYuan(item.unit_price),
        subtotalYuan: fenToYuan(item.subtotal),
        skuDesc: item.sku_name || (item.skus || []).map(s => s.name).join(' / ')
      }))

      // 计算当前进度步骤
      let stepIdx = 0
      if (data.status === 'created') stepIdx = 0
      else if (data.status === 'pending_dispense') stepIdx = 1
      else if (data.status === 'making') stepIdx = 2
      else if (data.status === 'success') stepIdx = 3

      const statusLogs = (data.status_logs || []).map(log => ({
        ...log,
        timeFormatted: formatDateTime(log.created_at),
        title: log.action_name || (log.from_status ? `${log.from_status} → ${log.to_status}` : '状态更新')
      }))

      this.setData({
        order: {
          ...data,
          items,
          statusLogs,
          payAmountYuan: fenToYuan(data.pay_amount || data.total_amount),
          totalAmountYuan: fenToYuan(data.total_amount),
          discountAmountYuan: fenToYuan(data.discount_amount || 0),
          createdAtFormatted: formatDateTime(data.created_at),
          paidAtFormatted: formatDateTime(data.paid_at),
          doneAtFormatted: formatDateTime(data.done_at)
        },
        currentStepIndex: stepIdx,
        loading: false
      })

      // 获取取餐码与实时制作状态
      await this.fetchPickupStatus()

      // 若处于活跃制作中，开启自动轮询
      if (['pending_dispense', 'making'].includes(data.status)) {
        this.startPolling()
      } else {
        this.stopPolling()
      }

    } catch (err) {
      console.error('获取订单详情失败:', err)
      this.setData({ loading: false })
    }
  },

  /**
   * 轮询取餐状态
   */
  async fetchPickupStatus() {
    try {
      const res = await getOrderStatusAndPickup(this.data.orderNo)
      const data = res.data || res
      if (data) {
        this.setData({
          pickupInfo: {
            pickupCode: data.pickup_code || data.code || '',
            waitMinutes: data.estimated_wait_minutes || data.wait_minutes || 2,
            queueAhead: data.queue_ahead || 0,
            status: data.status,
            slotNo: data.slot_no || '1'
          }
        })
      }
    } catch (e) {
      console.warn('获取取餐码状态失败:', e)
    }
  },

  startPolling() {
    if (pollTimer) return
    pollTimer = setInterval(() => {
      this.fetchDetail()
    }, 3000)
  },

  stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  },

  /**
   * 待支付订单快捷模拟支付
   */
  async handleQuickPay() {
    wx.showModal({
      title: '模拟支付确认',
      content: '确定模拟完成支付吗？',
      confirmText: '确认支付',
      success: async res => {
        if (res.confirm) {
          try {
            await mockSuccessPayment(this.data.orderNo)
            wx.showToast({ title: '支付成功！', icon: 'success' })
            this.fetchDetail()
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
  async handleCancelOrder() {
    wx.showModal({
      title: '取消订单',
      content: '确定要取消该订单吗？',
      success: async res => {
        if (res.confirm) {
          try {
            await cancelOrder(this.data.orderNo)
            wx.showToast({ title: '订单已取消', icon: 'success' })
            this.fetchDetail()
          } catch (e) {
            console.error('取消失败:', e)
          }
        }
      }
    })
  },

  /**
   * 申请退款
   */
  async handleRefund() {
    wx.showModal({
      title: '申请退款',
      content: '确定申请退款并撤回本次出餐吗？',
      confirmText: '申请退款',
      confirmColor: '#ef4444',
      success: async res => {
        if (res.confirm) {
          try {
            await requestRefund(this.data.orderNo, '用户在小程序端主动撤单')
            wx.showToast({ title: '退款申请已提交', icon: 'success' })
            this.fetchDetail()
          } catch (e) {
            console.error('退款失败:', e)
          }
        }
      }
    })
  },

  /**
   * 导航至门店
   */
  handleOpenNavigation() {
    const store = this.data.order && this.data.order.store
    if (!store || !store.lat || !store.lng) {
      wx.showToast({ title: '暂无门店坐标', icon: 'none' })
      return
    }
    openMapNavigation(store.lat, store.lng, store.name, store.address)
  },

  /**
   * 再来一单
   */
  handleReOrder() {
    wx.switchTab({
      url: '/pages/menu/menu'
    })
  },

  handleGoInvoice() {
    if (this.data.orderNo) {
      wx.navigateTo({
        url: `/pages/invoice/invoice?order_no=${this.data.orderNo}`
      })
    }
  }
})
