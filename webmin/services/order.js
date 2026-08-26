/**
 * 订单与出餐状态服务
 */

const { get, post } = require('./request')

/**
 * 下单前预校验（校验库存、计算实付总额及优惠）
 * @param {number} storeId 门店 ID
 * @param {Array} items 商品清单 [{ item: 1, sku: [10, 11], quantity: 1 }, ...]
 * @returns {Promise<any>}
 */
function precheckOrder(storeId, items, deviceSn = '') {
  const payload = {
    store_id: storeId,
    items
  }
  if (deviceSn) {
    payload.device_sn = deviceSn
  }
  return post('/api/order/precheck', payload, { showLoading: true, loadingText: '正在计算金额...' })
}

/**
 * 正式创建订单
 * @param {Object} payload { store_id, items, remark, order_token }
 * @returns {Promise<any>}
 */
function createOrder(payload) {
  return post('/api/order/create', payload, {
    showLoading: true,
    loadingText: '正在提交订单...'
  })
}

/**
 * 获取我的订单列表
 * @param {Object} [params] { page, page_size, status }
 */
function getOrderList(params = {}) {
  return get('/api/order/list', params)
}

/**
 * 获取订单详情
 * @param {string} orderNo 订单号
 */
function getOrderDetail(orderNo) {
  return get(`/api/order/${orderNo}`)
}

/**
 * 取消待支付订单
 * @param {string} orderNo 订单号
 */
function cancelOrder(orderNo) {
  return post(`/api/order/${orderNo}/cancel`, {}, {
    showLoading: true,
    loadingText: '正在取消订单...'
  })
}

/**
 * 轮询订单制作状态、排队等待时间与取餐码
 * @param {string} orderNo 订单号
 */
function getOrderStatusAndPickup(orderNo) {
  return get(`/api/notify/order/${orderNo}/status/`, {}, { showError: false })
}

/**
 * 申请开具电子发票
 * @param {string} orderNo 订单号
 * @param {Object} payload { invoice_type, title, tax_no, email }
 */
function applyInvoice(orderNo, payload) {
  return post(`/api/order/${orderNo}/invoice`, payload, {
    showLoading: true,
    loadingText: '正在提交发票申请...'
  })
}

/**
 * 查询发票详情
 * @param {string} orderNo 订单号
 */
function getInvoice(orderNo) {
  return get(`/api/order/${orderNo}/invoice`)
}

module.exports = {
  precheckOrder,
  createOrder,
  getOrderList,
  getOrderDetail,
  cancelOrder,
  getOrderStatusAndPickup,
  applyInvoice,
  getInvoice
}
