<template>
  <div class="page-container device-list-page">
    <PageHeader
      title="设备档案与配置管理"
      subtitle="管理全网自助咖啡机硬件信息、所属门店分配、注册上线、GPS坐标以及通信参数"
    >
      <template #actions>
        <el-button type="primary" icon="Plus" @click="openCreateDialog">
          + 录入新设备
        </el-button>
      </template>
    </PageHeader>

    <!-- 筛选表单 -->
    <div class="chart-card">
      <el-form :inline="true" :model="filters" size="default">
        <el-form-item label="设备序列号/名称">
          <el-input v-model="filters.search" placeholder="输入 SN 或名称" clearable />
        </el-form-item>
        <el-form-item label="设备状态">
          <el-select v-model="filters.status" placeholder="全部状态" clearable style="width: 120px;">
            <el-option label="在线" value="online" />
            <el-option label="离线" value="offline" />
            <el-option label="故障" value="fault" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" icon="Search" @click="fetchDevices">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>

      <!-- 设备列表表格 -->
      <el-table v-loading="loading" :data="deviceList" stripe style="width: 100%">
        <el-table-column prop="device_sn" label="设备序列号 (SN)" min-width="150">
          <template #default="{ row }">
            <span style="font-family: monospace; font-weight: 600;">{{ row.device_sn }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="device_name" label="设备名称" min-width="150" />
        <el-table-column prop="key_code" label="注册码" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.key_code" size="small" type="info" style="font-family: monospace;">{{ row.key_code }}</el-tag>
            <span v-else style="color: #c0c4cc;">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="store_name" label="所属门店" width="140">
          <template #default="{ row }">{{ row.store_name || '未分配' }}</template>
        </el-table-column>
        <el-table-column prop="device_model_name" label="设备型号" width="130">
          <template #default="{ row }">
            <el-tag v-if="row.device_model_name" size="small" type="primary">{{ row.device_model_name }}</el-tag>
            <span v-else style="color: #c0c4cc;">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="设备状态" width="100">
          <template #default="{ row }">
            <StatusBadge :status="row.status" />
          </template>
        </el-table-column>
        <el-table-column prop="business_status" label="营业状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.is_in_business_hours ? 'success' : 'info'" size="small">
              {{ row.business_status || (row.is_in_business_hours ? '正在营业中' : '打烊中') }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="firmware_version" label="固件版本" width="110">
          <template #default="{ row }">{{ row.firmware_version || '-' }}</template>
        </el-table-column>
        <el-table-column prop="gps_coordinate" label="GPS坐标" width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.gps_coordinate || '-' }}</template>
        </el-table-column>
        <el-table-column prop="last_heartbeat_at" label="最后心跳" width="170" />
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="$router.push(`/monitor/${row.device_sn}`)">
              监控
            </el-button>
            <el-button type="primary" link size="small" @click="openEditDialog(row)">
              编辑
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div style="margin-top: 16px; display: flex; justify-content: flex-end;">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="totalCount"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          @change="fetchDevices"
        />
      </div>
    </div>

    <!-- 录入/编辑设备对话框 -->
    <el-dialog
      v-model="showDialog"
      :title="isEdit ? '编辑设备配置' : '录入新设备'"
      width="680px"
    >
      <el-form ref="formRef" :model="formData" label-width="130px">
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="序列号 (SN)" required>
              <el-input v-model="formData.device_sn" :disabled="isEdit" placeholder="出厂唯一编码，如 SN001" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="设备名称" required>
              <el-input v-model="formData.device_name" placeholder="如 朝阳大悦城1号咖啡机" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="门店注册码 (key_code)">
              <el-input v-model="formData.key_code" placeholder="用于设备上线鉴权注册" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="设备状态">
              <el-select v-model="formData.status" style="width: 100%;">
                <el-option label="离线 (offline)" value="offline" />
                <el-option label="在线 (online)" value="online" />
                <el-option label="故障 (fault)" value="fault" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="分配所属门店">
              <el-select v-model="formData.store" placeholder="选择分配的门店" filterable clearable style="width: 100%;">
                <el-option
                  v-for="store in storeOptions"
                  :key="store.id"
                  :label="`${store.name} (ID: ${store.id})`"
                  :value="store.id"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="设备型号">
              <el-select v-model="formData.device_model" placeholder="选择硬件机型" clearable style="width: 100%;">
                <el-option
                  v-for="model in modelList"
                  :key="model.id"
                  :label="`${model.name} (${model.code})`"
                  :value="model.id"
                />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="固件版本">
              <el-input v-model="formData.firmware_version" placeholder="如 1.0.0 或 2.1.4" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="GPS经纬度坐标">
              <el-input v-model="formData.gps_coordinate" placeholder="如 116.4074,39.9042" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="MQTT主题前缀">
          <el-input v-model="formData.mqtt_topic_prefix" placeholder="留空则使用默认 automake/devices/{SN}" />
        </el-form-item>

        <el-form-item label="设备安装地址">
          <el-input v-model="formData.address" placeholder="如 商场1层B入口扶梯旁" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" :loading="submitLoading" @click="handleSubmit">
          确认保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { Plus, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { getDevicesApi, createDeviceApi, updateDeviceApi } from '@/api/devices'
import { getDeviceModelsApi } from '@/api/global_config'
import { getStoresApi } from '@/api/stores'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()

const loading = ref(false)
const deviceList = ref<any[]>([])
const totalCount = ref(0)
const page = ref(1)
const pageSize = ref(20)

const filters = reactive({
  search: '',
  status: '',
})

const showDialog = ref(false)
const isEdit = ref(false)
const submitLoading = ref(false)
const modelList = ref<any[]>([])
const storeOptions = ref<any[]>([])

const formData = reactive<any>({
  device_sn: '',
  key_code: '',
  device_name: '',
  store: undefined,
  device_model: undefined,
  status: 'offline',
  firmware_version: '1.0.0',
  gps_coordinate: '',
  mqtt_topic_prefix: '',
  address: '',
})

async function fetchDevices() {
  loading.value = true
  try {
    const res = await getDevicesApi({
      page: page.value,
      page_size: pageSize.value,
      search: filters.search,
      status: filters.status,
    })
    if (res.data) {
      deviceList.value = res.data.results || []
      totalCount.value = res.data.count || 0
    }
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  filters.search = ''
  filters.status = ''
  fetchDevices()
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

async function fetchModels() {
  try {
    const res = await getDeviceModelsApi()
    if (res.data) {
      modelList.value = res.data
    }
  } catch (e) {
    //
  }
}

function openCreateDialog() {
  isEdit.value = false
  fetchStores()
  fetchModels()
  Object.assign(formData, {
    device_sn: '',
    key_code: '',
    device_name: '',
    store: storeOptions.value[0]?.id || undefined,
    device_model: modelList.value[0]?.id || undefined,
    status: 'offline',
    firmware_version: '1.0.0',
    gps_coordinate: '',
    mqtt_topic_prefix: '',
    address: '',
  })
  showDialog.value = true
}

function openEditDialog(row: any) {
  isEdit.value = true
  fetchStores()
  fetchModels()
  Object.assign(formData, {
    device_sn: row.device_sn,
    key_code: row.key_code || '',
    device_name: row.device_name,
    store: row.store,
    device_model: row.device_model,
    status: row.status || 'offline',
    firmware_version: row.firmware_version || '',
    gps_coordinate: row.gps_coordinate || '',
    mqtt_topic_prefix: row.mqtt_topic_prefix || '',
    address: row.address || '',
  })
  showDialog.value = true
}

async function handleSubmit() {
  if (!formData.device_sn || !formData.device_name) {
    ElMessage.warning('设备序列号和名称为必填项')
    return
  }

  submitLoading.value = true
  try {
    if (isEdit.value) {
      await updateDeviceApi(formData.device_sn, formData)
      ElMessage.success('设备更新成功')
    } else {
      await createDeviceApi(formData)
      ElMessage.success('设备录入成功')
    }
    showDialog.value = false
    fetchDevices()
  } finally {
    submitLoading.value = false
  }
}

onMounted(() => {
  fetchDevices()
  fetchStores()
  fetchModels()
})
</script>
