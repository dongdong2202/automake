<template>
  <div class="page-container dashboard-page">
    <!-- 顶部操作与指引 -->
    <div class="guide-tip">
      <el-icon><InfoFilled /></el-icon>
      <span>💡 欢迎进入运营驾驶舱！以下是实时业务与设备运营指标，点击图表卡片可深入对应模块。</span>
    </div>

    <!-- 6 大核心 KPI 统计卡片 -->
    <el-row :gutter="16" class="kpi-row">
      <el-col :xs="24" :sm="12" :md="8" :lg="4">
        <div class="kpi-card" @click="$router.push('/analytics/finance')">
          <div class="kpi-title">
            <span>今日营收</span>
            <el-tag size="small" type="success">实时</el-tag>
          </div>
          <div class="kpi-value">¥{{ formatNumber(kpis.today_revenue) }}</div>
          <div class="kpi-footer">
            <span>较昨日</span>
            <span :class="kpis.revenue_growth >= 0 ? 'trend-up' : 'trend-down'">
              {{ kpis.revenue_growth >= 0 ? '↑' : '↓' }} {{ Math.abs(kpis.revenue_growth) }}%
            </span>
          </div>
        </div>
      </el-col>

      <el-col :xs="24" :sm="12" :md="8" :lg="4">
        <div class="kpi-card" @click="$router.push('/analytics/sales')">
          <div class="kpi-title">
            <span>今日订单量</span>
            <el-tag size="small">实时</el-tag>
          </div>
          <div class="kpi-value">{{ kpis.today_orders }} <span class="unit">单</span></div>
          <div class="kpi-footer">
            <span>较昨日</span>
            <span :class="kpis.orders_growth >= 0 ? 'trend-up' : 'trend-down'">
              {{ kpis.orders_growth >= 0 ? '↑' : '↓' }} {{ Math.abs(kpis.orders_growth) }}%
            </span>
          </div>
        </div>
      </el-col>

      <el-col :xs="24" :sm="12" :md="8" :lg="4">
        <div class="kpi-card" @click="$router.push('/analytics/sales')">
          <div class="kpi-title">
            <span>客单均价</span>
          </div>
          <div class="kpi-value">¥{{ formatNumber(kpis.avg_order_value) }}</div>
          <div class="kpi-footer">
            <span>实付/订单</span>
          </div>
        </div>
      </el-col>

      <el-col :xs="24" :sm="12" :md="8" :lg="4">
        <div class="kpi-card" @click="$router.push('/monitor')">
          <div class="kpi-title">
            <span>设备在线率</span>
            <el-tag size="small" :type="kpis.device_online_rate >= 80 ? 'success' : 'danger'">
              {{ kpis.online_devices }}/{{ kpis.total_devices }}
            </el-tag>
          </div>
          <div class="kpi-value">{{ kpis.device_online_rate }}%</div>
          <div class="kpi-footer">
            <span>健康在线设备</span>
          </div>
        </div>
      </el-col>

      <el-col :xs="24" :sm="12" :md="8" :lg="4">
        <div class="kpi-card" @click="$router.push('/notifications')">
          <div class="kpi-title">
            <span>未处理告警</span>
            <el-tag size="small" :type="kpis.unhandled_alarms > 0 ? 'danger' : 'info'">
              {{ kpis.unhandled_alarms > 0 ? '需关注' : '正常' }}
            </el-tag>
          </div>
          <div class="kpi-value" :style="{ color: kpis.unhandled_alarms > 0 ? '#F56C6C' : '#303133' }">
            {{ kpis.unhandled_alarms }} <span class="unit">条</span>
          </div>
          <div class="kpi-footer">
            <span>待处理硬件/物料异常</span>
          </div>
        </div>
      </el-col>

      <el-col :xs="24" :sm="12" :md="8" :lg="4">
        <div class="kpi-card" @click="$router.push('/analytics/customers')">
          <div class="kpi-title">
            <span>今日新增用户</span>
          </div>
          <div class="kpi-value">{{ kpis.today_new_users }} <span class="unit">人</span></div>
          <div class="kpi-footer">
            <span>微信小程序新注册</span>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 图表第一行：近7天趋势 + TOP10热销商品 -->
    <el-row :gutter="16">
      <el-col :xs="24" :lg="15">
        <div class="chart-card">
          <div class="card-header">
            <span class="card-title">
              <el-icon><TrendCharts /></el-icon>
              近 7 天经营趋势（订单量与营收）
            </span>
            <el-button type="primary" link @click="$router.push('/analytics/sales')">
              详细销售分析 <el-icon><ArrowRight /></el-icon>
            </el-button>
          </div>
          <BaseChart :option="trendChartOption" height="320px" />
        </div>
      </el-col>

      <el-col :xs="24" :lg="9">
        <div class="chart-card">
          <div class="card-header">
            <span class="card-title">
              <el-icon><GobletSquareFull /></el-icon>
              热销商品 TOP 10
            </span>
            <el-button type="primary" link @click="$router.push('/analytics/products')">
              产品分析 <el-icon><ArrowRight /></el-icon>
            </el-button>
          </div>
          <BaseChart :option="topItemsChartOption" height="320px" />
        </div>
      </el-col>
    </el-row>

    <!-- 图表第二行：设备状态分布 + 物料预警 -->
    <el-row :gutter="16">
      <el-col :xs="24" :lg="8">
        <div class="chart-card">
          <div class="card-header">
            <span class="card-title">
              <el-icon><Platform /></el-icon>
              设备运行状态分布
            </span>
            <el-button type="primary" link @click="$router.push('/monitor')">
              监控大屏 <el-icon><ArrowRight /></el-icon>
            </el-button>
          </div>
          <BaseChart :option="deviceStatusChartOption" height="280px" />
        </div>
      </el-col>

      <el-col :xs="24" :lg="16">
        <div class="chart-card">
          <div class="card-header">
            <span class="card-title">
              <el-icon><Box /></el-icon>
              仓库重点物料库存预警
            </span>
            <el-button type="primary" link @click="$router.push('/inventory')">
              进销存管理 <el-icon><ArrowRight /></el-icon>
            </el-button>
          </div>

          <el-table :data="materialWarnings" size="small" stripe style="width: 100%">
            <el-table-column prop="code" label="物料编码" width="100" />
            <el-table-column prop="name" label="物料名称" min-width="120" />
            <el-table-column prop="material_type" label="类别" width="100" />
            <el-table-column prop="quantity" label="当前库存" width="120">
              <template #default="{ row }">
                <el-tag :type="row.quantity <= 10 ? 'danger' : 'warning'" size="small">
                  {{ row.quantity }} {{ row.unit }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-button type="primary" link size="small" @click="$router.push('/inventory')">
                  去补货
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-col>
    </el-row>

    <!-- 实时订单动态 -->
    <div class="chart-card">
      <div class="card-header">
        <span class="card-title">
          <el-icon><List /></el-icon>
          实时订单流水（最近 10 条）
        </span>
        <el-button type="primary" link @click="$router.push('/orders')">
          查看全部订单 <el-icon><ArrowRight /></el-icon>
        </el-button>
      </div>

      <el-table :data="recentOrders" size="small" stripe style="width: 100%">
        <el-table-column prop="order_no" label="订单号" min-width="160" />
        <el-table-column prop="store_name" label="门店" width="140" />
        <el-table-column prop="device_sn" label="制作设备" width="140" />
        <el-table-column prop="items_summary" label="商品摘要" min-width="180" />
        <el-table-column prop="pay_amount" label="实付金额" width="110">
          <template #default="{ row }">¥{{ row.pay_amount }}</template>
        </el-table-column>
        <el-table-column prop="status_display" label="订单状态" width="110">
          <template #default="{ row }">
            <StatusBadge :status="row.status" :text="row.status_display" />
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="下单时间" width="100" />
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import {
  TrendCharts,
  GobletSquareFull,
  Platform,
  Box,
  List,
  ArrowRight,
  InfoFilled
} from '@element-plus/icons-vue'
import BaseChart from '@/components/charts/BaseChart.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { getDashboardStatsApi } from '@/api/dashboard'

const loading = ref(false)
const kpis = ref<any>({
  today_revenue: 0,
  yesterday_revenue: 0,
  revenue_growth: 0,
  today_orders: 0,
  yesterday_orders: 0,
  orders_growth: 0,
  avg_order_value: 0,
  online_devices: 0,
  total_devices: 0,
  device_online_rate: 0,
  unhandled_alarms: 0,
  today_new_users: 0,
})

const trendData = ref<{ labels: string[]; orders: number[]; revenue: number[] }>({
  labels: [],
  orders: [],
  revenue: [],
})

const topItems = ref<Array<{ name: string; quantity: number; amount: number }>>([])
const deviceStatus = ref<{ online: number; offline: number; fault: number }>({
  online: 0,
  offline: 0,
  fault: 0,
})
const materialWarnings = ref<any[]>([])
const recentOrders = ref<any[]>([])

function formatNumber(num: number): string {
  return (num || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

// 1. 近7天趋势图 Option
const trendChartOption = computed(() => {
  return {
    tooltip: {
      trigger: 'axis',
    },
    legend: {
      data: ['订单量(单)', '营业额(元)'],
      bottom: 0,
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '10%',
      top: '8%',
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: trendData.value.labels,
    },
    yAxis: [
      {
        type: 'value',
        name: '订单量',
      },
      {
        type: 'value',
        name: '营业额(元)',
      },
    ],
    series: [
      {
        name: '订单量(单)',
        type: 'line',
        smooth: true,
        data: trendData.value.orders,
        areaStyle: { opacity: 0.1 },
        itemStyle: { color: '#409EFF' },
      },
      {
        name: '营业额(元)',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        data: trendData.value.revenue,
        areaStyle: { opacity: 0.1 },
        itemStyle: { color: '#67C23A' },
      },
    ],
  }
})

// 2. 热销 TOP 10 柱状图 Option
const topItemsChartOption = computed(() => {
  const names = topItems.value.map((i) => i.name).reverse()
  const qtys = topItems.value.map((i) => i.quantity).reverse()

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
    },
    grid: {
      left: '3%',
      right: '8%',
      bottom: '3%',
      top: '3%',
      containLabel: true,
    },
    xAxis: {
      type: 'value',
    },
    yAxis: {
      type: 'category',
      data: names,
    },
    series: [
      {
        name: '销量(杯)',
        type: 'bar',
        data: qtys,
        itemStyle: {
          borderRadius: [0, 4, 4, 0],
          color: '#409EFF',
        },
      },
    ],
  }
})

// 3. 设备状态环形图 Option
const deviceStatusChartOption = computed(() => {
  return {
    tooltip: {
      trigger: 'item',
    },
    legend: {
      bottom: '5%',
      left: 'center',
    },
    series: [
      {
        name: '设备状态',
        type: 'pie',
        radius: ['45%', '70%'],
        avoidLabelOverlap: false,
        itemStyle: {
          borderRadius: 6,
          borderColor: '#fff',
          borderWidth: 2,
        },
        label: {
          show: false,
          position: 'center',
        },
        emphasis: {
          label: {
            show: true,
            fontSize: 16,
            fontWeight: 'bold',
          },
        },
        data: [
          { value: deviceStatus.value.online, name: '在线正常', itemStyle: { color: '#67C23A' } },
          { value: deviceStatus.value.fault, name: '设备故障', itemStyle: { color: '#F56C6C' } },
          { value: deviceStatus.value.offline, name: '离线状态', itemStyle: { color: '#909399' } },
        ],
      },
    ],
  }
})

async function fetchStats() {
  loading.value = true
  try {
    const res = await getDashboardStatsApi()
    if (res.data) {
      kpis.value = res.data.kpis || {}
      trendData.value = res.data.trend || { labels: [], orders: [], revenue: [] }
      topItems.value = res.data.top_items || []
      deviceStatus.value = res.data.device_status || { online: 0, offline: 0, fault: 0 }
      materialWarnings.value = res.data.material_warnings || []
      recentOrders.value = res.data.recent_orders || []
    }
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchStats()
})
</script>

<style scoped lang="scss">
.kpi-row {
  margin-bottom: 8px;
}

.unit {
  font-size: 13px;
  font-weight: normal;
  color: #909399;
}
</style>
