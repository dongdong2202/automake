import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAppStore = defineStore('app', () => {
  const isCollapse = ref(false)
  const unhandledAlarmsCount = ref(0)

  function toggleSidebar() {
    isCollapse.value = !isCollapse.value
  }

  function setUnhandledAlarms(count: number) {
    unhandledAlarmsCount.value = count
  }

  return {
    isCollapse,
    unhandledAlarmsCount,
    toggleSidebar,
    setUnhandledAlarms,
  }
})
