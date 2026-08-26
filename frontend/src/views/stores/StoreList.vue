<template>
  <div class="page-container store-management-page">
    <PageHeader
      title="门店管理"
      subtitle="集中维护全国各营业门店、营业时间规则、各门店自身物料库存、出库加料到设备及门店调拨流水台账"
    >
      <template #actions>
        <el-button v-if="activeTab === 'stores'" type="primary" icon="Plus" @click="openCreateDialog">
          + 新增门店
        </el-button>
        <el-button v-else-if="activeTab === 'inventory'" type="primary" icon="Upload" @click="openDispatchDialog">
          + 物料出库到设备
        </el-button>
        <el-button v-else-if="activeTab === 'records'" type="default" icon="Refresh" @click="fetchStoreRecords">
          刷新调拨台账
        </el-button>
      </template>
    </PageHeader>

    <!-- 顶部 3 大平行选项卡 -->
    <el-tabs v-model="activeTab" type="border-card" class="store-tabs" @tab-change="handleTabChange">
      <!-- ============================================================ -->
      <!-- TAB 1: 门店档案管理 (Store List & CRUD) -->
      <!-- ============================================================ -->
      <el-tab-pane name="stores">
        <template #label>
          <div class="tab-label-box">
            <span class="tab-icon">🏬</span>
            <span>门店档案管理</span>
            <el-badge :value="storeTotalCount" type="primary" class="tab-badge" />
          </div>
        </template>

        <!-- 筛选与表格 -->
        <el-form :inline="true" :model="filters" size="default" style="margin-bottom: 14px;">
          <el-form-item label="门店名称">
            <el-input v-model="filters.search" placeholder="输入门店名称搜索" clearable />
          </el-form-item>
          <el-form-item label="运营状态">
            <el-select v-model="filters.status" placeholder="全部状态" clearable style="width: 130px;">
              <el-option label="营业中" value="open" />
              <el-option label="已打烊" value="closed" />
              <el-option label="暂停营业" value="paused" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" icon="Search" @click="fetchStores">查询</el-button>
            <el-button @click="resetFilters">重置</el-button>
          </el-form-item>
        </el-form>

        <el-table v-loading="loading" :data="storeList" stripe style="width: 100%">
          <el-table-column prop="id" label="门店ID" width="95" align="center">
            <template #default="{ row }">
              <span style="font-family: monospace; font-weight: 600;">{{ row.id }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="门店名称" min-width="160" />
          <el-table-column prop="address" label="详细地址" min-width="220" show-overflow-tooltip />
          <el-table-column prop="contact_phone" label="联系电话" width="140" />
          <el-table-column label="营业时间" min-width="160">
            <template #default="{ row }">
              <span style="font-size: 13px;">{{ formatBusinessHours(row.business_hours) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="status" label="运营状态" width="110" align="center">
            <template #default="{ row }">
              <StatusBadge :status="row.status" />
            </template>
          </el-table-column>
          <el-table-column prop="device_count" label="绑定设备" width="100" align="center">
            <template #default="{ row }">
              <el-tag size="small" type="primary">{{ row.device_count || 0 }} 台</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="220" fixed="right">
            <template #default="{ row }">
              <el-button type="success" link size="small" @click="switchStoreTab(row.id)">
                查看库存
              </el-button>
              <el-button type="primary" link size="small" @click="openEditDialog(row)">
                编辑
              </el-button>
              <el-popconfirm title="确定删除该门店吗？" @confirm="handleDelete(row.id)">
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
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :total="storeTotalCount"
            :page-sizes="[10, 20, 50]"
            layout="total, sizes, prev, pager, next"
            @change="fetchStores"
          />
        </div>
      </el-tab-pane>

      <!-- ============================================================ -->
      <!-- TAB 2: 门店库存管理 (Store Specific Inventory) -->
      <!-- ============================================================ -->
      <el-tab-pane name="inventory">
        <template #label>
          <div class="tab-label-box">
            <span class="tab-icon">📦</span>
            <span>门店库存管理</span>
            <el-badge :value="storeInventoryTotalCount" type="success" class="tab-badge" />
          </div>
        </template>

        <!-- 顶部门店选择器与筛选 -->
        <el-form :inline="true" :model="invFilters" size="default" style="margin-bottom: 14px;">
          <el-form-item label="选择门店" required>
            <el-select
              v-model="selectedStoreId"
              placeholder="请选择门店"
              filterable
              style="width: 220px;"
              @change="onStoreChange"
            >
              <el-option
                v-for="s in storeOptions"
                :key="s.id"
                :label="`${s.name} (ID: ${s.id})`"
                :value="s.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="物料名称/编码">
            <el-input v-model="invFilters.search" placeholder="输入物料名称或Code" clearable />
          </el-form-item>
          <el-form-item label="物料类别">
            <el-select v-model="invFilters.material_type" placeholder="全部类别" clearable style="width: 140px;">
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
            <el-button type="primary" icon="Search" @click="fetchStoreInventory">查询库存</el-button>
            <el-button @click="resetInvFilters">重置</el-button>
          </el-form-item>
        </el-form>

        <!-- 门店库存大表 -->
        <el-table v-loading="loadingInventory" :data="storeInventoryList" stripe style="width: 100%">
          <el-table-column prop="material_code" label="物料编号" width="140">
            <template #default="{ row }">
              <span style="font-family: monospace; font-weight: 600;">{{ row.material_code }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="material_name" label="物料名称" min-width="160" />
          <el-table-column prop="material_type" label="物料类别" width="130">
            <template #default="{ row }">
              <el-tag size="small" :type="getTypeTagType(row.material_type)">
                {{ formatMaterialType(row.material_type) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="quantity" label="当前在店库存" width="150">
            <template #default="{ row }">
              <span
                style="font-size: 15px; font-weight: bold;"
                :style="{
                  color: Number(row.quantity) <= 5 ? '#F56C6C' : Number(row.quantity) <= 20 ? '#E6A23C' : '#67C23A'
                }"
              >
                {{ row.quantity }} {{ row.unit }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="material_price" label="参考进价(元)" width="120">
            <template #default="{ row }">
              ¥{{ Number(row.material_price || 0).toFixed(2) }}
            </template>
          </el-table-column>
          <el-table-column prop="shelf_life" label="保质期/时长" width="130">
            <template #default="{ row }">
              <el-tag v-if="!row.shelf_life_days && (!row.shelf_life || row.shelf_life === '永久有效')" type="info" size="small" effect="plain">
                永久有效
              </el-tag>
              <span v-else>{{ row.shelf_life }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="storage_conditions" label="储存条件" width="140">
            <template #default="{ row }">{{ row.storage_conditions || '常温' }}</template>
          </el-table-column>
          <el-table-column prop="updated_at" label="最后入库/变动时间" width="170" />
          <el-table-column label="操作" width="140" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link size="small" @click="openQuickDispatch(row)">
                出库到设备
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <!-- 分页 -->
        <div style="margin-top: 16px; display: flex; justify-content: flex-end;">
          <el-pagination
            v-model:current-page="invPage"
            v-model:page-size="invPageSize"
            :total="storeInventoryTotalCount"
            :page-sizes="[10, 20, 50]"
            layout="total, sizes, prev, pager, next"
            @change="fetchStoreInventory"
          />
        </div>
      </el-tab-pane>

      <!-- ============================================================ -->
      <!-- TAB 3: 门店调拨流水台账 (Store In/Out Records) -->
      <!-- ============================================================ -->
      <el-tab-pane name="records">
        <template #label>
          <div class="tab-label-box">
            <span class="tab-icon">📋</span>
            <span>门店调拨流水</span>
            <el-badge :value="storeRecordsTotalCount" type="info" class="tab-badge" />
          </div>
        </template>

        <!-- 筛选表单 -->
        <el-form :inline="true" :model="recordFilters" size="default" style="margin-bottom: 14px;">
          <el-form-item label="所属门店">
            <el-select
              v-model="recordStoreId"
              placeholder="全部门店"
              clearable
              filterable
              style="width: 220px;"
              @change="fetchStoreRecords"
            >
              <el-option
                v-for="s in storeOptions"
                :key="s.id"
                :label="`${s.name} (ID: ${s.id})`"
                :value="s.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="流转类型">
            <el-select v-model="recordFilters.record_type" placeholder="全部类型" clearable style="width: 160px;">
              <el-option label="总仓分拨入店" value="in_from_warehouse" />
              <el-option label="出库加料到设备" value="out_to_device" />
            </el-select>
          </el-form-item>
          <el-form-item label="关键字搜索">
            <el-input v-model="recordFilters.search" placeholder="搜索物料/设备/备注" clearable />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" icon="Search" @click="fetchStoreRecords">查询流水</el-button>
            <el-button @click="resetRecordFilters">重置</el-button>
          </el-form-item>
        </el-form>

        <!-- 流水表格 -->
        <el-table v-loading="loadingRecords" :data="storeRecordsList" stripe style="width: 100%">
          <el-table-column prop="id" label="流水ID" width="90" align="center" />
          <el-table-column prop="store_name" label="所属门店" min-width="150">
            <template #default="{ row }">
              <span style="font-weight: 500;">{{ row.store_name || `门店 #${row.store}` }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="record_type" label="流转类型" width="140">
            <template #default="{ row }">
              <el-tag
                v-if="row.record_type === 'in_from_warehouse'"
                type="success"
                effect="dark"
                size="small"
              >
                📥 总仓分拨入店
              </el-tag>
              <el-tag
                v-else
                type="primary"
                effect="dark"
                size="small"
              >
                📤 出库加料到设备
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="material_name" label="物料名称" min-width="150" />
          <el-table-column prop="material_code" label="物料编号" width="130">
            <template #default="{ row }">
              <span style="font-family: monospace;">{{ row.material_code }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="quantity" label="流转数量" width="120">
            <template #default="{ row }">
              <span style="font-weight: 600;">
                {{ row.record_type === 'in_from_warehouse' ? '+' : '-' }}{{ row.quantity }} {{ row.material_unit }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="device_name" label="目标设备" width="160">
            <template #default="{ row }">
              <div v-if="row.device_sn" style="display: flex; flex-direction: column;">
                <span style="font-weight: 500;">{{ row.device_name || row.device_sn }}</span>
                <span style="font-size: 11px; color: #909399; font-family: monospace;">{{ row.device_sn }}</span>
              </div>
              <span v-else style="color: #c0c4cc;">-</span>
            </template>
          </el-table-column>
          <el-table-column prop="operator_username" label="经办操作员" width="120">
            <template #default="{ row }">{{ row.operator_username || '系统自动' }}</template>
          </el-table-column>
          <el-table-column prop="created_at" label="发生时间" width="170" />
          <el-table-column prop="remarks" label="备注说明" min-width="170" show-overflow-tooltip />
        </el-table>

        <!-- 分页 -->
        <div style="margin-top: 16px; display: flex; justify-content: flex-end;">
          <el-pagination
            v-model:current-page="recordPage"
            v-model:page-size="recordPageSize"
            :total="storeRecordsTotalCount"
            :page-sizes="[10, 20, 50]"
            layout="total, sizes, prev, pager, next"
            @change="fetchStoreRecords"
          />
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- ============================================================ -->
    <!-- 对话框 1: 门店新增 / 编辑对话框 -->
    <!-- ============================================================ -->
    <el-dialog
      v-model="showDialog"
      :title="isEdit ? `编辑门店信息 (ID: ${currentId})` : '新增门店'"
      width="680px"
      top="5vh"
    >
      <el-form :model="formData" label-width="110px">
        <el-row :gutter="16">
          <el-col :span="14">
            <el-form-item label="门店名称" required>
              <el-input v-model="formData.name" placeholder="例如 北京朝阳大悦城店" />
            </el-form-item>
          </el-col>
          <el-col :span="10">
            <el-form-item label="运营状态" required>
              <el-select v-model="formData.status" style="width: 100%;">
                <el-option label="营业中 (open)" value="open" />
                <el-option label="暂停营业 (paused)" value="paused" />
                <el-option label="已关闭 (closed)" value="closed" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="联系电话">
              <el-input v-model="formData.contact_phone" placeholder="例如 010-88886666" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="详细地址">
              <el-input v-model="formData.address" placeholder="例如 朝阳区青年路大悦城 B1 层" />
            </el-form-item>
          </el-col>
        </el-row>

        <!-- 营业时间规则 -->
        <el-divider content-position="left">营业时间配置 (按星期排班)</el-divider>
        <div style="margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between;">
          <span style="font-size: 13px; color: #606266;">各星期的营业时段（留空表示该日全天营业或已休息）：</span>
          <el-button size="small" type="primary" link @click="applyDefaultHours">一键应用默认时间 (08:00-22:00)</el-button>
        </div>

        <el-row :gutter="12">
          <el-col v-for="day in weekDays" :key="day.key" :span="12" style="margin-bottom: 8px;">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="width: 50px; font-size: 13px; font-weight: 500;">{{ day.label }}:</span>
              <el-input v-model="businessHoursForm[day.key]" placeholder="如 08:00-22:00" size="small" clearable />
            </div>
          </el-col>
        </el-row>

        <el-form-item label="门店描述" style="margin-top: 12px;">
          <el-input v-model="formData.description" type="textarea" :rows="2" placeholder="门店特色或备注说明" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" :loading="submitLoading" @click="handleSubmit">
          {{ isEdit ? '确认保存' : '创建门店' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- ============================================================ -->
    <!-- 对话框 2: 门店物料出库加料到设备对话框 -->
    <!-- ============================================================ -->
    <el-dialog
      v-model="showDispatchDialog"
      title="物料出库加料到设备"
      width="540px"
    >
      <el-form :model="dispatchForm" label-width="110px">
        <el-form-item label="出库门店">
          <el-tag size="default" type="primary">{{ currentStoreName }}</el-tag>
        </el-form-item>

        <el-form-item label="目标加料设备" required>
          <el-select v-model="dispatchForm.device_sn" placeholder="请选择门店所属目标设备" style="width: 100%;">
            <el-option
              v-for="d in storeDeviceOptions"
              :key="d.device_sn"
              :label="`${d.device_name || d.device_sn} (${d.device_sn})`"
              :value="d.device_sn"
            />
          </el-select>
          <div v-if="storeDeviceOptions.length === 0" style="font-size: 12px; color: #F56C6C; margin-top: 4px;">
            ⚠️ 当前门店下未绑定任何设备，请先在设备管理中为该门店分配设备。
          </div>
        </el-form-item>

        <el-form-item label="选择在店物料" required>
          <el-select
            v-model="dispatchForm.material_id"
            placeholder="请选择在店物料"
            filterable
            style="width: 100%;"
            @change="handleDispatchMaterialChange"
          >
            <el-option
              v-for="m in storeInventoryList"
              :key="m.material"
              :label="`${m.material_name} (剩余在店: ${m.quantity} ${m.unit})`"
              :value="m.material"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="出库加料数量" required>
          <el-input-number
            v-model="dispatchForm.quantity"
            :min="0.1"
            :max="maxDispatchQuantity"
            :step="1"
            :precision="2"
            style="width: 100%;"
          />
          <div style="font-size: 12px; color: #909399; margin-top: 4px;">
            💡 当前最大可出库量：<b>{{ maxDispatchQuantity }}</b>（加料后系统将自动扣减门店库存，设备端液位由传感器实时检测读取）
          </div>
        </el-form-item>

        <el-form-item label="加料操作备注">
          <el-input v-model="dispatchForm.remarks" placeholder="如 上午常规补料 / 补充周末豆料" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showDispatchDialog = false">取消</el-button>
        <el-button type="primary" :loading="dispatchLoading" @click="handleDispatchSubmit">
          确认出库加料
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Plus, Search, Upload, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useAuthStore } from '@/stores/auth'
import {
  getStoresApi,
  createStoreApi,
  updateStoreApi,
  deleteStoreApi,
  getStoreInventoryApi,
  dispatchStoreInventoryToDeviceApi,
  getStoreInventoryRecordsApi
} from '@/api/stores'
import { getDevicesApi } from '@/api/devices'
import type { StoreItem } from '@/types'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

// 3 大平行选项卡
const activeTab = ref<'stores' | 'inventory' | 'records'>('stores')

// -------------------------------------------------------------
// TAB 1: 门店档案管理
// -------------------------------------------------------------
const loading = ref(false)
const storeList = ref<StoreItem[]>([])
const storeOptions = ref<StoreItem[]>([])
const storeTotalCount = ref(0)
const page = ref(1)
const pageSize = ref(20)

const filters = reactive({
  search: '',
  status: '',
})

const weekDays = [
  { key: 'mon', label: '周一' },
  { key: 'tue', label: '周二' },
  { key: 'wed', label: '周三' },
  { key: 'thu', label: '周四' },
  { key: 'fri', label: '周五' },
  { key: 'sat', label: '周六' },
  { key: 'sun', label: '周日' },
]

const showDialog = ref(false)
const isEdit = ref(false)
const currentId = ref<number | null>(null)
const submitLoading = ref(false)

const formData = reactive({
  name: '',
  description: '',
  address: '',
  lat: null as number | null,
  lng: null as number | null,
  contact_phone: '',
  code: '',
  status: 'open',
})

const businessHoursForm = reactive<Record<string, string>>({
  mon: '', tue: '', wed: '', thu: '', fri: '', sat: '', sun: '',
})

// -------------------------------------------------------------
// TAB 2: 门店库存管理
// -------------------------------------------------------------
const selectedStoreId = ref<number | undefined>(undefined)
const loadingInventory = ref(false)
const storeInventoryList = ref<any[]>([])
const storeInventoryTotalCount = ref(0)
const invPage = ref(1)
const invPageSize = ref(20)

const invFilters = reactive({
  search: '',
  material_type: '',
})

// 出库到设备弹窗
const showDispatchDialog = ref(false)
const dispatchLoading = ref(false)
const storeDeviceOptions = ref<any[]>([])

const dispatchForm = reactive({
  device_sn: '',
  material_id: undefined as number | undefined,
  quantity: 1,
  remarks: '',
})

const currentStoreName = computed(() => {
  const s = storeOptions.value.find(item => item.id === selectedStoreId.value)
  return s ? s.name : `门店 #${selectedStoreId.value}`
})

const maxDispatchQuantity = computed(() => {
  if (!dispatchForm.material_id) return 100
  const mat = storeInventoryList.value.find(item => item.material === dispatchForm.material_id)
  return mat ? Number(mat.quantity) : 100
})

// -------------------------------------------------------------
// TAB 3: 门店调拨流水
// -------------------------------------------------------------
const recordStoreId = ref<number | undefined>(undefined)
const loadingRecords = ref(false)
const storeRecordsList = ref<any[]>([])
const storeRecordsTotalCount = ref(0)
const recordPage = ref(1)
const recordPageSize = ref(20)

const recordFilters = reactive({
  record_type: '',
  search: '',
})

// -------------------------------------------------------------
// 生命周期与 URL 联动
// -------------------------------------------------------------
onMounted(async () => {
  const qTab = route.query.tab as string
  if (['stores', 'inventory', 'records'].includes(qTab)) {
    activeTab.value = qTab as any
  }
  await fetchStores()

  if (storeOptions.value.length > 0) {
    selectedStoreId.value = storeOptions.value[0].id
    if (activeTab.value === 'inventory') {
      fetchStoreInventory()
      fetchStoreDevices(selectedStoreId.value)
    }
  }

  if (activeTab.value === 'records') {
    fetchStoreRecords()
  }
})

function handleTabChange(tab: any) {
  router.replace({ query: { ...route.query, tab } })
  if (tab === 'inventory') {
    if (!selectedStoreId.value && storeOptions.value.length > 0) {
      selectedStoreId.value = storeOptions.value[0].id
    }
    if (selectedStoreId.value) {
      fetchStoreInventory()
      fetchStoreDevices(selectedStoreId.value)
    }
  } else if (tab === 'records') {
    fetchStoreRecords()
  }
}

function switchStoreTab(storeId: number) {
  selectedStoreId.value = storeId
  recordStoreId.value = storeId
  activeTab.value = 'inventory'
  router.replace({ query: { ...route.query, tab: 'inventory' } })
  fetchStoreInventory()
  fetchStoreDevices(storeId)
}

// -------------------------------------------------------------
// 门店档案 CRUD
// -------------------------------------------------------------
async function fetchStores() {
  loading.value = true
  try {
    const res = await getStoresApi({
      page: page.value,
      page_size: pageSize.value,
      search: filters.search,
      status: filters.status,
    })
    storeList.value = res.data.results || []
    storeTotalCount.value = res.data.count || 0
    storeOptions.value = res.data.results || []
  } catch (err: any) {
    ElMessage.error(err.message || '获取门店列表失败')
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  filters.search = ''
  filters.status = ''
  page.value = 1
  fetchStores()
}

function formatBusinessHours(bh: any) {
  if (!bh || Object.keys(bh).length === 0) return '全天营业'
  const keys = Object.keys(bh)
  return `${keys.length} 天已排班 (${bh[keys[0]] || ''})`
}

function applyDefaultHours() {
  weekDays.forEach(d => {
    businessHoursForm[d.key] = '08:00-22:00'
  })
}

function openCreateDialog() {
  isEdit.value = false
  currentId.value = null
  formData.name = ''
  formData.description = ''
  formData.address = ''
  formData.lat = null
  formData.lng = null
  formData.contact_phone = ''
  formData.code = ''
  formData.status = 'open'
  weekDays.forEach(d => { businessHoursForm[d.key] = '' })
  showDialog.value = true
}

function openEditDialog(row: StoreItem) {
  isEdit.value = true
  currentId.value = row.id
  formData.name = row.name
  formData.description = row.description || ''
  formData.address = row.address || ''
  formData.lat = row.lat ? Number(row.lat) : null
  formData.lng = row.lng ? Number(row.lng) : null
  formData.contact_phone = row.contact_phone || ''
  formData.code = row.code || ''
  formData.status = row.status
  weekDays.forEach(d => {
    businessHoursForm[d.key] = (row.business_hours && row.business_hours[d.key]) || ''
  })
  showDialog.value = true
}

async function handleSubmit() {
  if (!formData.name.trim()) {
    ElMessage.warning('门店名称为必填项')
    return
  }

  submitLoading.value = true
  try {
    const payload = {
      ...formData,
      business_hours: { ...businessHoursForm }
    }
    if (isEdit.value && currentId.value) {
      await updateStoreApi(currentId.value, payload)
      ElMessage.success('门店信息更新成功')
    } else {
      await createStoreApi(payload)
      ElMessage.success('门店创建成功')
    }
    showDialog.value = false
    fetchStores()
  } catch (err: any) {
    ElMessage.error(err.message || '操作失败')
  } finally {
    submitLoading.value = false
  }
}

async function handleDelete(id: number) {
  try {
    await deleteStoreApi(id)
    ElMessage.success('门店删除成功')
    fetchStores()
  } catch (err: any) {
    ElMessage.error(err.message || '删除失败')
  }
}

// -------------------------------------------------------------
// 门店库存管理逻辑
// -------------------------------------------------------------
function onStoreChange(storeId: number) {
  selectedStoreId.value = storeId
  invPage.value = 1
  fetchStoreInventory()
  fetchStoreDevices(storeId)
}

async function fetchStoreInventory() {
  if (!selectedStoreId.value) return
  loadingInventory.value = true
  try {
    const res = await getStoreInventoryApi(selectedStoreId.value, {
      page: invPage.value,
      page_size: invPageSize.value,
      search: invFilters.search,
      material_type: invFilters.material_type,
    })
    storeInventoryList.value = res.data.results || []
    storeInventoryTotalCount.value = res.data.count || 0
  } catch (err: any) {
    ElMessage.error(err.message || '获取门店库存失败')
  } finally {
    loadingInventory.value = false
  }
}

function resetInvFilters() {
  invFilters.search = ''
  invFilters.material_type = ''
  invPage.value = 1
  fetchStoreInventory()
}

async function fetchStoreDevices(storeId: number) {
  try {
    const res = await getDevicesApi({ store_id: storeId, page_size: 100 })
    storeDeviceOptions.value = res.data.results || []
  } catch (e) {
    storeDeviceOptions.value = []
  }
}

function formatMaterialType(type: string) {
  const map: Record<string, string> = {
    ingredient: '食材 (ingredient)',
    consumable: '耗材 (consumable)',
    cup: '杯/耗材 (cup)',
    ice: '冰块 (ice)',
    thin: '稀液料 (thin)',
    thick: '稠液料 (thick)',
    solid: '固体料 (solid)',
  }
  return map[type] || type || '通用物料'
}

function getTypeTagType(type: string) {
  const map: Record<string, any> = {
    ingredient: 'success',
    cup: 'warning',
    consumable: 'info',
    ice: 'primary',
    thin: 'primary',
    thick: 'warning',
    solid: 'danger',
  }
  return map[type] || 'info'
}

function openDispatchDialog() {
  if (!selectedStoreId.value) {
    ElMessage.warning('请先选择门店')
    return
  }
  fetchStoreDevices(selectedStoreId.value)
  const firstMat = storeInventoryList.value[0]
  dispatchForm.device_sn = storeDeviceOptions.value[0]?.device_sn || ''
  dispatchForm.material_id = firstMat?.material
  dispatchForm.quantity = 1
  dispatchForm.remarks = ''
  showDispatchDialog.value = true
}

function openQuickDispatch(row: any) {
  if (!selectedStoreId.value) return
  fetchStoreDevices(selectedStoreId.value)
  dispatchForm.device_sn = storeDeviceOptions.value[0]?.device_sn || ''
  dispatchForm.material_id = row.material
  dispatchForm.quantity = Math.min(Number(row.quantity), 1)
  dispatchForm.remarks = ''
  showDispatchDialog.value = true
}

function handleDispatchMaterialChange(matId: any) {
  const mat = storeInventoryList.value.find(item => item.material === matId)
  if (mat) {
    dispatchForm.quantity = Math.min(Number(mat.quantity), 1)
  }
}

async function handleDispatchSubmit() {
  if (!selectedStoreId.value || !dispatchForm.device_sn || !dispatchForm.material_id || !dispatchForm.quantity) {
    ElMessage.warning('请选择目标设备、物料并填写加料数量')
    return
  }

  dispatchLoading.value = true
  try {
    await dispatchStoreInventoryToDeviceApi(selectedStoreId.value, {
      material_id: dispatchForm.material_id,
      device_sn: dispatchForm.device_sn,
      quantity: dispatchForm.quantity,
      remarks: dispatchForm.remarks
    })
    ElMessage.success('物料已成功出库加料到设备！')
    showDispatchDialog.value = false
    fetchStoreInventory()
  } catch (err: any) {
    ElMessage.error(err.message || '出库加料失败')
  } finally {
    dispatchLoading.value = false
  }
}

// -------------------------------------------------------------
// 门店调拨流水
// -------------------------------------------------------------
async function fetchStoreRecords() {
  loadingRecords.value = true
  try {
    const res = await getStoreInventoryRecordsApi(recordStoreId.value, {
      page: recordPage.value,
      page_size: recordPageSize.value,
      record_type: recordFilters.record_type,
      search: recordFilters.search,
    })
    storeRecordsList.value = res.data.results || []
    storeRecordsTotalCount.value = res.data.count || 0
  } catch (err: any) {
    ElMessage.error(err.message || '获取门店流水失败')
  } finally {
    loadingRecords.value = false
  }
}

function resetRecordFilters() {
  recordStoreId.value = undefined
  recordFilters.record_type = ''
  recordFilters.search = ''
  recordPage.value = 1
  fetchStoreRecords()
}
</script>

<style scoped>
.store-management-page {
  padding-bottom: 24px;
}

.store-tabs {
  background: #ffffff;
  border-radius: 8px;
}

.tab-label-box {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
}

.tab-icon {
  font-size: 16px;
}

.tab-badge {
  margin-left: 4px;
}
</style>
