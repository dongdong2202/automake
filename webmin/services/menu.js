/**
 * 菜单与规格服务
 */

const { get } = require('./request')

/**
 * 获取指定设备/门店的完整菜单数据（按分类归集商品及对应有效规格 SKU）
 * @param {string|number} deviceSn 设备序列号或门店 ID
 * @returns {Promise<any>}
 */
function getStoreMenu(deviceSn) {
  return get(`/api/menu/store/${deviceSn}`)
}

/**
 * 获取指定设备/门店已售罄的饮品菜单 ID 列表（物料总量 < 10 时售罄）
 * @param {string|number} deviceSn 设备序列号或门店 ID
 * @returns {Promise<any>}
 */
function getSoldOutItems(deviceSn) {
  return get(`/api/menu/sold-out/${deviceSn}`)
}

module.exports = {
  getStoreMenu,
  getSoldOutItems
}
