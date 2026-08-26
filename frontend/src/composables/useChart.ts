import * as echarts from 'echarts'
import { ref, onMounted, onUnmounted, type Ref } from 'vue'

export const THEME_COLORS = [
  '#409EFF',  // 主蓝
  '#67C23A',  // 成功绿
  '#E6A23C',  // 警告橙
  '#F56C6C',  // 危险红
  '#00C9A7',  // 青绿
  '#845EC2',  // 优雅紫
  '#FF6F91',  // 珊瑚粉
  '#FFC75F',  // 金黄
  '#0081CF',  // 湛蓝
  '#909399',  // 中灰
]

export function useChart(chartRef: Ref<HTMLElement | null>) {
  let instance: echarts.EChartsType | null = null
  let resizeObserver: ResizeObserver | null = null
  const isReady = ref(false)

  onMounted(() => {
    if (chartRef.value) {
      instance = echarts.init(chartRef.value)
      isReady.value = true

      resizeObserver = new ResizeObserver(() => {
        instance?.resize()
      })
      resizeObserver.observe(chartRef.value)
    }
  })

  onUnmounted(() => {
    resizeObserver?.disconnect()
    instance?.dispose()
    instance = null
  })

  function setOption(option: any, notMerge = false) {
    if (!instance && chartRef.value) {
      instance = echarts.init(chartRef.value)
    }
    instance?.setOption(
      {
        color: THEME_COLORS,
        ...option,
      },
      { notMerge }
    )
  }

  function resize() {
    instance?.resize()
  }

  function getInstance() {
    return instance
  }

  return {
    setOption,
    resize,
    getInstance,
    isReady,
  }
}
