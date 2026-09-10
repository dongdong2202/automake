<template>
  <div class="page-container customer-analysis-page">
    <PageHeader
      title="客户画像与复购分析"
      subtitle="监控微信小程序新用户注册增长趋势、分析顾客购买频次与忠诚度分布"
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

    <!-- 图表行：用户增长趋势 + 消费频次分布 -->
    <el-row :gutter="16">
      <el-col :xs="24" :lg="14">
        <div class="chart-card">
          <div class="card-header">
            <span class="card-title">
              <el-icon><User /></el-icon>
              小程序注册用户增长趋势 (累计 {{ growthData.total_users }} 人)
            </span>
          </div>
          <BaseChart :option="growthChartOption" height="360px" />
        </div>
      </el-col>

      <el-col :xs="24" :lg="10">
        <div class="chart-card">
          <div class="card-header">
            <span class="card-title">
              <el-icon><PieChart /></el-icon>
              顾客复购与下单频次分布
            </span>
          </div>
          <BaseChart :option="frequencyChartOption" height="360px" />
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { User, PieChart } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import BaseChart from '@/components/charts/BaseChart.vue'
import { useDateRange } from '@/composables/useDateRange'
import { getCustomerGrowthApi, getCustomerFrequencyApi } from '@/api/analytics'
import {
  createLinearGradient,
  CHART_COLORS,
  MODERN_TOOLTIP,
  MODERN_GRID,
} from '@/utils/chartThemes'

const { dateRange, shortcuts } = useDateRange()
const growthData = ref<{ total_users: number; growth_trend: any[] }>({
  total_users: 0,
  growth_trend: [],
})
const frequencyList = ref<any[]>([])

/**
 * 1. 用户新增注册平滑渐变面积折线 Option
 * - 结合双色渐变色板，展示小程序用户增量速度
 */
const growthChartOption = computed(() => {
  const dates = growthData.value.growth_trend.map((i) => i.date)
  const newUsers = growthData.value.growth_trend.map((i) => i.new_users)

  return {
    tooltip: {
      ...MODERN_TOOLTIP,
      trigger: 'axis',
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
      name: '新增用户 (人)',
      axisLabel: { color: '#909399' },
      splitLine: { lineStyle: { color: '#F2F6FC', type: 'dashed' } },
    },
    series: [
      {
        name: '每日新增用户',
        type: 'line',
        smooth: 0.35,
        symbol: 'circle',
        symbolSize: 6,
        areaStyle: {
          color: createLinearGradient('rgba(64, 158, 255, 0.35)', 'rgba(64, 158, 255, 0.02)'),
        },
        data: newUsers,
        itemStyle: { color: CHART_COLORS.primary },
        lineStyle: { width: 3 },
      },
    ],
  }
})

/**
 * 2. 消费频次阶梯环形分布 Option
 * - 展现首购、复购 2-5 次、忠诚老客 (>5次) 的群体梯队
 */
const frequencyChartOption = computed(() => {
  return {
    tooltip: {
      ...MODERN_TOOLTIP,
      trigger: 'item',
      formatter: '{b}<br/>顾客数量：{c} 人 ({d}%)',
    },
    legend: {
      bottom: '3%',
      left: 'center',
      icon: 'circle',
      textStyle: { fontSize: 12, color: '#606266' },
    },
    color: CHART_COLORS.palette,
    series: [
      {
        name: '消费频次',
        type: 'pie',
        radius: ['45%', '72%'],
        center: ['50%', '45%'],
        avoidLabelOverlap: true,
        padAngle: 3,
        itemStyle: {
          borderRadius: 6,
          borderColor: '#fff',
          borderWidth: 2,
        },
        data: frequencyList.value.map((i) => ({ value: i.count, name: `${i.tier}` })),
      },
    ],
  }
})

async function fetchData() {
  const [start_date, end_date] = dateRange.value || []
  const params = { start_date, end_date }

  try {
    const [growthRes, freqRes] = await Promise.all([
      getCustomerGrowthApi(params),
      getCustomerFrequencyApi(),
    ])

    growthData.value = growthRes.data || { total_users: 0, growth_trend: [] }
    frequencyList.value = freqRes.data || []
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
