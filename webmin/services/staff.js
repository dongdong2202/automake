/**
 * 物料员与协调员服务
 */

const { get, post } = require('./request')

/**
 * 获取可管理的设备列表
 */
function getStaffDevices() {
  return get('/api/staff/devices')
}

/**
 * 获取指定设备的耗材与物料库存
 * @param {string} deviceSn
 */
function getStaffDeviceStock(deviceSn) {
  return get(`/api/staff/devices/${deviceSn}/stock`)
}

/**
 * 物料员手动更新耗材库存数量
 * @param {string} deviceSn 设备序列号
 * @param {Array} items [{ code: 'paperL', quantity: 80 }, ...]
 */
function updateConsumables(deviceSn, items) {
  return post('/api/staff/consumables/update', {
    device_sn: deviceSn,
    items
  }, { showLoading: true, loadingText: '正在同步云端库存...' })
}

/**
 * 协调员下发设备指令
 * @param {string} deviceSn 设备序列号
 * @param {string} action 'reset' | 'sync' | 'dispense'
 */
function sendDeviceAction(deviceSn, action) {
  return post(`/api/staff/devices/${deviceSn}/action`, { action }, {
    showLoading: true,
    loadingText: `正在下发 ${action} 指令...`
  })
}

module.exports = {
  getStaffDevices,
  getStaffDeviceStock,
  updateConsumables,
  sendDeviceAction
}
