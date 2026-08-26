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
          <BaseChart :option="stockProgressChartOption" height="340px" />
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
          <BaseChart :option="consumptionChartOption" height="340px" />
        </div>
      </el-col>
    </el-row>

    <!-- 补货建议与预测表格 -->
    <div class="chart-card">
      <div class="card-header">
        <span class="card-title">
          <el-icon><Warning /></el-icon>
          物料消耗预测与智能补货建议
        </span>
        <el-tag type="info" size="small">基于近 7 天平均出库速率推算</el-tag>
      </div>

      <el-table :data="forecastList" stripe style="width: 100%">
        <el-table-column prop="code" label="物料编码" width="120" />
        <el-table-column prop="name" label="物料名称" min-width="160" />
        <el-table-column prop="current_stock" label="当前总库存" width="140">
          <template #default="{ row }">
            {{ row.current_stock }} {{ row.unit }}
          </template>
        </el-table-column>
        <el-table-column prop="avg_daily_consumption" label="日均消耗速率" width="150">
          <template #default="{ row }">
            {{ row.avg_daily_consumption }} {{ row.unit }}/天
          </template>
        </el-table-column>
        <el-table-column prop="days_remaining" label="预计剩余可用" width="150" sortable>
          <template #default="{ row }">
            <span v-if="row.days_remaining > 365">充足 (>1年)</span>
            <span v-else>{{ row.days_remaining }} 天</span>
          </template>
        </el-table-column>
        <el-table-column prop="urgency" label="补货建议" width="140">
          <template #default="{ row }">
            <el-tag v-if="row.urgency === 'critical'" type="danger" effect="dark" size="small">
              ⚠️ 紧急需补货
            </el-tag>
            <el-tag v-else-if="row.urgency === 'warning'" type="warning" size="small">
              需近期补货
            </el-tag>
            <el-tag v-else type="success" size="small">
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

const stockList = ref<any[]>([])
const consumptionList = ref<any[]>([])
const forecastList = ref<any[]>([])

// 1. 库存百分比进度 Option
const stockProgressChartOption = computed(() => {
  const names = stockList.value.map((i) => i.name).reverse()
  const percents = stockList.value.map((i) => i.percentage).reverse()

  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '8%', bottom: '5%', top: '5%', containLabel: true },
    xAxis: { type: 'value', max: 100, name: '余量(%)' },
    yAxis: { type: 'category', data: names },
    series: [
      {
        name: '余量百分比',
        type: 'bar',
        data: percents,
        itemStyle: {
          color: (params: any) => {
            const val = params.value
            return val >= 60 ? '#67C23A' : val >= 30 ? '#E6A23C' : '#F56C6C'
          },
          borderRadius: [0, 4, 4, 0],
        },
      },
    ],
  }
})

// 2. 物料消耗趋势 Option
const consumptionChartOption = computed(() => {
  const dates = Array.from(new Set(consumptionList.value.map((i) => i.date))).sort()
  const materials = Array.from(new Set(consumptionList.value.map((i) => i.material_name)))

  const series = materials.map((mat) => {
    const data = dates.map((d) => {
      const match = consumptionList.value.find((c) => c.date === d && c.material_name === mat)
      return match ? match.quantity : 0
    })
    return {
      name: mat,
      type: 'line',
      smooth: true,
      data: data,
    }
  })

  return {
    tooltip: { trigger: 'axis' },
    legend: { bottom: 0 },
    grid: { left: '3%', right: '4%', bottom: '10%', top: '8%', containLabel: true },
    xAxis: { type: 'category', data: dates },
    yAxis: { type: 'value', name: '出库量' },
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
