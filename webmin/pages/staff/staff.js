// pages/staff/staff.js
const { getStaffDevices, getStaffDeviceStock, updateConsumables, sendDeviceAction } = require('../../services/staff')

Page({
  data: {
    activeRole: 'material',   // 'material' (物料员) | 'coordinator' (协调员)
    devices: [],
    selectedDeviceIndex: 0,
    selectedDevice: null,
    stockData: null,
    consumablesEditList: [],
    loading: true,
    isSubmitting: false
  },

  onShow() {
    this.fetchDevices()
  },

  onPullDownRefresh() {
    this.fetchDevices().finally(() => {
      wx.stopPullDownRefresh()
    })
  },

  handleRoleSwitch(e) {
    const role = e.currentTarget.dataset.role
    this.setData({ activeRole: role })
  },

  async fetchDevices() {
    this.setData({ loading: true })
    try {
      const res = await getStaffDevices()
      const list = Array.isArray(res) ? res : (res.data || [])
      
      if (list.length > 0) {
        const curDev = list[this.data.selectedDeviceIndex] || list[0]
        this.setData({
          devices: list,
          selectedDevice: curDev
        }, () => {
          this.fetchDeviceStock(curDev.device_sn)
        })
      } else {
        this.setData({ devices: [], selectedDevice: null, loading: false })
      }
    } catch (e) {
      console.error('获取员工设备失败:', e)
      this.setData({ loading: false })
    }
  },

  async fetchDeviceStock(deviceSn) {
    try {
      const res = await getStaffDeviceStock(deviceSn)
      const data = res.data || res
      
      const editList = (data.consumables || []).map(c => ({
        ...c,
        newQuantity: c.quantity
      }))

      this.setData({
        stockData: data,
        consumablesEditList: editList,
        loading: false
      })
    } catch (e) {
      console.error('获取设备库存失败:', e)
      this.setData({ loading: false })
    }
  },

  handleDeviceChange(e) {
    const idx = Number(e.detail.value)
    const curDev = this.data.devices[idx]
    this.setData({
      selectedDeviceIndex: idx,
      selectedDevice: curDev
    }, () => {
      this.fetchDeviceStock(curDev.device_sn)
    })
  },

  handleScanDevice() {
    wx.scanCode({
      success: res => {
        const scannedSn = res.result
        const found = this.data.devices.find(d => d.device_sn === scannedSn)
        if (found) {
          this.setData({ selectedDevice: found })
          this.fetchDeviceStock(found.device_sn)
          wx.showToast({ title: `已锁定设备 ${found.device_name}`, icon: 'success' })
        } else {
          wx.showToast({ title: `未匹配到设备 ${scannedSn}`, icon: 'none' })
        }
      }
    })
  },

  /**
   * 物料员修改耗材数量
   */
  handleQuantityInput(e) {
    const code = e.currentTarget.dataset.code
    const val = Number(e.detail.value) || 0
    const list = this.data.consumablesEditList.map(item => {
      if (item.code === code) {
        return { ...item, newQuantity: val }
      }
      return item
    })
    this.setData({ consumablesEditList: list })
  },

  /**
   * 提交更新耗材到云端
   */
  async handleSaveConsumables() {
    const { selectedDevice, consumablesEditList, isSubmitting } = this.data
    if (!selectedDevice || isSubmitting) return

    const updatePayload = consumablesEditList.map(item => ({
      code: item.code,
      quantity: item.newQuantity
    }))

    this.setData({ isSubmitting: true })

    try {
      await updateConsumables(selectedDevice.device_sn, updatePayload)
      wx.showToast({ title: '耗材已成功更新同步！', icon: 'success' })
      this.fetchDeviceStock(selectedDevice.device_sn)
    } catch (e) {
      wx.showToast({ title: e.message || '更新失败', icon: 'none' })
    } finally {
      this.setData({ isSubmitting: false })
    }
  },

  /**
   * 协调员下发指令
   */
  async handleDeviceAction(e) {
    const action = e.currentTarget.dataset.action
    const { selectedDevice } = this.data
    if (!selectedDevice) return

    const actionTexts = {
      reset: '确定向设备下发【重启复位】指令吗？',
      sync: '确定向设备下发【同步物料与配方】指令吗？',
      dispense: '确定向设备下发【强制开仓取餐】指令吗？'
    }

    wx.showModal({
      title: '指令确认',
      content: actionTexts[action] || '确定执行该操作吗？',
      success: async res => {
        if (res.confirm) {
          try {
            await sendDeviceAction(selectedDevice.device_sn, action)
            wx.showToast({ title: '指令已下发成功', icon: 'success' })
          } catch (err) {
            wx.showToast({ title: '下发指令失败', icon: 'none' })
          }
        }
      }
    })
  }
})
