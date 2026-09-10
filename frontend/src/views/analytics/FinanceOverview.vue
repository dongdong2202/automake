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
        <div class="kpi-card modern-kpi">
          <div class="kpi-title">
            <span>总营业额 (Gross)</span>
            <el-tag size="small" type="success" effect="plain">收款总计</el-tag>
          </div>
          <div class="kpi-value text-success">¥{{ formatNumber(summary.gross_revenue) }}</div>
          <div class="kpi-footer">
            <span>已支付成功订单 {{ summary.paid_orders }} 笔</span>
          </div>
        </div>
      </el-col>

      <el-col :xs="24" :sm="12" :md="6">
        <div class="kpi-card modern-kpi">
          <div class="kpi-title">
            <span>退款总额 (Refund)</span>
            <el-tag size="small" type="danger" effect="plain">冲正与退款</el-tag>
          </div>
          <div class="kpi-value text-danger">¥{{ formatNumber(summary.refund_amount) }}</div>
          <div class="kpi-footer">
            <span>退款笔数 {{ summary.refund_orders }} 笔</span>
          </div>
        </div>
      </el-col>

      <el-col :xs="24" :sm="12" :md="6">
        <div class="kpi-card modern-kpi">
          <div class="kpi-title">
            <span>净营业收入 (Net)</span>
            <el-tag size="small" type="primary" effect="plain">实际到账</el-tag>
          </div>
          <div class="kpi-value text-primary">¥{{ formatNumber(summary.net_revenue) }}</div>
          <div class="kpi-footer">
            <span>总营收 - 退款总额</span>
          </div>
        </div>
      </el-col>

      <el-col :xs="24" :sm="12" :md="6">
        <div class="kpi-card modern-kpi">
          <div class="kpi-title">
            <span>全网退款率</span>
            <el-tag size="small" :type="summary.refund_rate > 5 ? 'danger' : 'info'" effect="plain">
              {{ summary.refund_rate > 5 ? '需预警' : '平稳' }}
            </el-tag>
          </div>
          <div class="kpi-value" :class="summary.refund_rate > 5 ? 'text-danger' : ''">{{ summary.refund_rate }}%</div>
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
          <BaseChart :option="trendChartOption" height="360px" />
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
          <BaseChart :option="categoryPieChartOption" height="360px" />
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
import {
  createLinearGradient,
  CHART_COLORS,
  MODERN_TOOLTIP,
  MODERN_GRID,
} from '@/utils/chartThemes'

const { dateRange, shortcuts } = useDateRange()

// 财务汇总 KPI 指标数据对象
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

/**
 * 格式化千分位货币数值
 */
function formatNumber(num: number): string {
  return (num || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/**
 * 营收与退款趋势对比柱/折混合图 Option
 * - 采用双柱并列对比总营收与退款损失
 * - 叠加净收入平滑折线，直观展现利润走势
 */
const trendChartOption = computed(() => {
  const dates = trendList.value.map((i) => i.date)
  const revs = trendList.value.map((i) => i.revenue)
  const refs = trendList.value.map((i) => i.refund)
  const nets = trendList.value.map((i) => i.net_revenue)

  return {
    tooltip: {
      ...MODERN_TOOLTIP,
      trigger: 'axis',
    },
    legend: {
      data: ['总营收(元)', '退款额(元)', '净收入(元)'],
      bottom: 0,
      icon: 'roundRect',
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
      name: '金额 (元)',
      axisLabel: { color: '#909399' },
      splitLine: { lineStyle: { color: '#F2F6FC', type: 'dashed' } },
    },
    series: [
      {
        name: '总营收(元)',
        type: 'bar',
        barMaxWidth: 16,
        data: revs,
        itemStyle: {
          color: createLinearGradient(CHART_COLORS.greenGrad[0], CHART_COLORS.greenGrad[1]),
          borderRadius: [4, 4, 0, 0],
        },
      },
      {
        name: '退款额(元)',
        type: 'bar',
        barMaxWidth: 16,
        data: refs,
        itemStyle: {
          color: createLinearGradient('#F56C6C', '#F89898'),
          borderRadius: [4, 4, 0, 0],
        },
      },
      {
        name: '净收入(元)',
        type: 'line',
        smooth: 0.35,
        symbol: 'circle',
        symbolSize: 6,
        data: nets,
        itemStyle: { color: CHART_COLORS.primary },
        lineStyle: { width: 3 },
      },
    ],
  }
})

/**
 * 品类营收构成环形占比图 Option
 * - 采用现代 PadAngle 环形设计与企业级明亮配色
 */
const categoryPieChartOption = computed(() => {
  return {
    tooltip: {
      ...MODERN_TOOLTIP,
      trigger: 'item',
      formatter: '{b}<br/>营收贡献：¥{c} ({d}%)',
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
        name: '品类营收',
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
        label: {
          show: false,
        },
        emphasis: {
          label: {
            show: true,
            fontSize: 14,
            fontWeight: 'bold',
          },
        },
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
  margin-bottom: 12px;
}

.modern-kpi {
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  border: 1px solid #ebeef5;
}

.modern-kpi:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 16px rgba(0, 0, 0, 0.06);
}

.text-success {
  color: #67c23a;
}

.text-danger {
  color: #f56c6c;
}

.text-primary {
  color: #409eff;
}
</style>
