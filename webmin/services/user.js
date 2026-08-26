/**
 * 用户资料与会员营销服务
 */

const { get, post } = require('./request')

function getProfile() {
  return get('/api/user/profile')
}

function updateProfile(data) {
  return post('/api/user/profile', data)
}

function bindPhone(phone) {
  return post('/api/user/phone/bind', { phone }, {
    showLoading: true,
    loadingText: '正在绑定手机号...'
  })
}

function getCoupons(status = 'available') {
  return get('/api/user/coupons', { status })
}

function claimCoupon(payload = {}) {
  return post('/api/user/coupons/claim', payload, {
    showLoading: true,
    loadingText: '正在领取优惠券...'
  })
}

function getPoints() {
  return get('/api/user/points')
}

module.exports = {
  getProfile,
  updateProfile,
  bindPhone,
  getCoupons,
  claimCoupon,
  getPoints
}
