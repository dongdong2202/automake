<template>
  <div class="page-container category-list-page">
    <PageHeader
      title="菜谱品类与分类管理"
      subtitle="按设备机型灵活维护商品所属分类、推荐标签、排序权重与前端展示状态"
    >
      <template #actions>
        <el-button type="primary" icon="Plus" @click="openCreateDialog">
          + 新建菜单分类
        </el-button>
      </template>
    </PageHeader>

    <div class="chart-card">
      <el-form :inline="true" size="default">
        <el-form-item label="按设备型号筛选">
          <el-select
            v-model="selectedModel"
            placeholder="全部设备型号"
            clearable
            style="width: 200px;"
            @change="fetchCategories"
          >
            <el-option
              v-for="m in modelOptions"
              :key="m.id"
              :label="`${m.name} (${m.code})`"
              :value="m.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" icon="Search" @click="fetchCategories">查询</el-button>
        </el-form-item>
      </el-form>

      <el-table v-loading="loading" :data="categoryList" stripe style="width: 100%">
        <el-table-column prop="id" label="ID" width="80" align="center" />
        <el-table-column prop="name" label="分类名称" min-width="160" />
        <el-table-column prop="device_model_name" label="归属设备机型" min-width="160">
          <template #default="{ row }">
            <el-tag size="small" type="info">{{ row.device_model_name }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="label" label="特色标签" width="130">
          <template #default="{ row }">
            <el-tag
              v-if="row.label === 'recomm'"
              size="small"
              type="danger"
            >
              ★ 店长推荐
            </el-tag>
            <el-tag
              v-else-if="row.label === 'hot'"
              size="small"
              type="warning"
            >
              🔥 畅销爆款
            </el-tag>
            <el-tag
              v-else-if="row.label === 'new'"
              size="small"
              type="success"
            >
              ✨ 尝鲜新品
            </el-tag>
            <el-tag v-else size="small" type="info">{{ row.label || '常规' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="sort_order" label="排序权重" width="110" align="center" sortable />
        <el-table-column prop="item_count" label="归属商品数" width="120" align="center">
          <template #default="{ row }">
            <el-tag size="small" type="primary">{{ row.item_count || 0 }} 款</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="启用状态" width="110" align="center">
          <template #default="{ row }">
            <el-switch
              v-model="row.is_active"
              @change="handleToggleStatus(row)"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="openEditDialog(row)">
              编辑
            </el-button>
            <el-popconfirm title="确定删除该分类吗？" @confirm="handleDelete(row.id)">
              <template #reference>
                <el-button type="danger" link size="small">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 新增/编辑分类对话框 -->
    <el-dialog
      v-model="showDialog"
      :title="isEdit ? '编辑菜单分类' : '新建菜单分类'"
      width="540px"
    >
      <el-form :model="formData" label-width="110px">
        <el-form-item label="设备机型" required>
          <el-select v-model="formData.device_model" placeholder="请选择绑定的设备型号" style="width: 100%;">
            <el-option
              v-for="m in modelOptions"
              :key="m.id"
              :label="`${m.name} (${m.code})`"
              :value="m.id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="分类名称" required>
          <el-input v-model="formData.name" placeholder="例如 经典意式 / 特调风味 / 鲜萃冷饮" />
        </el-form-item>

        <el-form-item label="展示标签">
          <el-radio-group v-model="formData.label">
            <el-radio label="recomm">推荐 (recomm)</el-radio>
            <el-radio label="hot">热销 (hot)</el-radio>
            <el-radio label="new">新品 (new)</el-radio>
            <el-radio label="classic">经典 (classic)</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="排序权重">
          <el-input-number v-model="formData.sort_order" :min="0" :max="999" placeholder="数值越小越靠前" />
          <span style="margin-left: 10px; color: #909399; font-size: 12px;">数值越小，小程序端排序越靠前</span>
        </el-form-item>

        <el-form-item label="是否启用">
          <el-switch v-model="formData.is_active" />
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
import {
  getGlobalCategoriesApi,
  createGlobalCategoryApi,
  updateGlobalCategoryApi,
  deleteGlobalCategoryApi,
} from '@/api/menus'
import { getDeviceModelsApi } from '@/api/global_config'
import type { CategoryItem, DeviceModelItem } from '@/types'

const loading = ref(false)
const categoryList = ref<CategoryItem[]>([])
const modelOptions = ref<DeviceModelItem[]>([])
const selectedModel = ref<number | ''>('')

const showDialog = ref(false)
const isEdit = ref(false)
const submitLoading = ref(false)
const currentId = ref<number | null>(null)

const formData = reactive<any>({
  device_model: undefined,
  name: '',
  label: 'recomm',
  sort_order: 0,
  is_active: true,
})

async function fetchCategories() {
  loading.value = true
  try {
    const params = selectedModel.value ? { device_model: selectedModel.value } : undefined
    const res = await getGlobalCategoriesApi(params)
    if (res.data) {
      categoryList.value = res.data
    }
  } finally {
    loading.value = false
  }
}

async function fetchModels() {
  try {
    const res = await getDeviceModelsApi()
    if (res.data) {
      modelOptions.value = res.data
    }
  } catch (e) {
    //
  }
}

function openCreateDialog() {
  isEdit.value = false
  currentId.value = null
  Object.assign(formData, {
    device_model: modelOptions.value[0]?.id,
    name: '',
    label: 'recomm',
    sort_order: 0,
    is_active: true,
  })
  showDialog.value = true
}

function openEditDialog(row: CategoryItem) {
  isEdit.value = true
  currentId.value = row.id
  Object.assign(formData, {
    device_model: row.device_model,
    name: row.name,
    label: row.label || 'recomm',
    sort_order: row.sort_order || 0,
    is_active: row.is_active,
  })
  showDialog.value = true
}

async function handleSubmit() {
  if (!formData.device_model || !formData.name) {
    ElMessage.warning('请选择所属机型并填写分类名称')
    return
  }

  submitLoading.value = true
  try {
    if (isEdit.value && currentId.value) {
      await updateGlobalCategoryApi(currentId.value, formData)
      ElMessage.success('分类更新成功')
    } else {
      await createGlobalCategoryApi(formData)
      ElMessage.success('分类创建成功')
    }
    showDialog.value = false
    fetchCategories()
  } finally {
    submitLoading.value = false
  }
}

async function handleToggleStatus(row: CategoryItem) {
  try {
    await updateGlobalCategoryApi(row.id, { is_active: row.is_active })
    ElMessage.success(`分类 [${row.name}] 状态已更新`)
  } catch (e) {
    row.is_active = !row.is_active
  }
}

async function handleDelete(id: number) {
  try {
    await deleteGlobalCategoryApi(id)
    ElMessage.success('分类已删除')
    fetchCategories()
  } catch (e) {
    //
  }
}

onMounted(() => {
  fetchCategories()
  fetchModels()
})
</script>
