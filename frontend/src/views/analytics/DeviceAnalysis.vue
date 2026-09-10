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
          <BaseChart :option="healthScoreChartOption" height="350px" />
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
          <BaseChart :option="alarmTrendChartOption" height="350px" />
        </div>
      </el-col>
    </el-row>

    <!-- 设备详细状态表格 -->
    <div class="chart-card" style="margin-top: 16px;">
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
        <el-table-column prop="health_score" label="健康评分" width="160" sortable>
          <template #default="{ row }">
            <el-progress
              :percentage="row.health_score"
              :status="row.health_score >= 80 ? 'success' : row.health_score >= 50 ? 'warning' : 'exception'"
              :stroke-width="10"
              striped
              striped-flow
            />
          </template>
        </el-table-column>
        <el-table-column prop="unresolved_alarms" label="待处理告警" width="120" sortable>
          <template #default="{ row }">
            <el-tag :type="row.unresolved_alarms > 0 ? 'danger' : 'info'" size="small" effect="plain">
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
import {
  createLinearGradient,
  CHART_COLORS,
  MODERN_TOOLTIP,
  MODERN_GRID,
} from '@/utils/chartThemes'

const { dateRange, shortcuts } = useDateRange()
const uptimeList = ref<any[]>([])
const alarmTrendList = ref<any[]>([])

/**
 * 1. 健康评分排行水平胶囊柱图 Option
 * - 动态阶梯色彩映射：绿色 (健康良好) / 橙黄 (需关注) / 红色 (异常急需检修)
 */
const healthScoreChartOption = computed(() => {
  const names = uptimeList.value.map((i) => i.device_name || i.device_sn).reverse()
  const scores = uptimeList.value.map((i) => i.health_score).reverse()

  return {
    tooltip: {
      ...MODERN_TOOLTIP,
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
    },
    grid: {
      ...MODERN_GRID,
      left: '4%',
      right: '8%',
      top: '4%',
      bottom: '6%',
    },
    xAxis: {
      type: 'value',
      max: 100,
      name: '健康分',
      axisLabel: { color: '#909399' },
      splitLine: { lineStyle: { color: '#F2F6FC', type: 'dashed' } },
    },
    yAxis: {
      type: 'category',
      data: names,
      axisLine: { lineStyle: { color: '#E4E7ED' } },
      axisLabel: { color: '#606266', fontSize: 12 },
    },
    series: [
      {
        name: '健康评分',
        type: 'bar',
        barMaxWidth: 18,
        data: scores,
        itemStyle: {
          color: (params: any) => {
            const val = params.value
            if (val >= 80) {
              return createLinearGradient('#67C23A', '#95D475', false)
            } else if (val >= 60) {
              return createLinearGradient('#E6A23C', '#F3D19E', false)
            }
            return createLinearGradient('#F56C6C', '#F89898', false)
          },
          borderRadius: [0, 6, 6, 0],
        },
        label: {
          show: true,
          position: 'right',
          formatter: '{c} 分',
          color: '#909399',
          fontSize: 11,
        },
      },
    ],
  }
})

/**
 * 2. 告警趋势堆叠面积图 Option
 * - 区分普通提示 (Info)、一般警告 (Warning)、严重故障 (Critical)
 * - 采用半透明渐变区域填充，方便掌握故障暴发与恢复波谷
 */
const alarmTrendChartOption = computed(() => {
  const dates = alarmTrendList.value.map((i) => i.date)
  const infos = alarmTrendList.value.map((i) => i.info)
  const warnings = alarmTrendList.value.map((i) => i.warning)
  const criticals = alarmTrendList.value.map((i) => i.critical)

  return {
    tooltip: {
      ...MODERN_TOOLTIP,
      trigger: 'axis',
    },
    legend: {
      data: ['普通提示', '一般警告', '严重故障'],
      bottom: 0,
      icon: 'circle',
    },
    grid: MODERN_GRID,
    xAxis: {
      type: 'category',
      data: dates,
      axisLine: { lineStyle: { color: '#E4E7ED' } },
      axisLabel: { color: '#606266', fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      name: '告警频次',
      axisLabel: { color: '#909399' },
      splitLine: { lineStyle: { color: '#F2F6FC', type: 'dashed' } },
    },
    series: [
      {
        name: '普通提示',
        type: 'line',
        smooth: 0.35,
        symbol: 'none',
        areaStyle: {
          color: createLinearGradient('rgba(144, 147, 153, 0.25)', 'rgba(144, 147, 153, 0.02)'),
        },
        data: infos,
        itemStyle: { color: '#909399' },
      },
      {
        name: '一般警告',
        type: 'line',
        smooth: 0.35,
        symbol: 'none',
        areaStyle: {
          color: createLinearGradient('rgba(230, 162, 60, 0.35)', 'rgba(230, 162, 60, 0.02)'),
        },
        data: warnings,
        itemStyle: { color: '#E6A23C' },
      },
      {
        name: '严重故障',
        type: 'line',
        smooth: 0.35,
        symbol: 'circle',
        symbolSize: 6,
        areaStyle: {
          color: createLinearGradient('rgba(245, 108, 108, 0.4)', 'rgba(245, 108, 108, 0.03)'),
        },
        data: criticals,
        itemStyle: { color: '#F56C6C' },
        lineStyle: { width: 2.5 },
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

<style scoped>
.chart-card {
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
  border-radius: 8px;
}
</style>
