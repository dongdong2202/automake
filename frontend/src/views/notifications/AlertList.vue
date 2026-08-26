<template>
  <div class="page-container alert-list-page">
    <PageHeader
      title="异常事件与设备告警"
      subtitle="全网机器硬件故障、传感器异常、料桶缺料与低液位告警统一监控与一键确认处理"
    />

    <div class="chart-card">
      <el-form :inline="true" :model="filters" size="default">
        <el-form-item label="告警等级">
          <el-select v-model="filters.level" placeholder="全部等级" clearable style="width: 120px;">
            <el-option label="普通提示" value="info" />
            <el-option label="警告" value="warning" />
            <el-option label="严重故障" value="critical" />
          </el-select>
        </el-form-item>
        <el-form-item label="事件类型">
          <el-select v-model="filters.event_type" placeholder="全部类型" clearable style="width: 160px;">
            <el-option label="物料保质期预警" value="material_expiring" />
            <el-option label="设备硬件告警" value="device_alert" />
            <el-option label="物料低液位/缺料" value="material_low" />
            <el-option label="系统事件" value="system" />
          </el-select>
        </el-form-item>
        <el-form-item label="处理状态">
          <el-select v-model="filters.is_handled" placeholder="全部状态" clearable style="width: 110px;">
            <el-option label="未处理" value="false" />
            <el-option label="已处理" value="true" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" icon="Search" @click="fetchAlerts">查询</el-button>
        </el-form-item>
      </el-form>

      <el-table v-loading="loading" :data="alertList" stripe style="width: 100%">
        <el-table-column prop="level" label="等级" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="row.level === 'critical' ? 'danger' : row.level === 'warning' ? 'warning' : 'info'" size="small">
              {{ row.level_display }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="event_type" label="事件类型" width="140">
          <template #default="{ row }">
            <el-tag :type="row.event_type === 'material_expiring' ? 'warning' : 'info'" size="small" effect="plain">
              {{ row.event_type_display || row.event_type }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="告警标题" min-width="180" />
        <el-table-column prop="content" label="告警详情" min-width="260" show-overflow-tooltip />
        <el-table-column prop="device_sn" label="关联设备" width="150">
          <template #default="{ row }">
            <span v-if="row.device_sn" style="font-family: monospace;">{{ row.device_sn }}</span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="is_handled" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_handled ? 'success' : 'danger'" size="small">
              {{ row.is_handled ? '已处理' : '待处理' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="发生时间" width="170" />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="!row.is_handled"
              type="primary"
              link
              size="small"
              @click="handleResolveAlert(row.id)"
            >
              标记已处理
            </el-button>
            <span v-else style="color: #909399; font-size: 13px;">{{ row.handled_by_username || '已解决' }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import { getNotifyEventsApi, handleNotifyEventApi } from '@/api/notifications'
import { useAppStore } from '@/stores/app'

const appStore = useAppStore()
const loading = ref(false)
const alertList = ref<any[]>([])

const filters = reactive({
  level: '',
  event_type: '',
  is_handled: 'false',
})

async function fetchAlerts() {
  loading.value = true
  try {
    const res = await getNotifyEventsApi(filters)
    if (res.data) {
      alertList.value = res.data.results || []
    }
  } finally {
    loading.value = false
  }
}

async function handleResolveAlert(id: number) {
  try {
    await handleNotifyEventApi(id)
    ElMessage.success('已标记该事件为已处理')
    fetchAlerts()
    // 重新计算未处理告警数
    const unhandledRes = await getNotifyEventsApi({ is_handled: 'false' })
    if (unhandledRes.data) {
      appStore.setUnhandledAlarms(unhandledRes.data.count || 0)
    }
  } catch (e) {
    //
  }
}

onMounted(() => {
  fetchAlerts()
})
</script>
