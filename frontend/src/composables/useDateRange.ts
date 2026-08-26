import { ref } from 'vue'

export function useDateRange() {
  const dateRange = ref<[string, string]>(getDefaultLast30Days())

  function formatDate(d: Date): string {
    const year = d.getFullYear()
    const month = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
  }

  function getDefaultLast30Days(): [string, string] {
    const end = new Date()
    const start = new Date()
    start.setDate(end.getDate() - 29)
    return [formatDate(start), formatDate(end)]
  }

  function setToday() {
    const today = formatDate(new Date())
    dateRange.value = [today, today]
  }

  function setLast7Days() {
    const end = new Date()
    const start = new Date()
    start.setDate(end.getDate() - 6)
    dateRange.value = [formatDate(start), formatDate(end)]
  }

  function setLast30Days() {
    dateRange.value = getDefaultLast30Days()
  }

  function setThisMonth() {
    const end = new Date()
    const start = new Date(end.getFullYear(), end.getMonth(), 1)
    dateRange.value = [formatDate(start), formatDate(end)]
  }

  const shortcuts = [
    {
      text: '今日',
      value: () => {
        const d = new Date()
        return [d, d]
      },
    },
    {
      text: '近7天',
      value: () => {
        const end = new Date()
        const start = new Date()
        start.setDate(start.getDate() - 6)
        return [start, end]
      },
    },
    {
      text: '近30天',
      value: () => {
        const end = new Date()
        const start = new Date()
        start.setDate(start.getDate() - 29)
        return [start, end]
      },
    },
    {
      text: '本月',
      value: () => {
        const end = new Date()
        const start = new Date(end.getFullYear(), end.getMonth(), 1)
        return [start, end]
      },
    },
  ]

  return {
    dateRange,
    shortcuts,
    setToday,
    setLast7Days,
    setLast30Days,
    setThisMonth,
  }
}
