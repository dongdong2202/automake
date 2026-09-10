<template>
  <div class="page-container material-analysis-page">
    <PageHeader
      title="物料进销存与消耗预测"
      subtitle="监控仓库与门店物料实时库存、统计消耗趋势，基于算法智能预测补货周期与剩余可用天数"
    >
      <template #actions>
        <el-button type="primary" icon="Plus" @click="$router.push('/inventory')">
          物料出入库记账
        </el-button>
      </template>
    </PageHeader>

    <!-- 图表行：库存状态进度 + 出库消耗趋势 -->
    <el-row :gutter="16">
      <el-col :xs="24" :lg="12">
        <div class="chart-card">
          <div class="card-header">
            <span class="card-title">
              <el-icon><Box /></el-icon>
              物料库存余量总览 (%)
            </span>
          </div>
          <BaseChart :option="stockProgressChartOption" height="350px" />
        </div>
      </el-col>

      <el-col :xs="24" :lg="12">
        <div class="chart-card">
          <div class="card-header">
            <span class="card-title">
              <el-icon><TrendCharts /></el-icon>
              物料出库分拨消耗趋势
            </span>
          </div>
          <BaseChart :option="consumptionChartOption" height="350px" />
        </div>
      </el-col>
    </el-row>

    <!-- 补货建议与预测表格 -->
    <div class="chart-card" style="margin-top: 16px;">
      <div class="card-header">
        <span class="card-title">
          <el-icon><Warning /></el-icon>
          物料消耗预测与智能补货建议
        </span>
        <el-tag type="info" size="small" effect="plain">基于近 7 天平均出库速率推算</el-tag>
      </div>

      <el-table :data="forecastList" stripe style="width: 100%">
        <el-table-column prop="code" label="物料编码" width="120" />
        <el-table-column prop="name" label="物料名称" min-width="160" />
        <el-table-column prop="current_stock" label="当前总库存" width="140">
          <template #default="{ row }">
            <strong>{{ row.current_stock }}</strong> {{ row.unit }}
          </template>
        </el-table-column>
        <el-table-column prop="avg_daily_consumption" label="日均消耗速率" width="150">
          <template #default="{ row }">
            {{ row.avg_daily_consumption }} {{ row.unit }}/天
          </template>
        </el-table-column>
        <el-table-column prop="days_remaining" label="预计剩余可用" width="150" sortable>
          <template #default="{ row }">
            <span v-if="row.days_remaining > 365" class="text-success">充足 (>1年)</span>
            <span v-else :class="row.days_remaining <= 3 ? 'text-danger fw-bold' : row.days_remaining <= 7 ? 'text-warning' : ''">
              {{ row.days_remaining }} 天
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="urgency" label="补货建议" width="140">
          <template #default="{ row }">
            <el-tag v-if="row.urgency === 'critical'" type="danger" effect="dark" size="small">
              ⚠️ 紧急需补货
            </el-tag>
            <el-tag v-else-if="row.urgency === 'warning'" type="warning" size="small" effect="plain">
              需近期补货
            </el-tag>
            <el-tag v-else type="success" size="small" effect="plain">
              库存充足
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="$router.push('/inventory')">
              快速入库
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Box, TrendCharts, Warning } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import BaseChart from '@/components/charts/BaseChart.vue'
import {
  getMaterialStockStatusApi,
  getMaterialConsumptionTrendApi,
  getMaterialForecastApi,
} from '@/api/analytics'
import {
  createLinearGradient,
  CHART_COLORS,
  MODERN_TOOLTIP,
  MODERN_GRID,
} from '@/utils/chartThemes'

const stockList = ref<any[]>([])
const consumptionList = ref<any[]>([])
const forecastList = ref<any[]>([])

/**
 * 1. 库存余量百分比进度水平胶囊柱图 Option
 * - 动态三段色板预警：>=60% 绿色 (安全)；30%-60% 橙黄 (待补)；<30% 红色 (缺料警告)
 */
const stockProgressChartOption = computed(() => {
  const names = stockList.value.map((i) => i.name).reverse()
  const percents = stockList.value.map((i) => i.percentage).reverse()

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
      name: '余量 (%)',
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
        name: '余量百分比',
        type: 'bar',
        barMaxWidth: 18,
        data: percents,
        itemStyle: {
          color: (params: any) => {
            const val = params.value
            if (val >= 60) {
              return createLinearGradient('#67C23A', '#95D475', false)
            } else if (val >= 30) {
              return createLinearGradient('#E6A23C', '#F3D19E', false)
            }
            return createLinearGradient('#F56C6C', '#F89898', false)
          },
          borderRadius: [0, 6, 6, 0],
        },
        label: {
          show: true,
          position: 'right',
          formatter: '{c}%',
          color: '#909399',
          fontSize: 11,
        },
      },
    ],
  }
})

/**
 * 2. 物料出库分拨消耗趋势多折线 Option
 * - 结合现代色彩网格与平滑贝塞尔曲线，观察各物料随时间出库消耗动向
 */
const consumptionChartOption = computed(() => {
  const dates = Array.from(new Set(consumptionList.value.map((i) => i.date))).sort()
  const materials = Array.from(new Set(consumptionList.value.map((i) => i.material_name)))

  const series = materials.map((mat, idx) => {
    const data = dates.map((d) => {
      const match = consumptionList.value.find((c) => c.date === d && c.material_name === mat)
      return match ? match.quantity : 0
    })
    return {
      name: mat,
      type: 'line',
      smooth: 0.35,
      symbol: 'circle',
      symbolSize: 5,
      data: data,
    }
  })

  return {
    tooltip: {
      ...MODERN_TOOLTIP,
      trigger: 'axis',
    },
    color: CHART_COLORS.palette,
    legend: {
      bottom: 0,
      icon: 'roundRect',
      textStyle: { fontSize: 11, color: '#606266' },
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
      name: '出库用量',
      axisLabel: { color: '#909399' },
      splitLine: { lineStyle: { color: '#F2F6FC', type: 'dashed' } },
    },
    series: series,
  }
})

async function fetchData() {
  try {
    const [stockRes, consumptionRes, forecastRes] = await Promise.all([
      getMaterialStockStatusApi(),
      getMaterialConsumptionTrendApi(),
      getMaterialForecastApi(),
    ])

    stockList.value = stockRes.data || []
    consumptionList.value = consumptionRes.data || []
    forecastList.value = forecastRes.data || []
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

.text-success {
  color: #67c23a;
}

.text-warning {
  color: #e6a23c;
}

.text-danger {
  color: #f56c6c;
}

.fw-bold {
  font-weight: 600;
}
</style>
