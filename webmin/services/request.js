/**
 * 统一网络请求客户端
 * 支持 JWT 认证自动注入、401 自动刷新 Token 重试、请求超时及错误拦截
 */

const CONFIG = require('./config')

let isRefreshing = false
let refreshSubscribers = []

function subscribeTokenRefresh(cb) {
  refreshSubscribers.push(cb)
}

function onTokenRefreshed(newToken) {
  refreshSubscribers.forEach(cb => cb(newToken))
  refreshSubscribers = []
}

/**
 * 刷新 JWT Access Token
 */
function refreshToken() {
  const refresh = wx.getStorageSync('refresh_token')
  if (!refresh) {
    return Promise.reject(new Error('未找到 refresh token'))
  }

  return new Promise((resolve, reject) => {

    wx.request({
      url: `${CONFIG.BASE_URL}/api/user/token/refresh`,
      method: 'POST',
      data: { refresh },
      header: { 'Content-Type': 'application/json' },
      timeout: CONFIG.TIMEOUT,
      success(res) {
        if (res.statusCode === 200 && res.data && res.data.access) {
          const newAccess = res.data.access
          wx.setStorageSync('access_token', newAccess)
          if (res.data.refresh) {
            wx.setStorageSync('refresh_token', res.data.refresh)
          }
          resolve(newAccess)
        } else {
          // Refresh Token 也已失效，需重新登录
          wx.removeStorageSync('access_token')
          wx.removeStorageSync('refresh_token')
          reject(new Error('Token 刷新失败，请重新登录'))
        }
      },
      fail(err) {
        reject(err)
      }
    })
  })
}

/**
 * 核心请求方法
 * @param {Object} options 请求配置
 * @param {string} options.url 相对路径（例如 /api/store/list）
 * @param {string} [options.method='GET'] HTTP 方法
 * @param {Object} [options.data] 请求数据
 * @param {Object} [options.header] 额外请求头
 * @param {boolean} [options.showLoading=false] 是否显示加载动画
 * @param {string} [options.loadingText='加载中...'] 加载文本
 * @param {boolean} [options.showError=true] 失败时是否自动弹出 Toast
 * @returns {Promise<any>}
 */

const pendingRequests = new Map()

function generateReqKey(url, method, data) {
  return `${method}:${url}:${JSON.stringify(data || {})}`
}

function request(options = {}) {
  const {
    url,
    method = 'GET',
    data = {},
    header = {},
    showLoading = false,
    loadingText = '加载中...',
    showError = true
  } = options

  if (showLoading) {
    wx.showLoading({ title: loadingText, mask: true })
  }

  const token = wx.getStorageSync('access_token')
  const reqHeader = {
    'Content-Type': 'application/json',
    ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
    ...header
  }

  const fullUrl = url.startsWith('http') ? url : `${CONFIG.BASE_URL}${url}`


  const reqKey = generateReqKey(fullUrl, method, data)
  if (['POST', 'PUT', 'DELETE'].includes(method.toUpperCase())) {
    if (pendingRequests.has(reqKey)) {
      return Promise.reject(new Error('请求处理中，请勿重复操作'))
    }
    pendingRequests.set(reqKey, true)
  }

  return new Promise((resolve, reject) => {

    wx.request({
      url: fullUrl,
      method: method.toUpperCase(),
      data,
      header: reqHeader,
      timeout: CONFIG.TIMEOUT,
      success(res) {
        if (showLoading) {
          wx.hideLoading()
        }
        pendingRequests.delete(reqKey)

        // 1. 拦截 401 认证过期
        if (res.statusCode === 401) {
          if (!isRefreshing) {
            isRefreshing = true
            refreshToken()
              .then(newToken => {
                isRefreshing = false
                onTokenRefreshed(newToken)
              })
              .catch(() => {
                isRefreshing = false
                refreshSubscribers = []
              })
          }

          // 将当前请求排队重试
          return new Promise(retryResolve => {
            subscribeTokenRefresh(() => {
              retryResolve(request(options))
            })
          }).then(resolve).catch(reject)
        }

        // 2. HTTP 状态码成功 (200 ~ 299)
        if (res.statusCode >= 200 && res.statusCode < 300) {
          const body = res.data
          // 如果后端返回标准 ok 结构 { code: 200/0, data: ..., message: ... }
          if (body && typeof body === 'object' && ('code' in body)) {
            if (body.code === 200 || body.code === 0) {
              resolve(body.data !== undefined ? body.data : body)
            } else {
              const errMsg = body.message || body.msg || '业务处理失败'
              if (showError) {
                wx.showToast({ title: errMsg, icon: 'none', duration: 2500 })
              }
              reject(new Error(errMsg))
            }
          } else {
            // 直接返回 HTTP 响应体
            resolve(body)
          }
        } else {
          // 3. HTTP 错误处理
          const errorMsg = (res.data && (res.data.message || res.data.detail)) || `请求失败 (${res.statusCode})`
          if (showError) {
            wx.showToast({ title: errorMsg, icon: 'none', duration: 2500 })
          }
          reject(new Error(errorMsg))
        }
      },
      fail(err) {
        if (showLoading) {
          wx.hideLoading()
        }
        pendingRequests.delete(reqKey)
        const msg = err.errMsg && err.errMsg.includes('timeout') ? '请求超时，请检查网络' : '网络连接异常，请重试'
        if (showError) {
          wx.showToast({ title: msg, icon: 'none', duration: 2500 })
        }
        reject(err)
      }
    })
  })
}

module.exports = {
  request,
  get: (url, data, options = {}) => request({ url, method: 'GET', data, ...options }),
  post: (url, data, options = {}) => request({ url, method: 'POST', data, ...options }),
  put: (url, data, options = {}) => request({ url, method: 'PUT', data, ...options }),
  del: (url, data, options = {}) => request({ url, method: 'DELETE', data, ...options })
}
