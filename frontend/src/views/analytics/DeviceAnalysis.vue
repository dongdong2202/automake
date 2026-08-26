<template>
  <div class="page-container device-analysis-page">
    <PageHeader
      title="设备运维与健康分析"
      subtitle="全网设备运行健康度评估、在线率排行、告警发生趋势以及高频故障定位"
    >
      <template #actions>
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          value-format="YYYY-MM-DD"
          :shortcuts="shortcuts"
          @change="fetchData"
        />
      </template>
    </PageHeader>

    <!-- 图表行：健康评分排行 + 告警趋势面积图 -->
    <el-row :gutter="16">
      <el-col :xs="24" :lg="12">
        <div class="chart-card">
          <div class="card-header">
            <span class="card-title">
              <el-icon><Monitor /></el-icon>
              设备健康评分排行 (满分 100)
            </span>
          </div>
          <BaseChart :option="healthScoreChartOption" height="340px" />
        </div>
      </el-col>

      <el-col :xs="24" :lg="12">
        <div class="chart-card">
          <div class="card-header">
            <span class="card-title">
              <el-icon><Bell /></el-icon>
              系统告警发生趋势 (按严重等级)
            </span>
          </div>
          <BaseChart :option="alarmTrendChartOption" height="340px" />
        </div>
      </el-col>
    </el-row>

    <!-- 设备详细状态表格 -->
    <div class="chart-card">
      <div class="card-header">
        <span class="card-title">
          <el-icon><Cpu /></el-icon>
          设备健康运维档案
        </span>
      </div>

      <el-table :data="uptimeList" stripe style="width: 100%">
        <el-table-column prop="device_sn" label="设备序列号 (SN)" min-width="160" />
        <el-table-column prop="device_name" label="设备名称" min-width="160" />
        <el-table-column prop="store_name" label="所属门店" width="140" />
        <el-table-column prop="status_display" label="当前状态" width="110">
          <template #default="{ row }">
            <StatusBadge :status="row.status" :text="row.status_display" />
          </template>
        </el-table-column>
        <el-table-column prop="health_score" label="健康评分" width="130" sortable>
          <template #default="{ row }">
            <el-progress
              :percentage="row.health_score"
              :status="row.health_score >= 80 ? 'success' : row.health_score >= 50 ? 'warning' : 'exception'"
            />
          </template>
        </el-table-column>
        <el-table-column prop="unresolved_alarms" label="待处理告警" width="120" sortable>
          <template #default="{ row }">
            <el-tag :type="row.unresolved_alarms > 0 ? 'danger' : 'info'" size="small">
              {{ row.unresolved_alarms }} 条
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="last_heartbeat" label="最后心跳时间" width="180" />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="$router.push(`/monitor/${row.device_sn}`)">
              监控详情
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Monitor, Bell, Cpu } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import BaseChart from '@/components/charts/BaseChart.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useDateRange } from '@/composables/useDateRange'
import { getDeviceUptimeApi, getDeviceAlarmTrendApi } from '@/api/analytics'

const { dateRange, shortcuts } = useDateRange()
const uptimeList = ref<any[]>([])
const alarmTrendList = ref<any[]>([])

// 1. 健康评分排行 Option
const healthScoreChartOption = computed(() => {
  const names = uptimeList.value.map((i) => i.device_name || i.device_sn).reverse()
  const scores = uptimeList.value.map((i) => i.health_score).reverse()

  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '8%', bottom: '5%', top: '5%', containLabel: true },
    xAxis: { type: 'value', max: 100, name: '评分' },
    yAxis: { type: 'category', data: names },
    series: [
      {
        name: '健康评分',
        type: 'bar',
        data: scores,
        itemStyle: { color: '#67C23A', borderRadius: [0, 4, 4, 0] },
      },
    ],
  }
})

// 2. 告警趋势堆叠面积图 Option
const alarmTrendChartOption = computed(() => {
  const dates = alarmTrendList.value.map((i) => i.date)
  const infos = alarmTrendList.value.map((i) => i.info)
  const warnings = alarmTrendList.value.map((i) => i.warning)
  const criticals = alarmTrendList.value.map((i) => i.critical)

  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['普通提示', '一般警告', '严重故障'], bottom: 0 },
    grid: { left: '3%', right: '4%', bottom: '10%', top: '8%', containLabel: true },
    xAxis: { type: 'category', data: dates },
    yAxis: { type: 'value', name: '告警次数' },
    series: [
      {
        name: '普通提示',
        type: 'line',
        stack: 'total',
        areaStyle: {},
        data: infos,
        itemStyle: { color: '#909399' },
      },
      {
        name: '一般警告',
        type: 'line',
        stack: 'total',
        areaStyle: {},
        data: warnings,
        itemStyle: { color: '#E6A23C' },
      },
      {
        name: '严重故障',
        type: 'line',
        stack: 'total',
        areaStyle: {},
        data: criticals,
        itemStyle: { color: '#F56C6C' },
      },
    ],
  }
})

async function fetchData() {
  const [start_date, end_date] = dateRange.value || []
  const params = { start_date, end_date }

  try {
    const [uptimeRes, alarmRes] = await Promise.all([
      getDeviceUptimeApi(params),
      getDeviceAlarmTrendApi(params),
    ])

    uptimeList.value = uptimeRes.data || []
    alarmTrendList.value = alarmRes.data || []
  } catch (e) {
    // 错误处理由 Axios 拦截器负责
  }
}

onMounted(() => {
  fetchData()
})
</script>
