<template>
  <div class="page-container monitor-dashboard-page">
    <PageHeader
      title="设备实时监控大屏"
      subtitle="直连 Redis 高速快照与 WebSocket 双向长连接，毫秒级响应硬件状态、料桶余量与故障报警"
    >
      <template #actions>
        <el-tag :type="wsConnected ? 'success' : 'danger'" effect="dark">
          {{ wsConnected ? '● WebSocket 实时长连接中' : '○ 正在重连监控服务...' }}
        </el-tag>
        <el-button type="primary" plain icon="Refresh" @click="monitorStore.fetchDevices">
          刷新数据
        </el-button>
      </template>
    </PageHeader>

    <!-- 设备状态卡片网格 -->
    <div class="chart-card">
      <div class="card-header">
        <span class="card-title">
          <el-icon><Platform /></el-icon>
          全网设备运行状态矩阵 (共 {{ devicesList.length }} 台)
        </span>
      </div>

      <el-row :gutter="16">
        <el-col
          v-for="dev in devicesList"
          :key="dev.device_sn"
          :xs="24"
          :sm="12"
          :md="8"
          :lg="6"
          class="device-col"
        >
          <div
            class="device-card"
            :class="dev.display_status || (dev.healthy ? 'normal' : 'fault')"
            @click="$router.push(`/monitor/${dev.device_sn}`)"
          >
            <div class="card-top">
              <span class="device-sn">{{ dev.device_name || dev.device_sn }}</span>
              <StatusBadge
                :status="dev.display_status || (dev.healthy ? 'normal' : 'fault')"
                :text="dev.display_status === 'normal' ? '正常' : dev.display_status === 'warning' ? '预警' : '故障/离线'"
              />
            </div>

            <div class="card-body">
              <div class="info-item">
                <span class="label">所属门店:</span>
                <span class="val">{{ dev.store_name || '-' }}</span>
              </div>
              <div class="info-item">
                <span class="label">序列号:</span>
                <span class="val code">{{ dev.device_sn }}</span>
              </div>
              <div class="info-item">
                <span class="label">最后上报:</span>
                <span class="val">{{ dev.reported_at ? formatTime(dev.reported_at) : '暂无' }}</span>
              </div>

              <!-- 重点指标与异常问题编号小标签 -->
              <div class="metric-tags">
                <el-tag
                  v-for="prob in getDeviceProblemTags(dev)"
                  :key="prob"
                  size="small"
                  type="danger"
                  effect="dark"
                >
                  {{ prob }}
                </el-tag>
                <el-tag size="small" type="info" v-if="dev.temperature?.t1 !== undefined">
                  冷柜: {{ dev.temperature.t1 }}°C
                </el-tag>
                <el-tag size="small" type="info" v-if="dev.temperature?.t2 !== undefined">
                  加热: {{ dev.temperature.t2 }}°C
                </el-tag>
                <el-tag size="small" :type="dev.cups?.paperL?.damaged || dev.cups?.paperL?.empty ? 'danger' : 'success'" v-if="dev.cups?.paperL !== undefined">
                  大杯: {{ typeof dev.cups.paperL === 'object' ? (dev.cups.paperL.empty ? '缺杯' : (dev.cups.paperL.damaged ? '损坏' : '正常')) : dev.cups.paperL }}
                </el-tag>
              </div>
            </div>

            <div class="card-footer">
              <el-button type="primary" link size="small">查看设备详情 →</el-button>
            </div>
          </div>
        </el-col>
      </el-row>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { Platform, Refresh } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useMonitorStore } from '@/stores/monitor'
import { useWebSocket } from '@/composables/useWebSocket'

const monitorStore = useMonitorStore()

const { isConnected: wsConnected } = useWebSocket('/ws/monitor/', (payload) => {
  monitorStore.updateDeviceStatus(payload)
})

const devicesList = computed(() => {
  return Object.values(monitorStore.devicesMap)
})

function getDeviceProblemTags(dev: any): string[] {
  const tags: string[] = []
  if (!dev) return tags

  // 1. 检查料桶损坏或缺料
  const barrels = dev.barrels || {}
  Object.values(barrels).forEach((b: any) => {
    if (b?.damaged) {
      tags.push(`异常桶: ${b.barrel_code}${b.material_name && b.material_name !== b.barrel_code ? '(' + b.material_name + ')' : ''}`)
    }
  })

  // 2. 检查其他机构异常
  const abnormalities = dev.abnormalities || {}
  Object.entries(abnormalities).forEach(([k, desc]: [string, any]) => {
    if (!k.startsWith('thinP.') && !k.startsWith('thickP.') && !k.startsWith('solidP.') && k !== 'healthy') {
      if (k === 'disconnected') {
        tags.push('离线')
      } else {
        tags.push(`${k}`)
      }
    }
  })

  return tags.slice(0, 3) // 避免卡片标签过多
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString()
  } catch {
    return iso
  }
}

onMounted(() => {
  monitorStore.fetchDevices()
})
</script>

<style scoped lang="scss">
.device-col {
  margin-bottom: 16px;
}

.device-card {
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid #e8e8e8;
  padding: 16px;
  cursor: pointer;
  transition: all 0.3s ease;

  &:hover {
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
    transform: translateY(-2px);
  }

  &.normal {
    border-top: 3px solid #67C23A;
  }
  &.warning {
    border-top: 3px solid #E6A23C;
    background: #fffdf5;
  }
  &.fault {
    border-top: 3px solid #F56C6C;
    background: #fff5f5;
    animation: border-blink 1.5s infinite;
  }

  .card-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;

    .device-sn {
      font-size: 15px;
      font-weight: 600;
      color: #303133;
    }
  }

  .card-body {
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: 13px;

    .info-item {
      display: flex;
      justify-content: space-between;

      .label {
        color: #909399;
      }
      .val {
        color: #606266;
        &.code {
          font-family: monospace;
        }
      }
    }

    .metric-tags {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 8px;
    }
  }

  .card-footer {
    margin-top: 12px;
    padding-top: 10px;
    border-top: 1px dashed #ebeef5;
    text-align: right;
  }
}

@keyframes border-blink {
  0% { box-shadow: 0 0 0 rgba(245, 108, 108, 0); }
  50% { box-shadow: 0 0 8px rgba(245, 108, 108, 0.5); }
  100% { box-shadow: 0 0 0 rgba(245, 108, 108, 0); }
}
</style>
