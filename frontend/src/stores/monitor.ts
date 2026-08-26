import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getMonitorDevicesApi } from '@/api/monitor'

export const useMonitorStore = defineStore('monitor', () => {
  const devicesMap = ref<Record<string, any>>({})
  const loading = ref(false)

  async function fetchDevices() {
    loading.value = true
    try {
      const res = await getMonitorDevicesApi()
      if (res.data) {
        const map: Record<string, any> = {}
        for (const item of res.data) {
          map[item.device_sn] = item
        }
        devicesMap.value = map
      }
    } finally {
      loading.value = false
    }
  }

  function updateDeviceStatus(payload: any) {
    if (payload && payload.device_sn) {
      const existing = devicesMap.value[payload.device_sn] || {}
      devicesMap.value[payload.device_sn] = {
        ...existing,
        ...payload,
        reported_at: payload.reported_at || new Date().toISOString(),
      }
    }
  }

  return {
    devicesMap,
    loading,
    fetchDevices,
    updateDeviceStatus,
  }
})
