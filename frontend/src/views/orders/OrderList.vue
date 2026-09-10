<template>
  <div class="page-container order-list-page">
    <PageHeader
      title="订单流水与履约中心"
      subtitle="全生命周期追踪点单、预扣、设备制作、取餐码核销与退款流转状态"
    />

    <div class="chart-card">
      <el-form :inline="true" :model="filters" size="default">
        <el-form-item label="订单号">
          <el-input v-model="filters.order_no" placeholder="输入订单号搜索" clearable />
        </el-form-item>
        <el-form-item label="订单状态">
          <el-select v-model="filters.status" placeholder="全部状态" clearable style="width: 140px;">
            <el-option label="已创建 (待支付)" value="created" />
            <el-option label="待出货 (已支付)" value="pending_dispense" />
            <el-option label="制作中" value="making" />
            <el-option label="已完成 (出杯成功)" value="success" />
            <el-option label="已取消" value="cancelled" />
            <el-option label="已退款" value="refunded" />
            <el-option label="制作失败 (异常)" value="failed" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" icon="Search" @click="fetchOrders">查询</el-button>
        </el-form-item>
      </el-form>

      <el-table v-loading="loading" :data="orderList" stripe style="width: 100%">
        <el-table-column prop="order_no" label="订单号" min-width="170" />
        <el-table-column prop="store_name" label="门店" width="130" />
        <el-table-column prop="device_sn" label="制作设备" width="140" />
        <el-table-column prop="pay_amount" label="实付金额" width="110">
          <template #default="{ row }">{{ formatCurrency(row.pay_amount) }}</template>
        </el-table-column>
        <el-table-column prop="status_display" label="当前状态" width="110">
          <template #default="{ row }">
            <StatusBadge :status="row.status" :text="row.status_display" />
          </template>
        </el-table-column>
        <el-table-column prop="pickup_code" label="取餐码" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.pickup_code" type="success" size="small">{{ row.pickup_code }}</el-tag>
            <span v-else style="color: #909399;">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="下单时间" width="170" />
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="openOrderDetail(row.order_no)">
              明细
            </el-button>
            <el-button
              v-if="row.status === 'pending_dispense'"
              type="warning"
              link
              size="small"
              @click="openRefundDialog(row, 'auto')"
            >
              自动退款
            </el-button>
            <el-button
              v-if="['pending_dispense', 'making', 'success', 'failed'].includes(row.status)"
              type="danger"
              link
              size="small"
              @click="openRefundDialog(row, 'force')"
            >
              强制退款
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 订单明细抽屉 -->
    <el-drawer v-model="showDrawer" title="订单完整履约明细" size="480px">
      <div v-if="currentOrder" class="drawer-content">
        <el-descriptions title="基础信息" :column="1" border size="small">
          <el-descriptions-item label="订单编号">{{ currentOrder.order_no }}</el-descriptions-item>
          <el-descriptions-item label="下单门店">{{ currentOrder.store_name }}</el-descriptions-item>
          <el-descriptions-item label="制作设备">{{ currentOrder.device_sn || '未分配' }}</el-descriptions-item>
          <el-descriptions-item label="实付金额">{{ formatCurrency(currentOrder.pay_amount) }}</el-descriptions-item>
          <el-descriptions-item label="订单状态">
            <StatusBadge :status="currentOrder.status" :text="currentOrder.status_display" />
          </el-descriptions-item>
        </el-descriptions>

        <h4 style="margin: 20px 0 10px;">商品购买清单</h4>
        <el-table :data="currentOrder.items || []" size="small" border>
          <el-table-column prop="item_name" label="商品" />
          <el-table-column prop="sku_name" label="规格" />
          <el-table-column prop="unit_price" label="单价" width="85">
            <template #default="{ row }">{{ formatCurrency(row.unit_price) }}</template>
          </el-table-column>
          <el-table-column prop="quantity" label="数量" width="70" />
          <el-table-column prop="subtotal" label="小计" width="95">
            <template #default="{ row }">{{ formatCurrency(row.subtotal) }}</template>
          </el-table-column>
        </el-table>

        <h4 style="margin: 20px 0 10px;">履约流转时间线</h4>
        <el-timeline style="padding-left: 5px;">
          <el-timeline-item
            v-for="(log, idx) in currentOrder.status_logs || []"
            :key="idx"
            :timestamp="log.created_at"
            :type="getTimelineType(log)"
            size="large"
          >
            <div style="font-weight: 600; font-size: 14px; margin-bottom: 4px; display: flex; align-items: center; gap: 8px;">
              <span>{{ log.action_name || (log.from_status + ' → ' + log.to_status) }}</span>
              <el-tag :type="getOperatorTypeBadge(log.operator_type).type" size="small" effect="plain">
                {{ getOperatorTypeBadge(log.operator_type).text }}: {{ log.operator || 'system' }}
              </el-tag>
            </div>
            <div style="color: #606266; font-size: 13px; margin-bottom: 4px;">
              {{ log.remark || '状态流转更新' }}
            </div>
            <div
              v-if="log.payload && Object.keys(log.payload).length > 0"
              style="background: #f8f9fa; padding: 6px 10px; border-radius: 4px; font-size: 12px; color: #555; margin-top: 4px; border: 1px dashed #dcdfe6;"
            >
              <div v-for="(v, k) in log.payload" :key="k" style="margin-bottom: 2px;">
                <span style="color: #909399;">{{ k }}:</span> {{ typeof v === 'object' ? JSON.stringify(v) : v }}
              </div>
            </div>
          </el-timeline-item>
        </el-timeline>
      </div>
    </el-drawer>

    <!-- 退款弹窗 -->
    <el-dialog
      v-model="showRefundDialog"
      :title="refundType === 'auto' ? '自动退款确认（未制作·释放库存）' : '强制退款确认（不退库存·客诉/失败）'"
      width="500px"
    >
      <el-alert
        v-if="refundType === 'auto'"
        type="success"
        :closable="false"
        show-icon
        style="margin-bottom: 16px;"
      >
        <template #title>未制作订单自动退款</template>
        确认后系统将<strong>自动释放并归还纸杯、耗材与物料库存</strong>，作废生产任务，并向微信发起全额原路退款。
      </el-alert>
      <el-alert
        v-else
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 16px;"
      >
        <template #title>客诉或制作失败强制退款</template>
        物料已实际消耗冲泡或损耗，确认后<strong>不会退回物料库存</strong>，作废未完成任务，直接向微信发起全额原路退款。
      </el-alert>

      <p style="margin-bottom: 12px; color: #606266;">
        确定为订单 <b>{{ refundOrderNo }}</b> 发起全额原路退款吗？
      </p>
      <el-input v-model="refundReason" placeholder="请输入退款原因说明" />
      <template #footer>
        <el-button @click="showRefundDialog = false">取消</el-button>
        <el-button
          :type="refundType === 'auto' ? 'warning' : 'danger'"
          :loading="refundLoading"
          @click="handleConfirmRefund"
        >
          {{ refundType === 'auto' ? '确认自动退款 (放库存)' : '确认强制退款 (不退库存)' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { getOrdersApi, getOrderDetailApi, refundOrderApi } from '@/api/orders'
import { formatCurrency } from '@/utils/money'

const loading = ref(false)
const orderList = ref<any[]>([])

const filters = reactive({
  order_no: '',
  status: '',
})

const showDrawer = ref(false)
const currentOrder = ref<any>(null)

const showRefundDialog = ref(false)
const refundLoading = ref(false)
const refundOrderNo = ref('')
const refundType = ref<'auto' | 'force'>('auto')
const refundReason = ref('')

async function fetchOrders() {
  loading.value = true
  try {
    const res = await getOrdersApi(filters)
    if (res.data) {
      orderList.value = res.data.results || []
    }
  } finally {
    loading.value = false
  }
}

async function openOrderDetail(orderNo: string) {
  try {
    const res = await getOrderDetailApi(orderNo)
    if (res.data) {
      currentOrder.value = res.data
      showDrawer.value = true
    }
  } catch (e) {
    //
  }
}

function openRefundDialog(row: any, type: 'auto' | 'force') {
  refundOrderNo.value = row.order_no
  refundType.value = type
  if (type === 'auto') {
    refundReason.value = '未制作自动退款放库'
  } else {
    refundReason.value = row.status === 'failed' ? '制作失败强制退款' : '客诉问题强制退款'
  }
  showRefundDialog.value = true
}

async function handleConfirmRefund() {
  refundLoading.value = true
  try {
    const res = await refundOrderApi(refundOrderNo.value, {
      refund_type: refundType.value,
      reason: refundReason.value
    })
    ElMessage.success(res.message || '退款指令已成功提交并处理')
    showRefundDialog.value = false
    fetchOrders()
  } catch (e) {
    //
  } finally {
    refundLoading.value = false
  }
}

function getTimelineType(log: any) {
  if (['failed', 'refund_failed'].includes(log.action) || log.to_status === 'failed') {
    return 'danger'
  }
  if (['refund_applied', 'refunding'].includes(log.action) || log.to_status === 'refunding') {
    return 'warning'
  }
  if (['refund_success', 'refunded'].includes(log.action) || log.to_status === 'refunded') {
    return 'info'
  }
  if (['making_done', 'success'].includes(log.action) || log.to_status === 'success') {
    return 'success'
  }
  return 'primary'
}

function getOperatorTypeBadge(type?: string) {
  switch (type) {
    case 'user': return { text: '顾客', type: 'info' }
    case 'device': return { text: '设备', type: 'warning' }
    case 'admin': return { text: '管理员', type: 'primary' }
    case 'wechat': return { text: '微信网关', type: 'success' }
    default: return { text: '系统', type: 'info' }
  }
}

onMounted(() => {
  fetchOrders()
})
</script>
