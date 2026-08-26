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
              小程序注册用户增长趋势
            </span>
          </div>
          <BaseChart :option="growthChartOption" height="340px" />
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
          <BaseChart :option="frequencyChartOption" height="340px" />
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

const { dateRange, shortcuts } = useDateRange()
const growthData = ref<{ total_users: number; growth_trend: any[] }>({
  total_users: 0,
  growth_trend: [],
})
const frequencyList = ref<any[]>([])

// 1. 用户增长趋势 Option
const growthChartOption = computed(() => {
  const dates = growthData.value.growth_trend.map((i) => i.date)
  const newUsers = growthData.value.growth_trend.map((i) => i.new_users)

  return {
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '8%', top: '8%', containLabel: true },
    xAxis: { type: 'category', data: dates },
    yAxis: { type: 'value', name: '新增用户(人)' },
    series: [
      {
        name: '每日新增用户',
        type: 'line',
        smooth: true,
        areaStyle: { color: 'rgba(64, 158, 255, 0.2)' },
        data: newUsers,
        itemStyle: { color: '#409EFF' },
      },
    ],
  }
})

// 2. 消费频次分布 Option
const frequencyChartOption = computed(() => {
  return {
    tooltip: { trigger: 'item', formatter: '{a} <br/>{b} : {c}人 ({d}%)' },
    legend: { bottom: '5%', left: 'center' },
    series: [
      {
        name: '消费频次',
        type: 'pie',
        radius: ['40%', '70%'],
        avoidLabelOverlap: false,
        itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
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
