const CONFIG = require('../services/config')

const formatTime = date => {
  const year = date.getFullYear()
  const month = date.getMonth() + 1
  const day = date.getDate()
  const hour = date.getHours()
  const minute = date.getMinutes()
  const second = date.getSeconds()

  return `${[year, month, day].map(formatNumber).join('/')} ${[hour, minute, second].map(formatNumber).join(':')}`
}

const formatNumber = n => {
  n = n.toString()
  return n[1] ? n : `0${n}`
}

/**
 * 微信小程序图片地址统一解析工具
 * 自动为后端返回的相对路径补全 BASE_URL 域名
 */
function formatImageUrl(url) {
  if (!url) return ''
  const raw = String(url).trim()
  if (!raw) return ''

  if (raw.startsWith('http://') || raw.startsWith('https://') || raw.startsWith('data:')) {
    return raw
  }

  if (raw.startsWith('/images/')) {
    return raw
  }

  if (raw.startsWith('/')) {
    return `${CONFIG.BASE_URL}${raw}`
  }

  if (raw.startsWith('media/')) {
    return `${CONFIG.BASE_URL}/${raw}`
  }

  return `${CONFIG.BASE_URL}/media/${raw}`
}

module.exports = {
  formatTime,
  formatImageUrl
}
