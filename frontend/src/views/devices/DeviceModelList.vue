<template>
  <div class="page-container device-model-list-page">
    <PageHeader
      title="设备型号与机型定义"
      subtitle="定义物理硬件型号、型号编码与功能特性，全网设备按型号进行标准化归属与固件管理"
    >
      <template #actions>
        <el-button type="primary" icon="Plus" @click="openCreateDialog">
          + 录入新机型
        </el-button>
      </template>
    </PageHeader>

    <div class="chart-card">
      <el-table v-loading="loading" :data="modelList" stripe style="width: 100%">
        <el-table-column prop="id" label="型号ID" width="90" align="center" />
        <el-table-column prop="name" label="型号名称" min-width="180" />
        <el-table-column prop="code" label="型号唯一编码" width="160">
          <template #default="{ row }">
            <el-tag size="small" type="info" style="font-family: monospace;">{{ row.code }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="功能特性描述" min-width="240" show-overflow-tooltip />
        <el-table-column prop="device_count" label="全网绑定设备数" width="140" align="center">
          <template #default="{ row }">
            <el-tag size="small" type="primary">{{ row.device_count || 0 }} 台</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="180" />
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="openEditDialog(row)">
              编辑
            </el-button>
            <el-popconfirm title="确定删除该型号吗？" @confirm="handleDelete(row.id)">
              <template #reference>
                <el-button type="danger" link size="small">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 新增/编辑型号对话框 -->
    <el-dialog
      v-model="showDialog"
      :title="isEdit ? '编辑设备型号' : '录入新设备型号'"
      width="520px"
    >
      <el-form :model="formData" label-width="100px">
        <el-form-item label="型号名称" required>
          <el-input v-model="formData.name" placeholder="例如 智能现磨咖啡机 A1型" />
        </el-form-item>
        <el-form-item label="型号编码" required>
          <el-input v-model="formData.code" placeholder="全局唯一编码，如 MODEL-A1" />
        </el-form-item>
        <el-form-item label="功能描述">
          <el-input
            v-model="formData.description"
            type="textarea"
            :rows="3"
            placeholder="说明该型号的硬件特性（如：双出料口、自带冷柜与制冰机模块等）"
          />
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
import { Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import {
  getDeviceModelsApi,
  createDeviceModelApi,
  updateDeviceModelApi,
  deleteDeviceModelApi,
} from '@/api/global_config'
import type { DeviceModelItem } from '@/types'

const loading = ref(false)
const modelList = ref<DeviceModelItem[]>([])

const showDialog = ref(false)
const isEdit = ref(false)
const submitLoading = ref(false)
const currentId = ref<number | null>(null)

const formData = reactive({
  name: '',
  code: '',
  description: '',
})

async function fetchModels() {
  loading.value = true
  try {
    const res = await getDeviceModelsApi()
    if (res.data) {
      modelList.value = res.data
    }
  } finally {
    loading.value = false
  }
}

function openCreateDialog() {
  isEdit.value = false
  currentId.value = null
  Object.assign(formData, {
    name: '',
    code: '',
    description: '',
  })
  showDialog.value = true
}

function openEditDialog(row: DeviceModelItem) {
  isEdit.value = true
  currentId.value = row.id
  Object.assign(formData, {
    name: row.name,
    code: row.code,
    description: row.description || '',
  })
  showDialog.value = true
}

async function handleSubmit() {
  if (!formData.name || !formData.code) {
    ElMessage.warning('型号名称和编码为必填项')
    return
  }

  submitLoading.value = true
  try {
    if (isEdit.value && currentId.value) {
      await updateDeviceModelApi(currentId.value, formData)
      ElMessage.success('设备型号已更新')
    } else {
      await createDeviceModelApi(formData)
      ElMessage.success('设备型号已录入')
    }
    showDialog.value = false
    fetchModels()
  } finally {
    submitLoading.value = false
  }
}

async function handleDelete(id: number) {
  try {
    await deleteDeviceModelApi(id)
    ElMessage.success('设备型号已删除')
    fetchModels()
  } catch (e) {
    // 错误由拦截器统一提示
  }
}

onMounted(() => {
  fetchModels()
})
</script>
