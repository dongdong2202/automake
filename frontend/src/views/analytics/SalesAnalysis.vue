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

import {
  CHART_COLORS,
  createLinearGradient,
  MODERN_TOOLTIP,
  MODERN_GRID
} from '@/utils/chartThemes'

const { dateRange, shortcuts } = useDateRange()
const granularity = ref<'day' | 'week' | 'month'>('day')

const trendList = ref<any[]>([])
const hourList = ref<any[]>([])
const weekdayList = ref<any[]>([])
const storeList = ref<any[]>([])
const deviceList = ref<any[]>([])
const funnelList = ref<any[]>([])

// 1. 销售趋势（三维双轴复合平滑渐变面积图）
const trendChartOption = computed(() => {
  const dates = trendList.value.map((i) => i.date)
  const orders = trendList.value.map((i) => i.order_count)
  const revenues = trendList.value.map((i) => i.revenue)
  const avgs = trendList.value.map((i) => i.avg_order_value)

  return {
    tooltip: {
      ...MODERN_TOOLTIP,
      formatter: (params: any) => {
        if (!Array.isArray(params)) return ''
        let tip = `<div style="font-weight: 600; margin-bottom: 6px; color: #1e293b;">📅 ${params[0]?.name || ''} 销售分析</div>`
        params.forEach((item: any) => {
          const marker = `<span style="display:inline-block;margin-right:6px;border-radius:50%;width:8px;height:8px;background-color:${item.color};"></span>`
          const isYuan = item.seriesName.includes('元')
          const valStr = isYuan ? `¥${(item.value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}` : `${item.value} 单`
          tip += `<div style="display:flex;justify-content:space-between;gap:16px;margin:3px 0;color:#475569;font-size:12px;">
            <span>${marker}${item.seriesName}</span>
            <strong style="color:#0f172a;">${valStr}</strong>
          </div>`
        })
        return tip
      },
    },
    legend: {
      data: ['订单量(单)', '营业额(元)', '客单价(元)'],
      bottom: 2,
      textStyle: { color: CHART_COLORS.textSecondary, fontSize: 12 },
      itemGap: 20,
    },
    grid: { ...MODERN_GRID, top: '12%', bottom: '12%' },
    xAxis: {
      type: 'category',
      data: dates,
      axisLine: { lineStyle: { color: CHART_COLORS.borderLight } },
      axisLabel: { color: CHART_COLORS.textSecondary, fontSize: 12 },
    },
    yAxis: [
      {
        type: 'value',
        name: '订单量(单)',
        nameTextStyle: { color: CHART_COLORS.textMuted, fontSize: 11 },
        axisLabel: { color: CHART_COLORS.textSecondary },
        splitLine: { lineStyle: { color: CHART_COLORS.gridLine, type: 'dashed' } },
      },
      {
        type: 'value',
        name: '金额(元)',
        nameTextStyle: { color: CHART_COLORS.textMuted, fontSize: 11 },
        axisLabel: { color: CHART_COLORS.textSecondary, formatter: '¥{value}' },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '订单量(单)',
        type: 'line',
        smooth: 0.35,
        data: orders,
        lineStyle: { width: 3, color: CHART_COLORS.primary },
        itemStyle: { color: CHART_COLORS.primary },
        areaStyle: {
          color: createLinearGradient('rgba(59, 130, 246, 0.28)', 'rgba(59, 130, 246, 0.02)'),
        },
      },
      {
        name: '营业额(元)',
        type: 'line',
        yAxisIndex: 1,
        smooth: 0.35,
        data: revenues,
        lineStyle: { width: 3, color: CHART_COLORS.success },
        itemStyle: { color: CHART_COLORS.success },
        areaStyle: {
          color: createLinearGradient('rgba(16, 185, 129, 0.28)', 'rgba(16, 185, 129, 0.02)'),
        },
      },
      {
        name: '客单价(元)',
        type: 'line',
        yAxisIndex: 1,
        smooth: 0.35,
        data: avgs,
        lineStyle: { width: 2, type: 'dashed', color: CHART_COLORS.warning },
        itemStyle: { color: CHART_COLORS.warning },
      },
    ],
  }
})

// 2. 24小时时段分布（圆角高亮渐变柱状图）
const hourChartOption = computed(() => {
  return {
    tooltip: { ...MODERN_TOOLTIP, axisPointer: { type: 'shadow' } },
    grid: { ...MODERN_GRID, top: '14%', bottom: '10%' },
    xAxis: {
      type: 'category',
      data: hourList.value.map((i) => i.hour),
      axisLabel: { color: CHART_COLORS.textSecondary, fontSize: 11 },
      axisLine: { lineStyle: { color: CHART_COLORS.borderLight } },
    },
    yAxis: {
      type: 'value',
      name: '订单量(单)',
      axisLabel: { color: CHART_COLORS.textMuted },
      splitLine: { lineStyle: { color: CHART_COLORS.gridLine, type: 'dashed' } },
    },
    series: [
      {
        name: '时段订单量',
        type: 'bar',
        barMaxWidth: 20,
        data: hourList.value.map((i) => i.order_count),
        itemStyle: {
          color: (params: any) => {
            // 早高峰(8-9点)与午高峰(13-15点)采用琥珀金高亮
            const h = parseInt(params.name)
            if (h === 8 || h === 9 || h === 14 || h === 15) {
              return createLinearGradient('#f59e0b', '#fbbf24')
            }
            return createLinearGradient('#3b82f6', '#60a5fa')
          },
          borderRadius: [4, 4, 0, 0],
        },
      },
    ],
  }
})

// 3. 星期分布（圆角渐变平滑柱状图）
const weekdayChartOption = computed(() => {
  return {
    tooltip: { ...MODERN_TOOLTIP, axisPointer: { type: 'shadow' } },
    grid: { ...MODERN_GRID, top: '14%', bottom: '10%' },
    xAxis: {
      type: 'category',
      data: weekdayList.value.map((i) => i.weekday),
      axisLabel: { color: CHART_COLORS.textSecondary, fontSize: 12 },
      axisLine: { lineStyle: { color: CHART_COLORS.borderLight } },
    },
    yAxis: {
      type: 'value',
      name: '营业额(元)',
      axisLabel: { color: CHART_COLORS.textMuted, formatter: '¥{value}' },
      splitLine: { lineStyle: { color: CHART_COLORS.gridLine, type: 'dashed' } },
    },
    series: [
      {
        name: '星期营业额',
        type: 'bar',
        barMaxWidth: 28,
        data: weekdayList.value.map((i) => i.revenue),
        itemStyle: {
          color: createLinearGradient('#10b981', '#34d399'),
          borderRadius: [6, 6, 0, 0],
        },
      },
    ],
  }
})

// 4. 门店排行（水平横向圆角渐变条）
const storeRankingChartOption = computed(() => {
  const names = storeList.value.map((i) => i.store_name).reverse()
  const revs = storeList.value.map((i) => i.revenue).reverse()

  return {
    tooltip: { ...MODERN_TOOLTIP, axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '12%', bottom: '5%', top: '6%', containLabel: true },
    xAxis: {
      type: 'value',
      name: '营业额(元)',
      axisLabel: { color: CHART_COLORS.textMuted },
      splitLine: { lineStyle: { color: CHART_COLORS.gridLine, type: 'dashed' } },
    },
    yAxis: {
      type: 'category',
      data: names,
      axisLabel: { color: CHART_COLORS.textSecondary, fontSize: 12 },
      axisLine: { lineStyle: { color: CHART_COLORS.borderLight } },
    },
    series: [
      {
        name: '营业额',
        type: 'bar',
        barMaxWidth: 20,
        data: revs,
        label: {
          show: true,
          position: 'right',
          color: CHART_COLORS.textSecondary,
          formatter: '¥{c}',
        },
        itemStyle: {
          color: createLinearGradient('#8b5cf6', '#a78bfa', false),
          borderRadius: [0, 6, 6, 0],
        },
      },
    ],
  }
})

// 5. 设备排行（水平横向圆角渐变条）
const deviceRankingChartOption = computed(() => {
  const names = deviceList.value.map((i) => `${i.device_name} (${i.device_sn})`).reverse()
  const cups = deviceList.value.map((i) => i.cups_made).reverse()

  return {
    tooltip: { ...MODERN_TOOLTIP, axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '12%', bottom: '5%', top: '6%', containLabel: true },
    xAxis: {
      type: 'value',
      name: '出杯量(杯)',
      axisLabel: { color: CHART_COLORS.textMuted },
      splitLine: { lineStyle: { color: CHART_COLORS.gridLine, type: 'dashed' } },
    },
    yAxis: {
      type: 'category',
      data: names,
      axisLabel: { color: CHART_COLORS.textSecondary, fontSize: 12 },
      axisLine: { lineStyle: { color: CHART_COLORS.borderLight } },
    },
    series: [
      {
        name: '出杯量',
        type: 'bar',
        barMaxWidth: 20,
        data: cups,
        label: {
          show: true,
          position: 'right',
          color: CHART_COLORS.textSecondary,
          formatter: '{c} 杯',
        },
        itemStyle: {
          color: createLinearGradient('#06b6d4', '#22d3ee', false),
          borderRadius: [0, 6, 6, 0],
        },
      },
    ],
  }
})

// 6. 订单流转转化漏斗
const funnelChartOption = computed(() => {
  return {
    tooltip: {
      ...MODERN_TOOLTIP,
      trigger: 'item',
      formatter: '{a} <br/>{b} : {c} 单',
    },
    color: ['#3b82f6', '#6366f1', '#8b5cf6', '#10b981'],
    series: [
      {
        name: '订单转化',
        type: 'funnel',
        left: '10%',
        top: 20,
        bottom: 20,
        width: '80%',
        minSize: '20%',
        maxSize: '100%',
        sort: 'descending',
        gap: 4,
        label: {
          show: true,
          position: 'inside',
          formatter: '{b}: {c}单',
          color: '#ffffff',
          fontWeight: 600,
        },
        itemStyle: {
          borderColor: '#fff',
          borderWidth: 2,
          borderRadius: 6,
        },
        emphasis: {
          label: {
            fontSize: 14,
          },
        },
        data: funnelList.value.map((i) => ({ value: i.count, name: i.stage })),
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
