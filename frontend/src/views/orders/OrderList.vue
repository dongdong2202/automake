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
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="openOrderDetail(row.order_no)">
              明细
            </el-button>
            <el-button
              v-if="row.status === 'pending_dispense' || row.status === 'success' || row.status === 'failed'"
              type="danger"
              link
              size="small"
              @click="openRefundDialog(row)"
            >
              申请退款
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
        <el-timeline>
          <el-timeline-item
            v-for="(log, idx) in currentOrder.status_logs || []"
            :key="idx"
            :timestamp="log.created_at"
            type="primary"
          >
            {{ log.from_status }} → {{ log.to_status }} ({{ log.remark || log.operator }})
          </el-timeline-item>
        </el-timeline>
      </div>
    </el-drawer>

    <!-- 退款弹窗 -->
    <el-dialog v-model="showRefundDialog" title="管理员人工退款" width="460px">
      <p style="margin-bottom: 12px; color: #606266;">
        确定为订单 <b>{{ refundOrderNo }}</b> 发起全额原路退款吗？
      </p>
      <el-input v-model="refundReason" placeholder="请输入退款原因说明" />
      <template #footer>
        <el-button @click="showRefundDialog = false">取消</el-button>
        <el-button type="danger" :loading="refundLoading" @click="handleConfirmRefund">
          确认退款
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
const refundReason = ref('管理员人工后台退款')

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

function openRefundDialog(row: any) {
  refundOrderNo.value = row.order_no
  refundReason.value = '管理员人工后台退款'
  showRefundDialog.value = true
}

async function handleConfirmRefund() {
  refundLoading.value = true
  try {
    await refundOrderApi(refundOrderNo.value, { reason: refundReason.value })
    ElMessage.success('退款指令已成功提交并处理')
    showRefundDialog.value = false
    fetchOrders()
  } catch (e) {
    //
  } finally {
    refundLoading.value = false
  }
}

onMounted(() => {
  fetchOrders()
})
</script>
