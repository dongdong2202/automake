// pages/cart/cart.js
const app = getApp()
const { precheckOrder, createOrder, applyInvoice } = require('../../services/order')
const { createPayment, mockSuccessPayment, invokeWechatPay } = require('../../services/pay')
const { getCoupons } = require('../../services/user')
const { fenToYuan } = require('../../utils/price')

Page({
  data: {
    currentStore: null,
    cartList: [],
    remark: '',
    totalCount: 0,
    rawTotalAmount: 0,          // 原始总价（分）
    rawTotalYuan: '0.00',
    discountAmount: 0,          // 优惠券/活动立减金额（分）
    discountYuan: '0.00',
    payAmount: 0,               // 实付金额（分）
    payAmountYuan: '0.00',
    isSubmitting: false,
    orderToken: '',
    
    // 优惠券弹窗
    showCouponModal: false,
    availableCoupons: [],
    selectedCoupon: null,
    
    // 发票信息
    needInvoice: false,
    invoiceType: 'personal',   // 'personal' | 'company'
    invoiceTitle: '',
    invoiceTaxNo: '',
    invoiceEmail: ''
  },

  onShow() {
    this.initCartData()
  },

  async initCartData() {
    const store = app.globalData.currentStore
    const cart = app.globalData.cart || []

    if (!store || cart.length === 0) {
      this.setData({
        currentStore: store,
        cartList: [],
        totalCount: 0,
        rawTotalYuan: '0.00',
        payAmountYuan: '0.00'
      })
      return
    }

    const totalCount = app.getCartCount()
    const totalAmount = app.getCartTotalAmount()

    const formattedCart = cart.map((item, index) => ({
      ...item,
      index,
      unitPriceYuan: fenToYuan(item.unitPrice),
      subtotalYuan: fenToYuan(item.subtotal),
      skuDesc: (item.selectedSkus || []).map(s => s.name).join(' / ')
    }))

    this.setData({
      currentStore: store,
      cartList: formattedCart,
      totalCount,
      rawTotalAmount: totalAmount,
      rawTotalYuan: fenToYuan(totalAmount),
      orderToken: `MP_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`
    })

    // 获取并自动匹配最佳优惠券
    await this.fetchCouponsAndCalculate(totalAmount)
    this.handlePrecheck()
  },

  /**
   * 获取用户优惠券并自动选择最优优惠券
   */
  async fetchCouponsAndCalculate(totalAmount) {
    try {
      const res = await getCoupons('available')
      const coupons = Array.isArray(res) ? res : (res.data || [])
      
      // 筛选满足门槛的可用优惠券
      const validCoupons = coupons.map(c => {
        let isUsable = totalAmount >= (c.min_spend || 0)
        let calcDiscount = 0
        if (isUsable) {
          if (c.coupon_type === 'discount') {
            calcDiscount = Math.round(totalAmount * (100 - c.discount_rate) / 100)
          } else {
            calcDiscount = c.amount || 0
          }
        }
        return {
          ...c,
          isUsable,
          calcDiscount,
          amountYuan: fenToYuan(c.amount),
          minSpendYuan: fenToYuan(c.min_spend)
        }
      })

      // 选出立减金额最大的优惠券
      let best = null
      validCoupons.forEach(c => {
        if (c.isUsable && (!best || c.calcDiscount > best.calcDiscount)) {
          best = c
        }
      })

      const discount = best ? best.calcDiscount : 0
      const finalPay = Math.max(0, totalAmount - discount)

      this.setData({
        availableCoupons: validCoupons,
        selectedCoupon: best,
        discountAmount: discount,
        discountYuan: fenToYuan(discount),
        payAmount: finalPay,
        payAmountYuan: fenToYuan(finalPay)
      })

    } catch (e) {
      console.warn('获取优惠券失败:', e)
      this.setData({
        discountAmount: 0,
        discountYuan: '0.00',
        payAmount: totalAmount,
        payAmountYuan: fenToYuan(totalAmount)
      })
    }
  },

  /**
   * 打开选择优惠券弹窗
   */
  handleOpenCouponModal() {
    this.setData({ showCouponModal: true })
  },

  handleCloseCouponModal() {
    this.setData({ showCouponModal: false })
  },

  /**
   * 选择某张优惠券或不使用优惠券
   */
  handleSelectCoupon(e) {
    const coupon = e.currentTarget.dataset.coupon
    const { rawTotalAmount } = this.data

    if (!coupon) {
      // 不使用优惠券
      this.setData({
        selectedCoupon: null,
        discountAmount: 0,
        discountYuan: '0.00',
        payAmount: rawTotalAmount,
        payAmountYuan: fenToYuan(rawTotalAmount),
        showCouponModal: false
      })
      return
    }

    if (!coupon.isUsable) {
      wx.showToast({ title: `未达到使用门槛 (需满¥${coupon.minSpendYuan})`, icon: 'none' })
      return
    }

    const discount = coupon.calcDiscount
    const finalPay = Math.max(0, rawTotalAmount - discount)

    this.setData({
      selectedCoupon: coupon,
      discountAmount: discount,
      discountYuan: fenToYuan(discount),
      payAmount: finalPay,
      payAmountYuan: fenToYuan(finalPay),
      showCouponModal: false
    })
  },

  /**
   * 切换开票开关
   */
  handleToggleInvoice() {
    this.setData({ needInvoice: !this.data.needInvoice })
  },

  handleInvoiceTypeChange(e) {
    this.setData({ invoiceType: e.detail.value })
  },

  handleInvoiceInput(e) {
    const field = e.currentTarget.dataset.field
    this.setData({ [field]: e.detail.value })
  },

  /**
   * 订单预校验
   */
  async handlePrecheck() {
    const { currentStore, cartList } = this.data
    if (!currentStore || cartList.length === 0) return

    const precheckItems = cartList.map(ci => ({
      item: ci.item.id,
      sku: (ci.selectedSkus || []).map(s => s.id),
      quantity: ci.quantity
    }))

    const deviceSn = currentStore.device_sn || (currentStore.devices && currentStore.devices[0] && currentStore.devices[0].device_sn) || ''

    try {
      await precheckOrder(currentStore.id, precheckItems, deviceSn)
    } catch (err) {
      console.warn('预校验提示:', err)
    }
  },

  handleQuantityChange(e) {
    const { index, delta } = e.currentTarget.dataset
    app.updateCartQuantity(index, Number(delta))
    this.initCartData()
  },

  handleClearAll() {
    wx.showModal({
      title: '确认清空',
      content: '确定移除购物车中的所有商品吗？',
      success: res => {
        if (res.confirm) {
          app.clearCart()
          this.initCartData()
        }
      }
    })
  },

  handleRemarkInput(e) {
    this.setData({ remark: e.detail.value })
  },

  /**
   * 提交订单并唤起支付
   */
  async handleSubmitOrder() {
    const { 
      currentStore, cartList, remark, orderToken, isSubmitting, 
      needInvoice, invoiceType, invoiceTitle, invoiceTaxNo, invoiceEmail 
    } = this.data

    if (isSubmitting) return

    if (!currentStore) {
      wx.showToast({ title: '未选择门店', icon: 'none' })
      return
    }

    if (cartList.length === 0) {
      wx.showToast({ title: '购物车为空', icon: 'none' })
      return
    }

    if (needInvoice) {
      if (!invoiceTitle.trim()) {
        wx.showToast({ title: '请填写发票抬头', icon: 'none' })
        return
      }
      if (invoiceType === 'company' && !invoiceTaxNo.trim()) {
        wx.showToast({ title: '请填写企业税号', icon: 'none' })
        return
      }
      if (!invoiceEmail.trim() || !invoiceEmail.includes('@')) {
        wx.showToast({ title: '请填写正确的接收邮箱', icon: 'none' })
        return
      }
    }

    this.setData({ isSubmitting: true })

    try {
      const deviceSn = currentStore.device_sn || (currentStore.devices && currentStore.devices[0] && currentStore.devices[0].device_sn) || ''
      const orderPayload = {
        store_id: currentStore.id,
        device_sn: deviceSn,
        remark: remark || '',
        order_token: orderToken,
        items: cartList.map(ci => ({
          item: ci.item.id,
          sku: (ci.selectedSkus || []).map(s => s.id),
          quantity: ci.quantity
        }))
      }

      // 1. 创建订单
      const orderRes = await createOrder(orderPayload)
      const orderData = orderRes.data || orderRes
      const orderNo = orderData.order_no

      if (!orderNo) {
        throw new Error('下单失败：未返回订单号')
      }

      // 2. 发票信息预录
      if (needInvoice) {
        try {
          await applyInvoice(orderNo, {
            invoice_type: invoiceType,
            title: invoiceTitle.trim(),
            tax_no: invoiceTaxNo.trim(),
            email: invoiceEmail.trim()
          })
        } catch (invErr) {
          console.warn('发票预申请提示:', invErr)
        }
      }

      // 3. 支付流程
      try {
        const payRes = await createPayment(orderNo)
        const payParams = (payRes.data && payRes.data.pay_params) || payRes.pay_params || payRes

        if (payParams && payParams.timeStamp && payParams.paySign) {
          await invokeWechatPay(payParams)
        } else {
          await mockSuccessPayment(orderNo)
        }
      } catch (payErr) {
        console.warn('调起微信支付未完成，提供模拟支付选项')
        wx.showModal({
          title: '支付提示',
          content: '微信支付未完成，是否使用【模拟支付】完成本次出杯？',
          confirmText: '模拟支付',
          cancelText: '稍后支付',
          success: async (modalRes) => {
            if (modalRes.confirm) {
              await mockSuccessPayment(orderNo)
              app.clearCart()
              wx.redirectTo({
                url: `/pages/order-detail/order-detail?order_no=${orderNo}`
              })
            } else {
              app.clearCart()
              wx.redirectTo({
                url: `/pages/order-detail/order-detail?order_no=${orderNo}`
              })
            }
          }
        })
        this.setData({ isSubmitting: false })
        return
      }

      app.clearCart()
      wx.showToast({ title: '支付成功！', icon: 'success' })
      setTimeout(() => {
        wx.redirectTo({
          url: `/pages/order-detail/order-detail?order_no=${orderNo}`
        })
      }, 1000)

    } catch (err) {
      console.error('提交订单失败:', err)
      this.setData({ isSubmitting: false })
      wx.showToast({ title: err.message || '提交订单失败', icon: 'none' })
    }
  },

  handleGoMenu() {
    wx.switchTab({
      url: '/pages/menu/menu'
    })
  }
})
