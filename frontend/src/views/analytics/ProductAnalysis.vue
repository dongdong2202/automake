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

    <!-- 图表行：TOP 20 排行榜 + 规格偏好雷达图 -->
    <el-row :gutter="16">
      <el-col :xs="24" :lg="15">
        <div class="chart-card">
          <div class="card-header">
            <span class="card-title">
              <el-icon><GobletSquareFull /></el-icon>
              商品销售热度排行榜 TOP 20
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
    <div class="chart-card">
      <div class="card-header">
        <span class="card-title">
          <el-icon><List /></el-icon>
          商品销售明细数据汇总
        </span>
      </div>

      <el-table :data="rankingList" stripe style="width: 100%">
        <el-table-column type="index" label="排名" width="80" align="center" />
        <el-table-column prop="name" label="商品名称" min-width="180" />
        <el-table-column prop="quantity" label="累计销量(杯)" width="140" sortable>
          <template #default="{ row }">
            <el-tag size="small" type="primary">{{ row.quantity }} 杯</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="revenue" label="累计营业额(元)" width="160" sortable>
          <template #default="{ row }">{{ formatYuan(row.revenue) }}</template>
        </el-table-column>
        <el-table-column prop="avg_price" label="单杯实付均价" width="140">
          <template #default="{ row }">{{ formatYuan(row.avg_price) }}</template>
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

const { dateRange, shortcuts } = useDateRange()
const rankingList = ref<any[]>([])
const skuList = ref<any[]>([])

// 1. TOP 20 排行榜柱状图 Option
const rankingChartOption = computed(() => {
  const names = rankingList.value.slice(0, 15).map((i) => i.name).reverse()
  const qtys = rankingList.value.slice(0, 15).map((i) => i.quantity).reverse()

  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '8%', bottom: '5%', top: '3%', containLabel: true },
    xAxis: { type: 'value', name: '销量(杯)' },
    yAxis: { type: 'category', data: names },
    series: [
      {
        name: '销量(杯)',
        type: 'bar',
        data: qtys,
        itemStyle: { color: '#409EFF', borderRadius: [0, 4, 4, 0] },
      },
    ],
  }
})

// 2. 规格偏好饼图 Option
const skuPreferencesChartOption = computed(() => {
  const data = skuList.value.map((i) => ({ value: i.quantity, name: i.sku }))

  return {
    tooltip: { trigger: 'item', formatter: '{a} <br/>{b} : {c}杯 ({d}%)' },
    legend: { bottom: '5%', left: 'center' },
    series: [
      {
        name: '规格偏好',
        type: 'pie',
        radius: ['40%', '70%'],
        avoidLabelOverlap: false,
        itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
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
