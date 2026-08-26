<template>
  <div class="page-container inventory-management-page">
    <PageHeader
      title="库存管理"
      subtitle="集中管理原材料/耗材仓储档案、库存余量、采购入库与门店分拨出库流水台账"
    >
      <template #actions>
        <el-button type="danger" plain icon="Bell" :loading="checkingExpiration" @click="handleManualExpirationCheck">
          保质期体检预警 (30天)
        </el-button>
        <el-button type="success" icon="Download" @click="openRecordDialog('in')">
          + 原料采购入库
        </el-button>
        <el-button type="warning" icon="Upload" @click="openRecordDialog('out')">
          - 门店物料出库
        </el-button>
        <el-button v-if="activeTab === 'materials'" type="primary" icon="Plus" @click="openCreateMaterialDialog">
          + 新建物料品类
        </el-button>
      </template>
    </PageHeader>

    <!-- 顶部 2 大平行选项卡 -->
    <el-tabs v-model="activeTab" type="border-card" class="inventory-tabs" @tab-change="handleTabChange">
      <!-- ============================================================ -->
      <!-- TAB 1: 物料仓库管理 (Materials) -->
      <!-- ============================================================ -->
      <el-tab-pane name="materials">
        <template #label>
          <div class="tab-label-box">
            <span class="tab-icon">📦</span>
            <span>物料仓库档案</span>
            <el-badge :value="materialTotalCount" type="primary" class="tab-badge" />
          </div>
        </template>

        <!-- 筛选表单 -->
        <el-form :inline="true" :model="materialFilters" size="default" style="margin-bottom: 14px;">
          <el-form-item label="物料编码/名称">
            <el-input v-model="materialFilters.search" placeholder="输入物料名称或编码" clearable />
          </el-form-item>
          <el-form-item label="物料类别">
            <el-select v-model="materialFilters.material_type" placeholder="全部类别" clearable style="width: 150px;">
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
            <el-button @click="resetMaterialFilters">重置</el-button>
          </el-form-item>
        </el-form>

        <!-- 物料库存大表 -->
        <el-table v-loading="loadingMaterials" :data="materialList" stripe style="width: 100%">
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
          <el-table-column prop="shelf_life" label="保质期" width="130">
            <template #default="{ row }">
              <el-tag v-if="!row.shelf_life_days && (!row.shelf_life || row.shelf_life === '永久有效')" type="info" size="small" effect="plain">
                永久有效
              </el-tag>
              <span v-else>{{ row.shelf_life }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="storage_conditions" label="储存条件" width="130">
            <template #default="{ row }">{{ row.storage_conditions || '-' }}</template>
          </el-table-column>
          <el-table-column prop="retrieve_count" label="出库分拨次数" width="120" align="center" />
          <el-table-column label="操作" width="220" fixed="right">
            <template #default="{ row }">
              <el-button type="success" link size="small" @click="openQuickAction(row, 'in')">
                入库
              </el-button>
              <el-button type="warning" link size="small" @click="openQuickAction(row, 'out')">
                出库
              </el-button>
              <el-button type="primary" link size="small" @click="openEditMaterialDialog(row)">
                编辑
              </el-button>
              <el-popconfirm title="确定删除该物料档案吗？" @confirm="handleDeleteMaterial(row.id)">
                <template #reference>
                  <el-button type="danger" link size="small">删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>

        <!-- 分页 -->
        <div style="margin-top: 16px; display: flex; justify-content: flex-end;">
          <el-pagination
            v-model:current-page="materialPage"
            v-model:page-size="materialPageSize"
            :total="materialTotalCount"
            :page-sizes="[10, 20, 50]"
            layout="total, sizes, prev, pager, next"
            @change="fetchMaterials"
          />
        </div>
      </el-tab-pane>

      <!-- ============================================================ -->
      <!-- TAB 2: 进出库流水记录 (Records) -->
      <!-- ============================================================ -->
      <el-tab-pane name="records">
        <template #label>
          <div class="tab-label-box">
            <span class="tab-icon">📋</span>
            <span>进出库流水记录</span>
            <el-badge :value="recordTotalCount" type="success" class="tab-badge" />
          </div>
        </template>

        <!-- 筛选表单 -->
        <el-form :inline="true" :model="recordFilters" size="default" style="margin-bottom: 14px;">
          <el-form-item label="记录类型">
            <el-select v-model="recordFilters.record_type" placeholder="全部类型" clearable style="width: 130px;">
              <el-option label="采购入库" value="in" />
              <el-option label="门店出库" value="out" />
            </el-select>
          </el-form-item>
          <el-form-item label="目标门店">
            <el-select v-model="recordFilters.store_id" placeholder="全部门店" clearable filterable style="width: 180px;">
              <el-option
                v-for="store in storeOptions"
                :key="store.id"
                :label="`${store.name} (ID: ${store.id})`"
                :value="store.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" icon="Search" @click="fetchRecords">查询</el-button>
            <el-button @click="resetRecordFilters">重置</el-button>
          </el-form-item>
        </el-form>

        <!-- 流水列表表格 -->
        <el-table v-loading="loadingRecords" :data="recordList" stripe style="width: 100%">
          <el-table-column prop="id" label="单号" width="80" align="center" />
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
              <span style="font-weight: 600;" :style="{ color: row.record_type === 'in' ? '#67C23A' : '#E6A23C' }">
                {{ row.record_type === 'in' ? '+' : '-' }}{{ row.quantity }}
              </span>
              {{ row.material_unit }}
            </template>
          </el-table-column>
          <el-table-column prop="price" label="单价(元)" width="100">
            <template #default="{ row }">
              {{ row.price ? `¥${Number(row.price).toFixed(2)}` : '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="store_name" label="出库目标门店" min-width="150">
            <template #default="{ row }">
              {{ row.store_name || '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="operator_username" label="经办操作员" width="120" />
          <el-table-column label="批次保质期 / 到期状态" width="190">
            <template #default="{ row }">
              <template v-if="row.expiration_date">
                <div style="display: flex; flex-direction: column; gap: 4px;">
                  <span style="font-size: 13px; font-weight: 500;">{{ row.expiration_date }}</span>
                  <div>
                    <el-tag v-if="row.expiration_status === 'expired'" type="danger" size="small" effect="dark">
                      🚨 已过期 ({{ Math.abs(row.days_until_expiration) }}天前)
                    </el-tag>
                    <el-tag v-else-if="row.expiration_status === 'expiring_soon'" type="warning" size="small" effect="dark">
                      ⚠️ 临期 (剩 {{ row.days_until_expiration }} 天)
                    </el-tag>
                    <el-tag v-else type="success" size="small" effect="plain">
                      正常 (剩 {{ row.days_until_expiration }} 天)
                    </el-tag>
                  </div>
                </div>
              </template>
              <template v-else>
                <el-tag type="info" size="small" effect="plain">永久有效</el-tag>
              </template>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="操作时间" width="170" />
          <el-table-column prop="remarks" label="备注" min-width="150" show-overflow-tooltip />
        </el-table>

        <!-- 分页 -->
        <div style="margin-top: 16px; display: flex; justify-content: flex-end;">
          <el-pagination
            v-model:current-page="recordPage"
            v-model:page-size="recordPageSize"
            :total="recordTotalCount"
            :page-sizes="[10, 20, 50]"
            layout="total, sizes, prev, pager, next"
            @change="fetchRecords"
          />
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- ============================================================ -->
    <!-- 对话框 1: 入库 / 出库对话框 -->
    <!-- ============================================================ -->
    <el-dialog
      v-model="showRecordDialog"
      :title="recordForm.record_type === 'in' ? '原材料采购入库' : '门店物料出库分拨'"
      width="540px"
    >
      <el-form :model="recordForm" label-width="110px">
        <el-form-item label="操作物料" required>
          <el-select
            v-model="recordForm.material_id"
            placeholder="请选择物料"
            filterable
            style="width: 100%;"
            @change="handleRecordMaterialChange"
          >
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
            placeholder="留空即为永久有效"
            value-format="YYYY-MM-DD"
            clearable
            style="width: 100%;"
          />
          <div v-if="selectedMaterialDurationText" style="font-size: 12px; color: #67C23A; margin-top: 4px;">
            💡 {{ selectedMaterialDurationText }}
          </div>
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

    <!-- ============================================================ -->
    <!-- 对话框 2: 新建 / 编辑物料品类对话框 -->
    <!-- ============================================================ -->
    <el-dialog
      v-model="showMaterialDialog"
      :title="isEditMaterial ? `编辑物料品类 (#${currentMaterialId})` : '新建物料品类'"
      width="560px"
    >
      <el-form :model="materialForm" label-width="110px">
        <el-form-item label="物料名称" required>
          <el-input v-model="materialForm.name" placeholder="例如 特级深烘咖啡豆" />
        </el-form-item>
        <el-form-item label="物料编码" required>
          <el-input v-model="materialForm.code" :disabled="isEditMaterial" placeholder="上位机匹配Code，如 coffee_bean" />
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
        <el-form-item v-if="!isEditMaterial" label="初始库存数量">
          <el-input-number v-model="materialForm.quantity" :min="0" :step="1" :precision="2" style="width: 100%;" />
        </el-form-item>
        <el-form-item label="保质期/到期日">
          <div style="display: flex; gap: 8px; width: 100%; align-items: center;">
            <el-date-picker
              v-model="materialForm.shelf_life"
              type="date"
              placeholder="留空即为永久有效 (如纸杯/耗材)"
              value-format="YYYY-MM-DD"
              clearable
              style="flex: 1;"
            />
            <el-button
              v-if="materialForm.shelf_life"
              type="info"
              link
              size="small"
              @click="materialForm.shelf_life = ''"
            >
              清空设为永久有效
            </el-button>
          </div>
          <div v-if="materialForm.shelf_life" style="font-size: 12px; color: #409EFF; margin-top: 4px;">
            💡 设定保质期时长：约 <b>{{ calculateDaysFromToday(materialForm.shelf_life) }} 天</b>。系统将继承此时长，后续每次入库将按【入库当天 + {{ calculateDaysFromToday(materialForm.shelf_life) }} 天】自动推算批次过期日。
          </div>
          <div v-else style="font-size: 12px; color: #909399; margin-top: 4px;">
            💡 当前未设定保质期（<b>永久有效</b>）：如纸杯、吸管、杯盖、打包袋等常规耗材，系统不会对其生成任何过期预警或报警。
          </div>
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
          {{ isEditMaterial ? '确认保存' : '创建物料' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Plus, Download, Upload, Search, Bell } from '@element-plus/icons-vue'
import { ElMessage, ElNotification } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import {
  getMaterialsApi,
  createMaterialApi,
  updateMaterialApi,
  deleteMaterialApi,
  getInventoryRecordsApi,
  createInventoryRecordApi,
  checkInventoryExpirationApi,
  getExpirationSummaryApi,
} from '@/api/inventory'
import { getStoresApi } from '@/api/stores'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

// 当前选项卡 (materials | records)
const activeTab = ref<string>('materials')

// -------------------------------------------------------------
// 1. 物料档案相关状态与数据
// -------------------------------------------------------------
const loadingMaterials = ref(false)
const materialList = ref<any[]>([])
const materialTotalCount = ref(0)
const materialPage = ref(1)
const materialPageSize = ref(10)

const materialFilters = reactive({
  search: '',
  material_type: '',
})

// -------------------------------------------------------------
// 2. 进出库流水相关状态与数据
// -------------------------------------------------------------
const loadingRecords = ref(false)
const recordList = ref<any[]>([])
const recordTotalCount = ref(0)
const recordPage = ref(1)
const recordPageSize = ref(10)

const recordFilters = reactive({
  record_type: '',
  store_id: undefined,
})

// 门店下拉列表
const storeOptions = ref<any[]>([])

// -------------------------------------------------------------
// 对话框表单状态与体检状态
// -------------------------------------------------------------
const submitLoading = ref(false)
const checkingExpiration = ref(false)

async function handleManualExpirationCheck() {
  checkingExpiration.value = true
  try {
    const res = await checkInventoryExpirationApi({ days: 30, force: true })
    if (res.data) {
      ElNotification({
        title: '物料保质期预警体检完成',
        message: `全库扫描 ${res.data.total_scanned_batches} 个批次，临期批次: ${res.data.expiring_soon_batches} 个，已过期: ${res.data.expired_batches} 个，本次生成平台告警并发送短信: ${res.data.alerted_batches} 条。`,
        type: res.data.expired_batches > 0 ? 'error' : res.data.expiring_soon_batches > 0 ? 'warning' : 'success',
        duration: 6000,
      })
      fetchRecords()
      fetchMaterials()
    }
  } finally {
    checkingExpiration.value = false
  }
}

const showRecordDialog = ref(false)
const recordForm = reactive({
  material_id: undefined as number | undefined,
  record_type: 'in' as 'in' | 'out',
  quantity: 10,
  price: 50,
  expiration_date: '',
  store_id: undefined as number | undefined,
  remarks: '',
})

const showMaterialDialog = ref(false)
const isEditMaterial = ref(false)
const currentMaterialId = ref<number | null>(null)
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

// -------------------------------------------------------------
// 选项卡切换与 URL 联动
// -------------------------------------------------------------
function handleTabChange(tabName: any) {
  router.replace({
    path: '/inventory',
    query: { tab: tabName },
  })
}

watch(
  () => route.query.tab,
  (newTab) => {
    if (newTab && typeof newTab === 'string') {
      activeTab.value = newTab
    }
  },
  { immediate: true }
)

// -------------------------------------------------------------
// 辅助函数
// -------------------------------------------------------------
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

// -------------------------------------------------------------
// 数据请求逻辑
// -------------------------------------------------------------
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
  loadingMaterials.value = true
  try {
    const params = {
      page: materialPage.value,
      page_size: materialPageSize.value,
      search: materialFilters.search,
      material_type: materialFilters.material_type,
    }
    const res = await getMaterialsApi(params)
    if (res.data) {
      materialList.value = res.data.results || []
      materialTotalCount.value = res.data.count || 0
    }
  } finally {
    loadingMaterials.value = false
  }
}

function resetMaterialFilters() {
  materialFilters.search = ''
  materialFilters.material_type = ''
  materialPage.value = 1
  fetchMaterials()
}

async function fetchRecords() {
  loadingRecords.value = true
  try {
    const params = {
      page: recordPage.value,
      page_size: recordPageSize.value,
      record_type: recordFilters.record_type,
      store_id: recordFilters.store_id,
    }
    const res = await getInventoryRecordsApi(params)
    if (res.data) {
      recordList.value = res.data.results || []
      recordTotalCount.value = res.data.count || 0
    }
  } finally {
    loadingRecords.value = false
  }
}

function resetRecordFilters() {
  recordFilters.record_type = ''
  recordFilters.store_id = undefined
  recordPage.value = 1
  fetchRecords()
}

function getDefaultExpirationDate(years = 1) {
  const d = new Date()
  d.setFullYear(d.getFullYear() + years)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function calculateDaysFromToday(dateStr: string) {
  if (!dateStr) return 365
  try {
    const target = new Date(dateStr.slice(0, 10))
    const now = new Date()
    now.setHours(0, 0, 0, 0)
    target.setHours(0, 0, 0, 0)
    const diff = Math.round((target.getTime() - now.getTime()) / (24 * 3600 * 1000))
    return Math.max(1, diff)
  } catch (e) {
    return 365
  }
}

const selectedMaterialDurationText = computed(() => {
  if (recordForm.record_type !== 'in' || !recordForm.material_id) return ''
  const mat = materialList.value.find(m => m.id === recordForm.material_id)
  if (!mat) return ''
  if (!mat.shelf_life_days && (!mat.shelf_life || mat.shelf_life === '永久有效')) {
    return '该物料品类为【永久有效（无保质期）】，入库无需填写过期时间'
  }
  const days = mat.shelf_life_days || calculateDaysFromToday(mat.shelf_life) || 180
  return `已按该品类保质期时长（${days} 天）自动基于当前入库日期推算`
})

function getMaterialCalculatedExpirationDate(mat: any) {
  if (!mat) return ''
  if (!mat.shelf_life_days && (!mat.shelf_life || mat.shelf_life === '永久有效')) {
    return ''
  }
  if (mat.default_expiration_date) {
    return mat.default_expiration_date
  }
  const days = mat.shelf_life_days || calculateDaysFromToday(mat.shelf_life)
  if (!days) return ''
  const d = new Date()
  d.setDate(d.getDate() + days)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function handleRecordMaterialChange(matId: any) {
  const mat = materialList.value.find(m => m.id === matId)
  if (mat) {
    recordForm.price = Number(mat.price) || 0
    if (recordForm.record_type === 'in') {
      recordForm.expiration_date = getMaterialCalculatedExpirationDate(mat)
    }
  }
}

// -------------------------------------------------------------
// 入库 / 出库操作
// -------------------------------------------------------------
function openRecordDialog(type: 'in' | 'out') {
  fetchStores()
  const firstMat = materialList.value[0]
  recordForm.record_type = type
  recordForm.material_id = firstMat?.id
  recordForm.quantity = 10
  recordForm.price = Number(firstMat?.price) || 50
  if (type === 'in') {
    recordForm.expiration_date = getMaterialCalculatedExpirationDate(firstMat)
  } else {
    recordForm.expiration_date = ''
  }
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
  if (type === 'in') {
    recordForm.expiration_date = getMaterialCalculatedExpirationDate(row)
  } else {
    recordForm.expiration_date = ''
  }
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
    ElMessage.success('操作成功！物料库存及流水记录已实时同步更新')
    showRecordDialog.value = false
    fetchMaterials()
    fetchRecords()
  } finally {
    submitLoading.value = false
  }
}

// -------------------------------------------------------------
// 物料档案新增 / 编辑 / 删除
// -------------------------------------------------------------
function openCreateMaterialDialog() {
  isEditMaterial.value = false
  currentMaterialId.value = null
  Object.assign(materialForm, {
    name: '',
    code: '',
    material_type: 'ingredient',
    price: 0,
    quantity: 0,
    unit: 'kg',
    shelf_life: getDefaultExpirationDate(1),
    storage_conditions: '常温避光',
    remarks: '',
  })
  showMaterialDialog.value = true
}

function openEditMaterialDialog(row: any) {
  isEditMaterial.value = true
  currentMaterialId.value = row.id
  Object.assign(materialForm, {
    name: row.name,
    code: row.code,
    material_type: row.material_type,
    price: Number(row.price) || 0,
    quantity: Number(row.quantity) || 0,
    unit: row.unit,
    shelf_life: row.shelf_life || '',
    storage_conditions: row.storage_conditions || '',
    remarks: row.remarks || '',
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
    if (isEditMaterial.value && currentMaterialId.value) {
      await updateMaterialApi(currentMaterialId.value, materialForm)
      ElMessage.success('物料档案已成功更新')
    } else {
      await createMaterialApi(materialForm)
      ElMessage.success('物料品类已成功创建')
    }
    showMaterialDialog.value = false
    fetchMaterials()
    fetchRecords()
  } finally {
    submitLoading.value = false
  }
}

async function handleDeleteMaterial(id: number) {
  try {
    await deleteMaterialApi(id)
    ElMessage.success('物料档案已删除')
    fetchMaterials()
  } catch (e) {
    // 错误拦截器统一处理
  }
}

// -------------------------------------------------------------
// 生命周期
// -------------------------------------------------------------
onMounted(() => {
  fetchMaterials()
  fetchRecords()
  fetchStores()
})
</script>

<style scoped>
.inventory-tabs {
  background: #ffffff;
  border-radius: 8px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.05);
  border: 1px solid #ebeef5;
}

.tab-label-box {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 500;
  padding: 4px 6px;
}

.tab-icon {
  font-size: 16px;
}

.tab-badge {
  margin-left: 4px;
}

:deep(.el-tabs__content) {
  padding: 20px 24px 28px;
}

:deep(.el-tabs__header) {
  background-color: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}

:deep(.el-tabs__item.is-active) {
  background-color: #ffffff !important;
  font-weight: 600;
  color: var(--el-color-primary);
}
</style>
