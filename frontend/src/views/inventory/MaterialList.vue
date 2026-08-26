<template>
  <div class="page-container material-list-page">
    <PageHeader
      title="物料仓储与进销存管理"
      subtitle="管理原材料/耗材基本信息、标准计量单位、保质期、库存余量及出入库分拨台账"
    >
      <template #actions>
        <el-button type="success" icon="Download" @click="openRecordDialog('in')">
          + 原料采购入库
        </el-button>
        <el-button type="warning" icon="Upload" @click="openRecordDialog('out')">
          - 门店物料出库
        </el-button>
        <el-button type="primary" icon="Plus" @click="openCreateMaterialDialog">
          + 新建物料品类
        </el-button>
      </template>
    </PageHeader>

    <div class="chart-card">
      <el-form :inline="true" :model="filters" size="default">
        <el-form-item label="物料编码/名称">
          <el-input v-model="filters.search" placeholder="输入物料名称或编码" clearable />
        </el-form-item>
        <el-form-item label="物料类别">
          <el-select v-model="filters.material_type" placeholder="全部类别" clearable style="width: 150px;">
            <el-option label="食材 (ingredient)" value="ingredient" />
            <el-option label="耗材 (consumable)" value="consumable" />
            <el-option label="杯/耗材 (cup)" value="cup" />
            <el-option label="冰块 (ice)" value="ice" />
            <el-option label="稀液料 (thin)" value="thin" />
            <el-option label="稠液料 (thick)" value="thick" />
            <el-option label="固体料 (solid)" value="solid" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" icon="Search" @click="fetchMaterials">查询</el-button>
        </el-form-item>
      </el-form>

      <!-- 物料库存大表 -->
      <el-table v-loading="loading" :data="materialList" stripe style="width: 100%">
        <el-table-column prop="code" label="物料编码 (Code)" width="140">
          <template #default="{ row }">
            <span style="font-family: monospace; font-weight: 600;">{{ row.code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="物料名称" min-width="160" />
        <el-table-column prop="material_type" label="类别" width="130">
          <template #default="{ row }">
            <el-tag :type="getTypeTag(row.material_type)" size="small">
              {{ getTypeLabel(row.material_type) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="quantity" label="当前库存余量" width="140">
          <template #default="{ row }">
            <span
              :style="{
                fontWeight: 'bold',
                color: Number(row.quantity) < 10 ? '#F56C6C' : '#67C23A'
              }"
            >
              {{ row.quantity }} {{ row.unit }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="price" label="参考单价(元)" width="120">
          <template #default="{ row }">¥{{ Number(row.price).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column prop="shelf_life" label="保质期" width="110">
          <template #default="{ row }">{{ row.shelf_life || '-' }}</template>
        </el-table-column>
        <el-table-column prop="storage_conditions" label="储存条件" width="130">
          <template #default="{ row }">{{ row.storage_conditions || '-' }}</template>
        </el-table-column>
        <el-table-column prop="retrieve_count" label="出库分拨次数" width="120" align="center" />
        <el-table-column label="快捷操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button type="success" link size="small" @click="openQuickAction(row, 'in')">
              入库
            </el-button>
            <el-button type="warning" link size="small" @click="openQuickAction(row, 'out')">
              出库
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 入库 / 出库对话框 -->
    <el-dialog
      v-model="showRecordDialog"
      :title="recordForm.record_type === 'in' ? '原材料采购入库' : '门店物料出库分拨'"
      width="540px"
    >
      <el-form :model="recordForm" label-width="110px">
        <el-form-item label="操作物料" required>
          <el-select v-model="recordForm.material_id" placeholder="请选择物料" filterable style="width: 100%;">
            <el-option
              v-for="m in materialList"
              :key="m.id"
              :label="`${m.name} (${m.code}) - 存量: ${m.quantity}${m.unit}`"
              :value="m.id"
            />
          </el-select>
        </el-form-item>

        <el-form-item :label="recordForm.record_type === 'in' ? '入库数量' : '出库数量'" required>
          <el-input-number v-model="recordForm.quantity" :min="0.1" :step="1" :precision="2" style="width: 100%;" />
        </el-form-item>

        <el-form-item v-if="recordForm.record_type === 'in'" label="采购单价(元)">
          <el-input-number v-model="recordForm.price" :min="0" :step="1" :precision="2" style="width: 100%;" />
        </el-form-item>

        <el-form-item v-if="recordForm.record_type === 'in'" label="批次过期时间">
          <el-date-picker
            v-model="recordForm.expiration_date"
            type="date"
            placeholder="留空则按品类默认计算"
            value-format="YYYY-MM-DD"
            style="width: 100%;"
          />
        </el-form-item>

        <el-form-item v-if="recordForm.record_type === 'out'" label="接收门店" required>
          <el-select v-model="recordForm.store_id" placeholder="请选择目标门店" filterable style="width: 100%;">
            <el-option
              v-for="s in storeOptions"
              :key="s.id"
              :label="`${s.name} (ID: ${s.id})`"
              :value="s.id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="操作备注">
          <el-input v-model="recordForm.remarks" placeholder="如 8月批次常规采购 / 补充周末库存" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showRecordDialog = false">取消</el-button>
        <el-button type="primary" :loading="submitLoading" @click="handleRecordSubmit">
          确认提交
        </el-button>
      </template>
    </el-dialog>

    <!-- 录入新物料品类元数据对话框 -->
    <el-dialog v-model="showMaterialDialog" title="新建物料品类" width="560px">
      <el-form :model="materialForm" label-width="110px">
        <el-form-item label="物料名称" required>
          <el-input v-model="materialForm.name" placeholder="例如 特级深烘咖啡豆" />
        </el-form-item>
        <el-form-item label="物料编码" required>
          <el-input v-model="materialForm.code" placeholder="上位机匹配Code，如 coffee_bean" />
        </el-form-item>
        <el-form-item label="物料类别" required>
          <el-select v-model="materialForm.material_type" style="width: 100%;">
            <el-option label="食材 (ingredient)" value="ingredient" />
            <el-option label="耗材 (consumable)" value="consumable" />
            <el-option label="杯/耗材 (cup)" value="cup" />
            <el-option label="冰块 (ice)" value="ice" />
            <el-option label="稀液料 (thin)" value="thin" />
            <el-option label="稠液料 (thick)" value="thick" />
            <el-option label="固体料 (solid)" value="solid" />
          </el-select>
        </el-form-item>
        <el-form-item label="计量单位" required>
          <el-input v-model="materialForm.unit" placeholder="如 kg, 升, 个, 包, 箱" />
        </el-form-item>
        <el-form-item label="参考采购单价">
          <el-input-number v-model="materialForm.price" :min="0" :step="1" :precision="2" style="width: 100%;" />
        </el-form-item>
        <el-form-item label="初始库存数量">
          <el-input-number v-model="materialForm.quantity" :min="0" :step="1" :precision="2" style="width: 100%;" />
        </el-form-item>
        <el-form-item label="保质期">
          <el-input v-model="materialForm.shelf_life" placeholder="如 12个月, 30天" />
        </el-form-item>
        <el-form-item label="储存条件">
          <el-input v-model="materialForm.storage_conditions" placeholder="如 常温避光, 冷藏(2-8℃), 冷冻" />
        </el-form-item>
        <el-form-item label="物料备注">
          <el-input v-model="materialForm.remarks" type="textarea" :rows="2" placeholder="供应商说明或规格说明" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showMaterialDialog = false">取消</el-button>
        <el-button type="primary" :loading="submitLoading" @click="handleMaterialSubmit">
          创建物料
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { Plus, Download, Upload, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import { getMaterialsApi, createMaterialApi, createInventoryRecordApi } from '@/api/inventory'
import { getStoresApi } from '@/api/stores'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()

const loading = ref(false)
const submitLoading = ref(false)
const materialList = ref<any[]>([])
const storeOptions = ref<any[]>([])

const filters = reactive({
  search: '',
  material_type: '',
})

const showRecordDialog = ref(false)
const recordForm = reactive({
  material_id: undefined,
  record_type: 'in' as 'in' | 'out',
  quantity: 10,
  price: 50,
  expiration_date: '',
  store_id: undefined,
  remarks: '',
})

const showMaterialDialog = ref(false)
const materialForm = reactive({
  name: '',
  code: '',
  material_type: 'ingredient',
  price: 0,
  quantity: 0,
  unit: 'kg',
  shelf_life: '12个月',
  storage_conditions: '常温避光',
  remarks: '',
})

function getTypeLabel(type: string) {
  const map: Record<string, string> = {
    ingredient: '食材',
    consumable: '耗材',
    cup: '杯/耗材',
    ice: '冰块',
    thin: '稀液料',
    thick: '稠液料',
    solid: '固体料',
  }
  return map[type] || type
}

function getTypeTag(type: string) {
  const map: Record<string, string> = {
    ingredient: 'primary',
    consumable: 'warning',
    cup: 'info',
    ice: 'cyan' as any,
    thin: 'success',
    thick: 'danger',
    solid: 'primary',
  }
  return map[type] || 'info'
}

async function fetchStores() {
  try {
    const res = await getStoresApi({ page_size: 200 })
    if (res.data) {
      storeOptions.value = res.data.results || []
    }
  } catch (e) {
    //
  }
}

async function fetchMaterials() {
  loading.value = true
  try {
    const res = await getMaterialsApi(filters)
    if (res.data) {
      materialList.value = res.data.results || []
    }
  } finally {
    loading.value = false
  }
}

function openRecordDialog(type: 'in' | 'out') {
  fetchStores()
  recordForm.record_type = type
  recordForm.material_id = materialList.value[0]?.id
  recordForm.quantity = 10
  recordForm.price = 50
  recordForm.expiration_date = ''
  recordForm.store_id = storeOptions.value[0]?.id || (authStore.user?.stores[0]?.id as any)
  recordForm.remarks = ''
  showRecordDialog.value = true
}

function openQuickAction(row: any, type: 'in' | 'out') {
  fetchStores()
  recordForm.record_type = type
  recordForm.material_id = row.id
  recordForm.quantity = 10
  recordForm.price = Number(row.price) || 50
  recordForm.expiration_date = ''
  recordForm.store_id = storeOptions.value[0]?.id || (authStore.user?.stores[0]?.id as any)
  recordForm.remarks = ''
  showRecordDialog.value = true
}

async function handleRecordSubmit() {
  if (!recordForm.material_id || !recordForm.quantity) {
    ElMessage.warning('请选择物料并填写数量')
    return
  }

  if (recordForm.record_type === 'out' && !recordForm.store_id) {
    ElMessage.warning('出库必须选择目标门店')
    return
  }

  submitLoading.value = true
  try {
    await createInventoryRecordApi(recordForm as any)
    ElMessage.success('操作成功！物料库存已实时同步更新')
    showRecordDialog.value = false
    fetchMaterials()
  } finally {
    submitLoading.value = false
  }
}

function openCreateMaterialDialog() {
  Object.assign(materialForm, {
    name: '',
    code: '',
    material_type: 'ingredient',
    price: 0,
    quantity: 0,
    unit: 'kg',
    shelf_life: '12个月',
    storage_conditions: '常温避光',
    remarks: '',
  })
  showMaterialDialog.value = true
}

async function handleMaterialSubmit() {
  if (!materialForm.name || !materialForm.code || !materialForm.unit) {
    ElMessage.warning('物料名称、编号和单位为必填项')
    return
  }

  submitLoading.value = true
  try {
    await createMaterialApi(materialForm)
    ElMessage.success('物料品类已创建')
    showMaterialDialog.value = false
    fetchMaterials()
  } finally {
    submitLoading.value = false
  }
}

onMounted(() => {
  fetchMaterials()
  fetchStores()
})
</script>
