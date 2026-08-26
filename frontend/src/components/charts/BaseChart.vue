<template>
  <div ref="chartRef" :style="{ width: width, height: height }"></div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, type PropType } from 'vue'
import { useChart } from '@/composables/useChart'

const props = defineProps({
  option: {
    type: Object as PropType<any>,
    required: true,
  },
  width: {
    type: String,
    default: '100%',
  },
  height: {
    type: String,
    default: '320px',
  },
  notMerge: {
    type: Boolean,
    default: false,
  },
})

const chartRef = ref<HTMLElement | null>(null)
const { setOption, resize, isReady } = useChart(chartRef)

watch(
  () => props.option,
  (newOpt) => {
    if (newOpt) {
      setOption(newOpt, props.notMerge)
    }
  },
  { deep: true }
)

onMounted(() => {
  if (props.option) {
    setOption(props.option, props.notMerge)
  }
})

defineExpose({
  resize,
  setOption,
})
</script>
