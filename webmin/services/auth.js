/**
 * 用户认证与授权服务
 */

const { post, get } = require('./request')

/**
 * 微信静默登录
 * @returns {Promise<any>}
 */
function silentLogin() {
  return new Promise((resolve, reject) => {
    wx.login({
      success(res) {
        if (res.code) {
          post('/api/user/login', { code: res.code }, { showError: false })
            .then(data => {
              if (data && data.access) {
                wx.setStorageSync('access_token', data.access)
                if (data.refresh) {
                  wx.setStorageSync('refresh_token', data.refresh)
                }
                if (data.user) {
                  wx.setStorageSync('user_info', data.user)
                }
                resolve(data.user)
              } else {
                reject(new Error('登录未返回有效的 Token'))
              }
            })
            .catch(err => {
              console.warn('静默登录换取 Token 失败:', err)
              reject(err)
            })
        } else {
          reject(new Error('获取微信登录 Code 失败'))
        }
      },
      fail(err) {
        reject(err)
      }
    })
  })
}

/**
 * 更新用户头像与昵称
 * @param {Object} profile { nickname, avatar_url, sex, age }
 */
function updateProfile(profile) {
  return post('/api/user/profile', profile).then(user => {
    wx.setStorageSync('user_info', user)
    return user
  })
}

/**
 * 获取当前用户信息
 */
function fetchUserProfile() {
  return get('/api/user/profile').then(user => {
    wx.setStorageSync('user_info', user)
    return user
  })
}

/**
 * 检查当前是否已登录
 * @returns {boolean}
 */
function isLoggedIn() {
  return !!wx.getStorageSync('access_token')
}

/**
 * 退出登录
 */
function logout() {
  wx.removeStorageSync('access_token')
  wx.removeStorageSync('refresh_token')
  wx.removeStorageSync('user_info')
}

/**
 * 微信一键授权登录 (登录 + 绑定手机号 + 初始化微信资料)
 * @param {string} phoneCode 微信 getPhoneNumber 返回的凭证
 * @returns {Promise<any>}
 */
function oneClickLogin(phoneCode) {
  return new Promise((resolve, reject) => {
    wx.login({
      success(res) {
        if (res.code) {
          const payload = { code: res.code }
          if (phoneCode) {
            payload.phone = phoneCode
          }
          post('/api/user/login', payload)
            .then(data => {
              if (data && data.access) {
                wx.setStorageSync('access_token', data.access)
                if (data.refresh) {
                  wx.setStorageSync('refresh_token', data.refresh)
                }
                if (data.user) {
                  wx.setStorageSync('user_info', data.user)
                }
                resolve(data.user)
              } else {
                reject(new Error('登录未返回有效的 Token'))
              }
            })
            .catch(err => {
              console.warn('一键登录失败:', err)
              reject(err)
            })
        } else {
          reject(new Error('获取微信登录 Code 失败'))
        }
      },
      fail(err) {
        reject(err)
      }
    })
  })
}

module.exports = {
  silentLogin,
  oneClickLogin,
  updateProfile,
  fetchUserProfile,
  isLoggedIn,
  logout
}
