/**
 * 地理定位与距离计算工具
 */

/**
 * 角度转弧度
 */
function toRad(d) {
  return (d * Math.PI) / 180.0
}

/**
 * 基于 Haversine 公式计算两个经纬度之间的球面距离（单位：米）
 * @param {number} lat1 纬度1
 * @param {number} lng1 经度1
 * @param {number} lat2 纬度2
 * @param {number} lng2 经度2
 * @returns {number} 距离（米）
 */
function getDistance(lat1, lng1, lat2, lng2) {
  if (!lat1 || !lng1 || !lat2 || !lng2) return 0
  const R = 6378137.0 // 地球半径 (米)
  const radLat1 = toRad(Number(lat1))
  const radLat2 = toRad(Number(lat2))
  const a = radLat1 - radLat2
  const b = toRad(Number(lng1)) - toRad(Number(lng2))
  
  let s = 2 * Math.asin(
    Math.sqrt(
      Math.pow(Math.sin(a / 2), 2) +
      Math.cos(radLat1) * Math.cos(radLat2) * Math.pow(Math.sin(b / 2), 2)
    )
  )
  s = s * R
  return Math.round(s)
}

/**
 * 格式化距离文本 (例如 320m, 1.5km)
 * @param {number} meters 距离（米）
 * @returns {string}
 */
function formatDistance(meters) {
  if (meters === null || meters === undefined || isNaN(meters)) {
    return '未知距离'
  }
  if (meters < 1000) {
    return `${Math.round(meters)}m`
  }
  return `${(meters / 1000).toFixed(1)}km`
}

/**
 * 获取当前设备经纬度位置 (Promise 包装)
 * @returns {Promise<{ latitude: number, longitude: number }>}
 */
function getCurrentLocation() {
  return new Promise((resolve, reject) => {
    wx.getLocation({
      type: 'gcj02',
      success: res => {
        resolve({
          latitude: res.latitude,
          longitude: res.longitude
        })
      },
      fail: err => {
        console.warn('获取用户地理位置失败:', err)
        reject(err)
      }
    })
  })
}

/**
 * 打开地图导航至目标经纬度
 * @param {number} latitude 目标纬度
 * @param {number} longitude 目标经度
 * @param {string} name 门店名称
 * @param {string} address 详细地址
 */
function openMapNavigation(latitude, longitude, name = '', address = '') {
  if (!latitude || !longitude) {
    wx.showToast({ title: '暂无该门店坐标信息', icon: 'none' })
    return
  }
  wx.openLocation({
    latitude: Number(latitude),
    longitude: Number(longitude),
    name: name,
    address: address,
    scale: 16
  })
}

module.exports = {
  getDistance,
  formatDistance,
  getCurrentLocation,
  openMapNavigation
}
