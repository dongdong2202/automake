<template>
  <div class="page-container finance-overview-page">
    <PageHeader
      title="财务收支与退款概览"
      subtitle="实时分析系统总营业额、退款损失、净收益趋势以及各品类商品营收贡献构成"
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

    <!-- 财务 KPI 汇总卡片 -->
    <el-row :gutter="16" class="kpi-row">
      <el-col :xs="24" :sm="12" :md="6">
        <div class="kpi-card">
          <div class="kpi-title">
            <span>总营业额 (Gross)</span>
            <el-tag size="small" type="success">收款总计</el-tag>
          </div>
          <div class="kpi-value">¥{{ formatNumber(summary.gross_revenue) }}</div>
          <div class="kpi-footer">
            <span>已支付成功订单 {{ summary.paid_orders }} 笔</span>
          </div>
        </div>
      </el-col>

      <el-col :xs="24" :sm="12" :md="6">
        <div class="kpi-card">
          <div class="kpi-title">
            <span>退款总额 (Refund)</span>
            <el-tag size="small" type="danger">冲正与退款</el-tag>
          </div>
          <div class="kpi-value" style="color: #F56C6C;">¥{{ formatNumber(summary.refund_amount) }}</div>
          <div class="kpi-footer">
            <span>退款笔数 {{ summary.refund_orders }} 笔</span>
          </div>
        </div>
      </el-col>

      <el-col :xs="24" :sm="12" :md="6">
        <div class="kpi-card">
          <div class="kpi-title">
            <span>净营业收入 (Net)</span>
            <el-tag size="small" type="primary">实际到账</el-tag>
          </div>
          <div class="kpi-value" style="color: #409EFF;">¥{{ formatNumber(summary.net_revenue) }}</div>
          <div class="kpi-footer">
            <span>总营收 - 退款总额</span>
          </div>
        </div>
      </el-col>

      <el-col :xs="24" :sm="12" :md="6">
        <div class="kpi-card">
          <div class="kpi-title">
            <span>全网退款率</span>
            <el-tag size="small" :type="summary.refund_rate > 5 ? 'danger' : 'info'">
              {{ summary.refund_rate > 5 ? '需预警' : '平稳' }}
            </el-tag>
          </div>
          <div class="kpi-value">{{ summary.refund_rate }}%</div>
          <div class="kpi-footer">
            <span>净客单均价 ¥{{ summary.avg_net_order_value }}</span>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 图表行：营收 vs 退款趋势 + 品类营收占比 -->
    <el-row :gutter="16">
      <el-col :xs="24" :lg="15">
        <div class="chart-card">
          <div class="card-header">
            <span class="card-title">
              <el-icon><Money /></el-icon>
              营收与退款收支趋势对比
            </span>
          </div>
          <BaseChart :option="trendChartOption" height="340px" />
        </div>
      </el-col>

      <el-col :xs="24" :lg="9">
        <div class="chart-card">
          <div class="card-header">
            <span class="card-title">
              <el-icon><PieChart /></el-icon>
              品类营收构成占比
            </span>
          </div>
          <BaseChart :option="categoryPieChartOption" height="340px" />
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Money, PieChart } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import BaseChart from '@/components/charts/BaseChart.vue'
import { useDateRange } from '@/composables/useDateRange'
import {
  getFinanceSummaryApi,
  getFinanceTrendApi,
  getFinanceCategoryShareApi,
} from '@/api/analytics'

const { dateRange, shortcuts } = useDateRange()

const summary = ref<any>({
  gross_revenue: 0,
  refund_amount: 0,
  net_revenue: 0,
  refund_rate: 0,
  paid_orders: 0,
  refund_orders: 0,
  avg_net_order_value: 0,
})

const trendList = ref<any[]>([])
const categoryShareList = ref<any[]>([])

function formatNumber(num: number): string {
  return (num || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

// 营收与退款趋势图 Option
const trendChartOption = computed(() => {
  const dates = trendList.value.map((i) => i.date)
  const revs = trendList.value.map((i) => i.revenue)
  const refs = trendList.value.map((i) => i.refund)
  const nets = trendList.value.map((i) => i.net_revenue)

  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['总营收(元)', '退款额(元)', '净收入(元)'], bottom: 0 },
    grid: { left: '3%', right: '4%', bottom: '10%', top: '8%', containLabel: true },
    xAxis: { type: 'category', data: dates },
    yAxis: { type: 'value', name: '金额(元)' },
    series: [
      {
        name: '总营收(元)',
        type: 'bar',
        data: revs,
        itemStyle: { color: '#67C23A', borderRadius: [4, 4, 0, 0] },
      },
      {
        name: '退款额(元)',
        type: 'bar',
        data: refs,
        itemStyle: { color: '#F56C6C', borderRadius: [4, 4, 0, 0] },
      },
      {
        name: '净收入(元)',
        type: 'line',
        smooth: true,
        data: nets,
        itemStyle: { color: '#409EFF' },
      },
    ],
  }
})

// 品类构成饼图 Option
const categoryPieChartOption = computed(() => {
  return {
    tooltip: { trigger: 'item', formatter: '{a} <br/>{b} : ¥{c} ({d}%)' },
    legend: { bottom: '5%', left: 'center' },
    series: [
      {
        name: '品类营收',
        type: 'pie',
        radius: ['40%', '70%'],
        avoidLabelOverlap: false,
        itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
        data: categoryShareList.value,
      },
    ],
  }
})

async function fetchData() {
  const [start_date, end_date] = dateRange.value || []
  const params = { start_date, end_date }

  try {
    const [summaryRes, trendRes, categoryRes] = await Promise.all([
      getFinanceSummaryApi(params),
      getFinanceTrendApi(params),
      getFinanceCategoryShareApi(params),
    ])

    summary.value = summaryRes.data || {}
    trendList.value = trendRes.data || []
    categoryShareList.value = categoryRes.data || []
  } catch (e) {
    // 错误处理已由 Axios 拦截器负责
  }
}

onMounted(() => {
  fetchData()
})
</script>

<style scoped>
.kpi-row {
  margin-bottom: 8px;
}
</style>
