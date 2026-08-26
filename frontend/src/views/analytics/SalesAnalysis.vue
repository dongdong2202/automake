<template>
  <div class="page-container sales-analysis-page">
    <PageHeader
      title="销售业绩与时段分析"
      subtitle="多维度分析销售趋势、高峰时段、星期规律、门店及设备产能排行与转化漏斗"
    >
      <template #actions>
        <el-radio-group v-model="granularity" size="default" @change="fetchData">
          <el-radio-button label="day">按日</el-radio-button>
          <el-radio-button label="week">按周</el-radio-button>
          <el-radio-button label="month">按月</el-radio-button>
        </el-radio-group>
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

    <!-- 图表 1: 销售业绩趋势折线图 (双 Y 轴 + 环比增长率) -->
    <div class="chart-card">
      <div class="card-header">
        <span class="card-title">
          <el-icon><TrendCharts /></el-icon>
          销售趋势（订单量、营业额与客单均价）
        </span>
      </div>
      <BaseChart :option="trendChartOption" height="340px" />
    </div>

    <!-- 图表 2 & 3: 24小时时段分布 + 星期分布 -->
    <el-row :gutter="16">
      <el-col :xs="24" :lg="12">
        <div class="chart-card">
          <div class="card-header">
            <span class="card-title">
              <el-icon><Clock /></el-icon>
              24 小时各时段销售分布
            </span>
          </div>
          <BaseChart :option="hourChartOption" height="300px" />
        </div>
      </el-col>

      <el-col :xs="24" :lg="12">
        <div class="chart-card">
          <div class="card-header">
            <span class="card-title">
              <el-icon><Calendar /></el-icon>
              星期销售分布（周一至周日）
            </span>
          </div>
          <BaseChart :option="weekdayChartOption" height="300px" />
        </div>
      </el-col>
    </el-row>

    <!-- 图表 4 & 5: 门店销售排行 + 设备产能排行 -->
    <el-row :gutter="16">
      <el-col :xs="24" :lg="12">
        <div class="chart-card">
          <div class="card-header">
            <span class="card-title">
              <el-icon><Shop /></el-icon>
              门店销售排名
            </span>
          </div>
          <BaseChart :option="storeRankingChartOption" height="300px" />
        </div>
      </el-col>

      <el-col :xs="24" :lg="12">
        <div class="chart-card">
          <div class="card-header">
            <span class="card-title">
              <el-icon><Cpu /></el-icon>
              设备出杯产能排名
            </span>
          </div>
          <BaseChart :option="deviceRankingChartOption" height="300px" />
        </div>
      </el-col>
    </el-row>

    <!-- 图表 6: 订单流转转化漏斗 -->
    <div class="chart-card">
      <div class="card-header">
        <span class="card-title">
          <el-icon><Filter /></el-icon>
          订单履约全链路转化漏斗
        </span>
      </div>
      <BaseChart :option="funnelChartOption" height="320px" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { TrendCharts, Clock, Calendar, Shop, Cpu, Filter } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import BaseChart from '@/components/charts/BaseChart.vue'
import { useDateRange } from '@/composables/useDateRange'
import {
  getSalesTrendApi,
  getSalesByHourApi,
  getSalesByWeekdayApi,
  getSalesByStoreApi,
  getSalesByDeviceApi,
  getSalesFunnelApi,
} from '@/api/analytics'

const { dateRange, shortcuts } = useDateRange()
const granularity = ref<'day' | 'week' | 'month'>('day')

const trendList = ref<any[]>([])
const hourList = ref<any[]>([])
const weekdayList = ref<any[]>([])
const storeList = ref<any[]>([])
const deviceList = ref<any[]>([])
const funnelList = ref<any[]>([])

// 1. 销售趋势
const trendChartOption = computed(() => {
  const dates = trendList.value.map((i) => i.date)
  const orders = trendList.value.map((i) => i.order_count)
  const revenues = trendList.value.map((i) => i.revenue)
  const avgs = trendList.value.map((i) => i.avg_order_value)

  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['订单量(单)', '营业额(元)', '客单价(元)'], bottom: 0 },
    grid: { left: '3%', right: '4%', bottom: '10%', top: '8%', containLabel: true },
    xAxis: { type: 'category', data: dates },
    yAxis: [
      { type: 'value', name: '订单量(单)' },
      { type: 'value', name: '金额(元)' },
    ],
    series: [
      {
        name: '订单量(单)',
        type: 'line',
        smooth: true,
        data: orders,
        itemStyle: { color: '#409EFF' },
      },
      {
        name: '营业额(元)',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        data: revenues,
        itemStyle: { color: '#67C23A' },
      },
      {
        name: '客单价(元)',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        data: avgs,
        itemStyle: { color: '#E6A23C' },
      },
    ],
  }
})

// 2. 24小时时段分布
const hourChartOption = computed(() => {
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '4%', bottom: '8%', top: '8%', containLabel: true },
    xAxis: { type: 'category', data: hourList.value.map((i) => i.hour) },
    yAxis: { type: 'value', name: '订单量' },
    series: [
      {
        name: '时段订单量',
        type: 'bar',
        data: hourList.value.map((i) => i.order_count),
        itemStyle: { color: '#409EFF', borderRadius: [4, 4, 0, 0] },
      },
    ],
  }
})

// 3. 星期分布
const weekdayChartOption = computed(() => {
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '4%', bottom: '8%', top: '8%', containLabel: true },
    xAxis: { type: 'category', data: weekdayList.value.map((i) => i.weekday) },
    yAxis: { type: 'value', name: '营业额(元)' },
    series: [
      {
        name: '星期营业额',
        type: 'bar',
        data: weekdayList.value.map((i) => i.revenue),
        itemStyle: { color: '#67C23A', borderRadius: [4, 4, 0, 0] },
      },
    ],
  }
})

// 4. 门店排行
const storeRankingChartOption = computed(() => {
  const names = storeList.value.map((i) => i.store_name).reverse()
  const revs = storeList.value.map((i) => i.revenue).reverse()

  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '8%', bottom: '5%', top: '5%', containLabel: true },
    xAxis: { type: 'value', name: '营业额(元)' },
    yAxis: { type: 'category', data: names },
    series: [
      {
        name: '营业额',
        type: 'bar',
        data: revs,
        itemStyle: { color: '#845EC2', borderRadius: [0, 4, 4, 0] },
      },
    ],
  }
})

// 5. 设备排行
const deviceRankingChartOption = computed(() => {
  const names = deviceList.value.map((i) => `${i.device_name} (${i.device_sn})`).reverse()
  const cups = deviceList.value.map((i) => i.cups_made).reverse()

  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '8%', bottom: '5%', top: '5%', containLabel: true },
    xAxis: { type: 'value', name: '出杯量' },
    yAxis: { type: 'category', data: names },
    series: [
      {
        name: '出杯量',
        type: 'bar',
        data: cups,
        itemStyle: { color: '#00C9A7', borderRadius: [0, 4, 4, 0] },
      },
    ],
  }
})

// 6. 转化漏斗
const funnelChartOption = computed(() => {
  const data = funnelList.value.map((i) => ({
    value: i.count,
    name: `${i.stage} (${i.percentage}%)`,
  }))

  return {
    tooltip: { trigger: 'item', formatter: '{a} <br/>{b} : {c}' },
    series: [
      {
        name: '订单转化',
        type: 'funnel',
        left: '10%',
        top: 20,
        bottom: 20,
        width: '80%',
        min: 0,
        sort: 'descending',
        gap: 2,
        label: { show: true, position: 'inside' },
        itemStyle: { borderColor: '#fff', borderWidth: 1 },
        data: data,
      },
    ],
  }
})

async function fetchData() {
  const [start_date, end_date] = dateRange.value || []
  const params = { start_date, end_date, granularity: granularity.value }

  try {
    const [trendRes, hourRes, weekdayRes, storeRes, deviceRes, funnelRes] = await Promise.all([
      getSalesTrendApi(params),
      getSalesByHourApi(params),
      getSalesByWeekdayApi(params),
      getSalesByStoreApi(params),
      getSalesByDeviceApi(params),
      getSalesFunnelApi(params),
    ])

    trendList.value = trendRes.data || []
    hourList.value = hourRes.data || []
    weekdayList.value = weekdayRes.data || []
    storeList.value = storeRes.data || []
    deviceList.value = deviceRes.data || []
    funnelList.value = funnelRes.data || []
  } catch (e) {
    // 错误处理已由 Axios 拦截器负责
  }
}

onMounted(() => {
  fetchData()
})
</script>
