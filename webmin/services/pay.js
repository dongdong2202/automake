/**
 * 微信支付与模拟支付服务
 */

const { post } = require('./request')

/**
 * 创建微信 JSAPI 支付订单，获取调起支付参数
 * @param {string} orderNo 订单号
 * @returns {Promise<any>}
 */
function createPayment(orderNo) {
  return post('/api/pay/create', { order_no: orderNo }, {
    showLoading: true,
    loadingText: '正在拉起支付...'
  })
}

/**
 * 本地开发调试：模拟支付成功
 * @param {string} orderNo 订单号
 * @returns {Promise<any>}
 */
function mockSuccessPayment(orderNo) {
  return post('/api/pay/mock-success', { order_no: orderNo }, {
    showLoading: true,
    loadingText: '正在确认模拟支付...'
  })
}

/**
 * 调起微信原生支付组件
 * @param {Object} payParams { timeStamp, nonceStr, package, signType, paySign }
 * @returns {Promise<any>}
 */
function invokeWechatPay(payParams) {
  return new Promise((resolve, reject) => {
    wx.requestPayment({
      timeStamp: payParams.timeStamp,
      nonceStr: payParams.nonceStr,
      package: payParams.package,
      signType: payParams.signType || 'RSA',
      paySign: payParams.paySign,
      success: res => resolve(res),
      fail: err => {
        // 用户取消支付或网络失败
        if (err.errMsg && err.errMsg.includes('cancel')) {
          wx.showToast({ title: '已取消支付', icon: 'none' })
        } else {
          wx.showToast({ title: err.errMsg || '支付失败', icon: 'none' })
        }
        reject(err)
      }
    })
  })
}

/**
 * 申请用户撤单退款
 * @param {string} orderNo 订单号
 * @param {string} [reason='用户主动申请退款'] 退款原因
 * @returns {Promise<any>}
 */
function requestRefund(orderNo, reason = '用户主动申请退款') {
  return post('/api/pay/refund', {
    order_no: orderNo,
    reason
  }, {
    showLoading: true,
    loadingText: '正在提交退款申请...'
  })
}

module.exports = {
  createPayment,
  mockSuccessPayment,
  invokeWechatPay,
  requestRefund
}
