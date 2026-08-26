/**
 * 日期时间与营业时间处理工具 (基于北京时间 CST, UTC+8)
 */

/**
 * 获取指定时间或当前时间的北京时间 (UTC+8) 分量
 * 无论用户手机系统、开发者工具处于哪个时区，均精确换算为北京时间
 * @param {string|number|Date} [dateInput] 可选输入时间，默认当前时间
 * @returns {{ year: number, month: number, day: number, weekdayIdx: number, weekdayKey: string, hours: number, minutes: number, seconds: number, totalMinutes: number }}
 */
function getBeijingTimeComponents(dateInput) {
  let d
  if (!dateInput) {
    d = new Date()
  } else if (typeof dateInput === 'string') {
    // 兼容没有时区标识的 ISO 字符串
    if (dateInput.includes('T') && !dateInput.endsWith('Z') && !dateInput.includes('+')) {
      d = new Date(dateInput + '+08:00')
    } else {
      d = new Date(dateInput)
    }
  } else {
    d = new Date(dateInput)
  }

  if (isNaN(d.getTime())) {
    d = new Date()
  }

  // d.getTime() 是 UTC 毫秒数，加 8 小时即为北京时间绝对毫秒
  const bjDate = new Date(d.getTime() + (8 * 3600 * 1000))

  const weekdays = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat']
  const weekdayIdx = bjDate.getUTCDay()
  const hours = bjDate.getUTCHours()
  const minutes = bjDate.getUTCMinutes()
  const seconds = bjDate.getUTCSeconds()

  return {
    year: bjDate.getUTCFullYear(),
    month: bjDate.getUTCMonth() + 1,
    day: bjDate.getUTCDate(),
    weekdayIdx,
    weekdayKey: weekdays[weekdayIdx],
    hours,
    minutes,
    seconds,
    totalMinutes: hours * 60 + minutes
  }
}

/**
 * 格式化 ISO 日期时间为北京时间字符串 (例如 "2026-08-25 13:30")
 * @param {string|Date} dateStr
 * @returns {string}
 */
function formatDateTime(dateStr) {
  if (!dateStr) return '-'
  const bj = getBeijingTimeComponents(dateStr)
  const month = String(bj.month).padStart(2, '0')
  const day = String(bj.day).padStart(2, '0')
  const hours = String(bj.hours).padStart(2, '0')
  const minutes = String(bj.minutes).padStart(2, '0')
  
  return `${bj.year}-${month}-${day} ${hours}:${minutes}`
}

/**
 * 格式化营业时间展示（基于北京时间判定今日）
 * @param {Object} businessHours 营业时间对象 {"mon": "08:00-22:00", ...}
 * @returns {string}
 */
function formatBusinessHours(businessHours) {
  if (!businessHours || typeof businessHours !== 'object' || Object.keys(businessHours).length === 0) {
    return '全天营业 (00:00-24:00)'
  }

  const hasAny = Object.values(businessHours).some(v => v && String(v).trim())
  if (!hasAny) {
    return '全天营业 (00:00-24:00)'
  }
  
  const bj = getBeijingTimeComponents()
  const todayKey = bj.weekdayKey
  
  if (businessHours[todayKey] !== undefined && businessHours[todayKey] !== null) {
    const val = String(businessHours[todayKey]).trim()
    if (val.toLowerCase() === 'closed' || val === '已打烊' || val === '休息' || val === '今日休息') {
      return '今日 休息'
    }
    if (val === '' || val.toLowerCase() === '24h' || val === '全天营业' || val === '00:00-24:00' || val === '全天') {
      return '全天营业 (00:00-24:00)'
    }
    return `今日 ${val}`
  }
  
  return '全天营业 (00:00-24:00)'
}

/**
 * 获取门店/设备营业状态详情（基于北京时间 UTC+8）
 * 当对应星期配置为 closed 时，返回 "今日休息"；
 * 当不在营业时间时，返回 "打烊中"；
 * 当处于营业时间时，返回 "营业中"。
 * @param {Object} store
 * @returns {{ isOpen: boolean, statusText: string, isRestToday: boolean }}
 */
function getStoreBusinessStatus(store) {
  if (!store) {
    return { isOpen: false, statusText: '打烊中', isRestToday: false }
  }

  // 1. 门店本身非 open 状态
  if (store.status && store.status !== 'open') {
    return { isOpen: false, statusText: '已打烊', isRestToday: false }
  }

  // 2. 设备本身处于非 online 状态（直接视同打烊，不提示生硬的“设备离线”）
  if (store.device_status && store.device_status !== 'online') {
    return { isOpen: false, statusText: '打烊中', isRestToday: false }
  }

  const bj = getBeijingTimeComponents()
  const todayKey = bj.weekdayKey
  const hours = store.business_hours || {}

  // 3. 检查是否所有星期均留空（全留空 = 全天 24 小时营业）
  const hasAny = Object.values(hours).some(v => v && String(v).trim())
  if (!hasAny) {
    return { isOpen: true, statusText: '营业中', isRestToday: false }
  }

  const todayRange = hours[todayKey]

  // 4. 如果今天显式标注打烊/休息
  if (todayRange !== undefined && todayRange !== null) {
    const lower = String(todayRange).trim().toLowerCase()
    if (lower === 'closed' || lower === '已打烊' || lower === '休息' || lower === '今日休息') {
      return { isOpen: false, statusText: '今日休息', isRestToday: true }
    }
    if (lower === '' || lower === '24h' || lower === '全天' || lower === '00:00-24:00') {
      return { isOpen: true, statusText: '营业中', isRestToday: false }
    }
  }

  // 4. 如果配置了今日时间段 (如 "08:00-22:00")
  if (todayRange && String(todayRange).includes('-')) {
    try {
      const [startStr, endStr] = String(todayRange).split('-')
      const [startH, startM] = startStr.trim().split(':').map(Number)
      const [endH, endM] = endStr.trim().split(':').map(Number)
      const currentMins = bj.totalMinutes
      const startMins = startH * 60 + startM
      const endMins = endH * 60 + endM

      let inHours = false
      if (startMins <= endMins) {
        inHours = currentMins >= startMins && currentMins <= endMins
      } else {
        inHours = currentMins >= startMins || currentMins <= endMins
      }

      if (inHours && store.is_in_business_hours !== false) {
        return { isOpen: true, statusText: '营业中', isRestToday: false }
      } else {
        return { isOpen: false, statusText: '打烊中', isRestToday: false }
      }
    } catch (e) {
      return { isOpen: false, statusText: '打烊中', isRestToday: false }
    }
  }

  // 5. 若未配置具体时间段，但后端接口有返回 business_status_text，优先采用
  if (store.business_status_text) {
    const isOpen = store.is_in_business_hours !== false && store.business_status_text === '营业中'
    return {
      isOpen,
      statusText: store.business_status_text,
      isRestToday: store.business_status_text === '今日休息'
    }
  }

  if (store.is_in_business_hours === false) {
    return { isOpen: false, statusText: '打烊中', isRestToday: false }
  }

  return { isOpen: true, statusText: '营业中', isRestToday: false }
}

/**
 * 判断门店/设备是否处于营业状态
 * @param {Object} store
 * @returns {boolean}
 */
function checkIsStoreOpen(store) {
  return getStoreBusinessStatus(store).isOpen
}

module.exports = {
  getBeijingTimeComponents,
  formatDateTime,
  formatBusinessHours,
  getStoreBusinessStatus,
  checkIsStoreOpen
}

