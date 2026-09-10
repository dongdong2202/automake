<template>
  <div class="page-container product-analysis-page">
    <PageHeader
      title="产品与品类分析"
      subtitle="挖掘爆款单品与滞销产品，分析顾客杯型与糖度规格偏好，辅助菜单迭代与定价调整"
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

    <!-- 图表行：TOP 20 排行榜 + 规格偏好环形图 -->
    <el-row :gutter="16">
      <el-col :xs="24" :lg="15">
        <div class="chart-card">
          <div class="card-header">
            <span class="card-title">
              <el-icon><GobletSquareFull /></el-icon>
              商品销售热度排行榜 TOP 15
            </span>
          </div>
          <BaseChart :option="rankingChartOption" height="420px" />
        </div>
      </el-col>

      <el-col :xs="24" :lg="9">
        <div class="chart-card">
          <div class="card-header">
            <span class="card-title">
              <el-icon><PieChart /></el-icon>
              顾客规格选择偏好分布
            </span>
          </div>
          <BaseChart :option="skuPreferencesChartOption" height="420px" />
        </div>
      </el-col>
    </el-row>

    <!-- 商品详细数据表格 -->
    <div class="chart-card" style="margin-top: 16px;">
      <div class="card-header">
        <span class="card-title">
          <el-icon><List /></el-icon>
          商品销售明细数据汇总
        </span>
      </div>

      <el-table :data="rankingList" stripe style="width: 100%">
        <el-table-column type="index" label="排名" width="80" align="center">
          <template #default="{ $index }">
            <el-tag
              :type="$index === 0 ? 'danger' : $index === 1 ? 'warning' : $index === 2 ? 'success' : 'info'"
              effect="plain"
              size="small"
              round
            >
              No.{{ $index + 1 }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="商品名称" min-width="180" />
        <el-table-column prop="quantity" label="累计销量(杯)" width="140" sortable>
          <template #default="{ row }">
            <el-tag size="small" type="primary" effect="light">{{ row.quantity }} 杯</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="revenue" label="累计营业额(元)" width="160" sortable>
          <template #default="{ row }">¥{{ formatYuan(row.revenue) }}</template>
        </el-table-column>
        <el-table-column prop="avg_price" label="单杯实付均价" width="140">
          <template #default="{ row }">¥{{ formatYuan(row.avg_price) }}</template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { GobletSquareFull, PieChart, List } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import BaseChart from '@/components/charts/BaseChart.vue'
import { useDateRange } from '@/composables/useDateRange'
import { getProductRankingApi, getProductSkuPreferencesApi } from '@/api/analytics'
import { formatYuan } from '@/utils/money'
import {
  createLinearGradient,
  CHART_COLORS,
  MODERN_TOOLTIP,
  MODERN_GRID,
} from '@/utils/chartThemes'

const { dateRange, shortcuts } = useDateRange()
const rankingList = ref<any[]>([])
const skuList = ref<any[]>([])

/**
 * TOP 15 排行榜水平胶囊条形图 Option
 * - 采用水平柱状图方便阅读长商品名称
 * - 渐变胶囊圆角与数据标签内置展现
 */
const rankingChartOption = computed(() => {
  const names = rankingList.value.slice(0, 15).map((i) => i.name).reverse()
  const qtys = rankingList.value.slice(0, 15).map((i) => i.quantity).reverse()

  return {
    tooltip: {
      ...MODERN_TOOLTIP,
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
    },
    grid: {
      ...MODERN_GRID,
      left: '4%',
      right: '6%',
      top: '4%',
      bottom: '6%',
    },
    xAxis: {
      type: 'value',
      name: '销量 (杯)',
      axisLabel: { color: '#909399' },
      splitLine: { lineStyle: { color: '#F2F6FC', type: 'dashed' } },
    },
    yAxis: {
      type: 'category',
      data: names,
      axisLine: { lineStyle: { color: '#E4E7ED' } },
      axisLabel: {
        color: '#606266',
        fontSize: 12,
        formatter: (val: string) => (val.length > 8 ? val.substring(0, 7) + '...' : val),
      },
    },
    series: [
      {
        name: '累计销量',
        type: 'bar',
        barMaxWidth: 18,
        data: qtys,
        itemStyle: {
          color: createLinearGradient(CHART_COLORS.blueGrad[0], CHART_COLORS.blueGrad[1], false),
          borderRadius: [0, 6, 6, 0],
        },
        label: {
          show: true,
          position: 'right',
          formatter: '{c} 杯',
          color: '#909399',
          fontSize: 11,
        },
      },
    ],
  }
})

/**
 * 顾客规格选择偏好环形分布图 Option
 * - 采用现代 PadAngle 环形设计，清晰展现顾客在杯型/温度/甜度等 SKU 上的偏好
 */
const skuPreferencesChartOption = computed(() => {
  const data = skuList.value.map((i) => ({ value: i.quantity, name: i.sku }))

  return {
    tooltip: {
      ...MODERN_TOOLTIP,
      trigger: 'item',
      formatter: '{b}<br/>点单量：{c} 杯 ({d}%)',
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
        name: '规格偏好',
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
        data: data,
      },
    ],
  }
})

async function fetchData() {
  const [start_date, end_date] = dateRange.value || []
  const params = { start_date, end_date }

  try {
    const [rankingRes, skuRes] = await Promise.all([
      getProductRankingApi(params),
      getProductSkuPreferencesApi(params),
    ])

    rankingList.value = rankingRes.data || []
    skuList.value = skuRes.data || []
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
