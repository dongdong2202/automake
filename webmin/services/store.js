/**
 * 门店与设备服务
 */

const { get } = require('./request')

/**
 * 获取营业中门店列表
 */
function getStoreList() {
  return get('/api/store/list')
}

/**
 * 获取门店详情
 * @param {number} storeId 门店 ID
 */
function getStoreDetail(storeId) {
  return get(`/api/store/${storeId}/`)
}

module.exports = {
  getStoreList,
  getStoreDetail
}
