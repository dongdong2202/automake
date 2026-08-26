// pages/invoice/invoice.js
const { getInvoice, applyInvoice, getOrderDetail } = require('../../services/order')
const { fenToYuan } = require('../../utils/price')

Page({
  data: {
    orderNo: '',
    order: null,
    invoice: null,
    loading: true,
    invoiceType: 'personal',
    title: '',
    taxNo: '',
    email: '',
    isSubmitting: false
  },

  onLoad(options) {
    if (options && options.order_no) {
      this.setData({ orderNo: options.order_no })
      this.fetchInvoiceData()
    }
  },

  async fetchInvoiceData() {
    this.setData({ loading: true })
    try {
      const [orderRes, invoiceRes] = await Promise.allSettled([
        getOrderDetail(this.data.orderNo),
        getInvoice(this.data.orderNo)
      ])

      let order = null
      let invoice = null

      if (orderRes.status === 'fulfilled' && orderRes.value) {
        order = orderRes.value.data || orderRes.value
      }
      if (invoiceRes.status === 'fulfilled' && invoiceRes.value) {
        invoice = invoiceRes.value.data || invoiceRes.value
      }

      this.setData({
        order,
        invoice,
        amountYuan: order ? fenToYuan(order.pay_amount || order.total_amount) : '0.00',
        loading: false
      })

    } catch (e) {
      console.error('获取发票数据失败:', e)
      this.setData({ loading: false })
    }
  },

  handleTypeChange(e) {
    this.setData({ invoiceType: e.detail.value })
  },

  handleInput(e) {
    const field = e.currentTarget.dataset.field
    this.setData({ [field]: e.detail.value })
  },

  async handleSubmitInvoice() {
    const { orderNo, invoiceType, title, taxNo, email, isSubmitting } = this.data
    if (isSubmitting) return

    if (!title.trim()) {
      wx.showToast({ title: '请输入发票抬头', icon: 'none' })
      return
    }
    if (invoiceType === 'company' && !taxNo.trim()) {
      wx.showToast({ title: '请输入企业税号', icon: 'none' })
      return
    }
    if (!email.trim() || !email.includes('@')) {
      wx.showToast({ title: '请输入正确的邮箱', icon: 'none' })
      return
    }

    this.setData({ isSubmitting: true })

    try {
      await applyInvoice(orderNo, {
        invoice_type: invoiceType,
        title: title.trim(),
        tax_no: taxNo.trim(),
        email: email.trim()
      })

      wx.showToast({ title: '发票申请成功！', icon: 'success' })
      this.fetchInvoiceData()

    } catch (e) {
      wx.showToast({ title: e.message || '申请失败', icon: 'none' })
    } finally {
      this.setData({ isSubmitting: false })
    }
  },

  handleCopyDownloadUrl() {
    if (this.data.invoice && this.data.invoice.invoice_url) {
      wx.setClipboardData({
        data: this.data.invoice.invoice_url,
        success: () => {
          wx.showToast({ title: '下载链接已复制', icon: 'success' })
        }
      })
    }
  }
})
