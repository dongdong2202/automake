<template>
  <div class="page-container record-list-page">
    <PageHeader
      title="物料进出库流水台账"
      subtitle="记录每笔原材料采购入库与门店分拨出库的经办人、数量、单价与批次流水"
    />

    <div class="chart-card">
      <el-form :inline="true" :model="filters" size="default">
        <el-form-item label="记录类型">
          <el-select v-model="filters.record_type" placeholder="全部类型" clearable style="width: 120px;">
            <el-option label="采购入库" value="in" />
            <el-option label="门店出库" value="out" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" icon="Search" @click="fetchRecords">查询</el-button>
        </el-form-item>
      </el-form>

      <el-table v-loading="loading" :data="recordList" stripe style="width: 100%">
        <el-table-column prop="id" label="单号" width="80" />
        <el-table-column prop="record_type" label="类型" width="110">
          <template #default="{ row }">
            <el-tag :type="row.record_type === 'in' ? 'success' : 'warning'" size="small">
              {{ row.record_type === 'in' ? '采购入库' : '门店出库' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="material_name" label="物料名称" min-width="160" />
        <el-table-column prop="quantity" label="变动数量" width="130">
          <template #default="{ row }">
            <span style="font-weight: 600;">
              {{ row.record_type === 'in' ? '+' : '-' }}{{ row.quantity }}
            </span>
            {{ row.material_unit }}
          </template>
        </el-table-column>
        <el-table-column prop="price" label="单价(元)" width="100">
          <template #default="{ row }">
            {{ row.price ? `¥${row.price}` : '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="store_name" label="出库目标门店" min-width="150">
          <template #default="{ row }">
            {{ row.store_name || '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="operator_username" label="经办操作员" width="120" />
        <el-table-column prop="created_at" label="操作时间" width="180" />
        <el-table-column prop="remarks" label="备注" min-width="160" />
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { Search } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import { getInventoryRecordsApi } from '@/api/inventory'

const loading = ref(false)
const recordList = ref<any[]>([])

const filters = reactive({
  record_type: '',
})

async function fetchRecords() {
  loading.value = true
  try {
    const res = await getInventoryRecordsApi(filters)
    if (res.data) {
      recordList.value = res.data.results || []
    }
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchRecords()
})
</script>
