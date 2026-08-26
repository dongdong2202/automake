<template>
  <el-tag :type="tagType" :effect="effect" size="small" class="status-badge">
    <span class="status-dot" :class="status"></span>
    {{ text || defaultText }}
  </el-tag>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps({
  status: {
    type: String, // 'online' | 'offline' | 'fault' | 'normal' | 'warning' | 'open' | 'closed'
    required: true,
  },
  text: {
    type: String,
    default: '',
  },
  effect: {
    type: String as () => 'light' | 'dark' | 'plain',
    default: 'light',
  },
})

const tagType = computed(() => {
  switch (props.status) {
    case 'online':
    case 'normal':
    case 'open':
    case 'success':
      return 'success'
    case 'warning':
    case 'paused':
      return 'warning'
    case 'offline':
    case 'closed':
      return 'info'
    case 'fault':
    case 'critical':
    case 'failed':
      return 'danger'
    default:
      return 'info'
  }
})

const defaultText = computed(() => {
  switch (props.status) {
    case 'online':
      return '在线'
    case 'offline':
      return '离线'
    case 'fault':
      return '故障'
    case 'normal':
      return '正常'
    case 'warning':
      return '预警'
    case 'open':
      return '营业中'
    case 'closed':
      return '已打烊'
    default:
      return props.status
  }
})
</script>

<style scoped>
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: currentColor;
}
.status-dot.online,
.status-dot.normal,
.status-dot.open {
  background-color: #67C23A;
}
.status-dot.warning,
.status-dot.paused {
  background-color: #E6A23C;
}
.status-dot.fault,
.status-dot.critical {
  background-color: #F56C6C;
  animation: pulse 1.5s infinite;
}
.status-dot.offline,
.status-dot.closed {
  background-color: #909399;
}

@keyframes pulse {
  0% { opacity: 1; }
  50% { opacity: 0.3; }
  100% { opacity: 1; }
}
</style>
