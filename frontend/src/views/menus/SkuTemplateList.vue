<template>
  <div class="page-container sku-template-list-page">
    <PageHeader
      title="全局规格模板库 (GlobalSkuTemplate)"
      subtitle="定义通用的抽象规格分类（杯型、温度、糖度等）、标准加价增量与规格默认原料消耗配方"
    >
      <template #actions>
        <el-button type="primary" icon="Plus" @click="openCreateDialog">
          + 新建规格模板
        </el-button>
      </template>
    </PageHeader>

    <div class="chart-card">
      <el-form :inline="true" size="default">
        <el-form-item label="规格分类">
          <el-select
            v-model="filterCategory"
            placeholder="全部分类"
            clearable
            style="width: 160px;"
            @change="fetchTemplates"
          >
            <el-option label="杯型" value="杯型" />
            <el-option label="温度" value="温度" />
            <el-option label="糖度" value="糖度" />
            <el-option label="风味" value="风味" />
            <el-option label="通用/默认" value="default" />
          </el-select>
        </el-form-item>
        <el-form-item label="规格名称">
          <el-input v-model="searchKeyword" placeholder="输入规格名称或描述" clearable />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" icon="Search" @click="fetchTemplates">查询</el-button>
        </el-form-item>
      </el-form>

      <el-table v-loading="loading" :data="templateList" stripe style="width: 100%">
        <el-table-column prop="id" label="ID" width="70" align="center" />
        <el-table-column prop="category" label="规格分类" width="130">
          <template #default="{ row }">
            <el-tag :type="getCategoryTag(row.category)" size="small">
              {{ row.category }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="规格名称" min-width="150">
          <template #default="{ row }">
            <span style="font-weight: 600;">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="default_price_delta" label="默认加价(元)" width="140">
          <template #default="{ row }">
            <span
              :style="{
                fontWeight: 'bold',
                color: row.default_price_delta > 0 ? '#E6A23C' : '#67C23A'
              }"
            >
              {{ row.default_price_delta > 0 ? `+${formatCurrency(row.default_price_delta)}` : '¥0.00' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="规格默认配料清单" min-width="220">
          <template #default="{ row }">
            <div v-if="row.ingredients && row.ingredients.length > 0" style="display: flex; flex-wrap: wrap; gap: 4px;">
              <el-tag
                v-for="(ing, idx) in row.ingredients"
                :key="idx"
                size="small"
                type="info"
                effect="plain"
              >
                {{ ing.material_name || ing.material }}: {{ ing.quantity }}{{ ing.unit || 'g' }}
              </el-tag>
            </div>
            <span v-else style="color: #c0c4cc; font-size: 12px;">无默认配料</span>
          </template>
        </el-table-column>
        <el-table-column prop="sku_count" label="绑定商品数" width="110" align="center">
          <template #default="{ row }">
            <el-badge :value="row.sku_count || 0" type="primary" />
          </template>
        </el-table-column>
        <el-table-column prop="description" label="规格描述" min-width="150" show-overflow-tooltip />
        <el-table-column prop="sort_order" label="排序" width="80" align="center" sortable />
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.is_active" @change="handleToggleStatus(row)" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="openEditDialog(row)">
              编辑
            </el-button>
            <el-popconfirm title="确定删除该规格模板吗？" @confirm="handleDelete(row.id)">
              <template #reference>
                <el-button type="danger" link size="small">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 创建/编辑规格模板对话框 -->
    <el-dialog
      v-model="showDialog"
      :title="isEdit ? `编辑规格模板 (ID: ${currentId})` : '新建全局规格模板'"
      width="680px"
      top="5vh"
    >
      <el-form :model="formData" label-position="top">
        <el-card shadow="never" class="section-card">
          <template #header>
            <span class="card-title">📌 基本信息</span>
          </template>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="规格分类" required>
                <div style="display: flex; gap: 8px; width: 100%;">
                  <el-select
                    v-model="formData.category"
                    filterable
                    allow-create
                    default-first-option
                    placeholder="选择已有分类或输入新分类"
                    style="flex: 1;"
                    @blur="handleCategorySelectBlur"
                  >
                    <el-option
                      v-for="cat in availableCategories"
                      :key="cat"
                      :label="cat"
                      :value="cat"
                    >
                      <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span>{{ cat }}</span>
                        <el-tag size="small" type="info" effect="plain" style="margin-left: 8px;">分类</el-tag>
                      </div>
                    </el-option>
                  </el-select>
                  <el-button
                    type="primary"
                    plain
                    icon="Plus"
                    @click="handlePromptNewCategory"
                  >
                    新建分类
                  </el-button>
                </div>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="规格名称" required>
                <el-input v-model="formData.name" placeholder="如 大杯、热、去冰、五分糖" />
              </el-form-item>
            </el-col>
          </el-row>

          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="默认加价 (元)">
                <el-input-number
                  v-model="formData.priceYuan"
                  :min="0"
                  :step="0.5"
                  :precision="2"
                  style="width: 100%;"
                />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="排序权重">
                <el-input-number v-model="formData.sort_order" :min="0" :max="999" style="width: 100%;" />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="是否启用">
                <el-switch v-model="formData.is_active" active-text="启用" inactive-text="停用" />
              </el-form-item>
            </el-col>
          </el-row>

          <el-form-item label="规格描述">
            <el-input v-model="formData.description" placeholder="说明该规格的含义或标准制作指引" />
          </el-form-item>
        </el-card>

        <!-- 默认配料清单管理 -->
        <el-card shadow="never" class="section-card" style="margin-top: 14px;">
          <template #header>
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span class="card-title">🧪 规格默认配料消耗 (可选)</span>
              <el-button type="primary" size="small" icon="Plus" @click="handleAddIngredient">
                添加物料配方
              </el-button>
            </div>
          </template>

          <div v-if="formData.ingredients.length === 0" style="text-align: center; color: #909399; padding: 12px 0;">
            暂未添加默认配料（该规格不额外消耗或改变基础原料）
          </div>

          <el-table v-else :data="formData.ingredients" size="small" border style="width: 100%">
            <el-table-column label="物料名称 (Material)" min-width="180">
              <template #default="{ row }">
                <el-select
                  v-model="row.material"
                  placeholder="选择仓库物料"
                  filterable
                  style="width: 100%;"
                  @change="(val: any) => handleMaterialSelect(row, val)"
                >
                  <el-option
                    v-for="m in materialOptions"
                    :key="m.name"
                    :label="`${m.name} (${m.code}) - ${m.unit}`"
                    :value="m.name"
                  />
                </el-select>
              </template>
            </el-table-column>

            <el-table-column label="默认用量" width="150">
              <template #default="{ row }">
                <el-input-number v-model="row.quantity" :min="0.01" :step="1" :precision="2" style="width: 100%;" />
              </template>
            </el-table-column>

            <el-table-column label="计量单位" width="120">
              <template #default="{ row }">
                <el-input v-model="row.unit" placeholder="留空使用默认" />
              </template>
            </el-table-column>

            <el-table-column label="操作" width="80" align="center">
              <template #default="{ $index }">
                <el-button type="danger" link size="small" @click="formData.ingredients.splice($index, 1)">
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
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
import { ref, reactive, computed, onMounted } from 'vue'
import { Plus, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import {
  getSkuTemplatesApi,
  createSkuTemplateApi,
  updateSkuTemplateApi,
  deleteSkuTemplateApi,
} from '@/api/menus'
import { getMaterialsApi } from '@/api/inventory'
import { fenToYuan, yuanToFen, formatCurrency } from '@/utils/money'
import type { SkuTemplateItem, MaterialItem } from '@/types'

const loading = ref(false)
const templateList = ref<SkuTemplateItem[]>([])
const materialOptions = ref<MaterialItem[]>([])
const filterCategory = ref('')
const searchKeyword = ref('')

const showDialog = ref(false)
const isEdit = ref(false)
const submitLoading = ref(false)
const currentId = ref<number | null>(null)

const presetCategories = ref<string[]>(['杯型', '温度', '糖度', '风味', '加料', '通用'])

const availableCategories = computed(() => {
  const cats = new Set<string>(presetCategories.value)
  if (Array.isArray(templateList.value)) {
    templateList.value.forEach((t: any) => {
      if (t.category && String(t.category).trim()) {
        cats.add(String(t.category).trim())
      }
    })
  }
  if (formData.category && String(formData.category).trim()) {
    cats.add(String(formData.category).trim())
  }
  return Array.from(cats)
})

async function handlePromptNewCategory() {
  try {
    const { value } = await ElMessageBox.prompt('请输入新的规格分类名称（例如：奶基底、包装、加料等）：', '新建规格分类', {
      confirmButtonText: '确定添加',
      cancelButtonText: '取消',
      inputPattern: /^.+$/,
      inputErrorMessage: '分类名称不能为空',
      inputPlaceholder: '如：加料、奶基底、浓度'
    })
    const trimmed = String(value || '').trim()
    if (trimmed) {
      if (!presetCategories.value.includes(trimmed)) {
        presetCategories.value.push(trimmed)
      }
      formData.category = trimmed
      ElMessage.success(`已设置分类为: ${trimmed}`)
    }
  } catch (e) {
    // canceled
  }
}

function handleCategorySelectBlur(e: any) {
  const inputVal = e?.target?.value?.trim()
  if (inputVal && !formData.category) {
    formData.category = inputVal
    if (!presetCategories.value.includes(inputVal)) {
      presetCategories.value.push(inputVal)
    }
  }
}

const formData = reactive<any>({
  category: '杯型',
  name: '',
  priceYuan: 0,
  description: '',
  sort_order: 0,
  is_active: true,
  ingredients: [] as Array<{ material: string; quantity: number; unit: string }>,
})

function getCategoryTag(cat: string) {
  const map: Record<string, string> = {
    杯型: 'primary',
    温度: 'danger',
    糖度: 'warning',
    风味: 'success',
    default: 'info',
  }
  return map[cat] || 'info'
}

async function fetchMaterials() {
  try {
    const res = await getMaterialsApi({ page_size: 200 })
    if (res.data) {
      materialOptions.value = res.data.results || []
    }
  } catch (e) {
    //
  }
}

async function fetchTemplates() {
  loading.value = true
  try {
    const res = await getSkuTemplatesApi({
      category: filterCategory.value || undefined,
      search: searchKeyword.value || undefined,
    })
    if (res.data) {
      templateList.value = res.data
    }
  } finally {
    loading.value = false
  }
}

function openCreateDialog() {
  isEdit.value = false
  currentId.value = null
  fetchMaterials()
  Object.assign(formData, {
    category: '杯型',
    name: '',
    priceYuan: 0,
    description: '',
    sort_order: 0,
    is_active: true,
    ingredients: [],
  })
  showDialog.value = true
}

function openEditDialog(row: SkuTemplateItem) {
  isEdit.value = true
  currentId.value = row.id
  fetchMaterials()
  Object.assign(formData, {
    category: row.category,
    name: row.name,
    priceYuan: fenToYuan(row.default_price_delta),
    description: row.description || '',
    sort_order: row.sort_order || 0,
    is_active: row.is_active,
    ingredients: (row.ingredients || []).map((ing: any) => ({
      material: ing.material_name || ing.material,
      quantity: Number(ing.quantity) || 1,
      unit: ing.unit || '',
    })),
  })
  showDialog.value = true
}

function handleAddIngredient() {
  const firstMat = materialOptions.value[0]
  formData.ingredients.push({
    material: firstMat ? firstMat.name : '',
    quantity: 1,
    unit: firstMat ? firstMat.unit : 'g',
  })
}

function handleMaterialSelect(row: any, matName: string) {
  const target = materialOptions.value.find((m) => m.name === matName)
  if (target) {
    row.unit = target.unit
  }
}

async function handleSubmit() {
  if (!formData.category || !formData.name) {
    ElMessage.warning('规格分类和规格名称为必填项')
    return
  }

  submitLoading.value = true
  try {
    const payload = {
      category: formData.category,
      name: formData.name,
      default_price_delta: yuanToFen(formData.priceYuan),
      description: formData.description,
      sort_order: formData.sort_order,
      is_active: formData.is_active,
      ingredients: formData.ingredients.map((ing: any) => ({
        material: ing.material,
        quantity: ing.quantity,
        unit: ing.unit,
      })),
    }

    if (isEdit.value && currentId.value) {
      await updateSkuTemplateApi(currentId.value, payload)
      ElMessage.success('规格模板更新成功')
    } else {
      await createSkuTemplateApi(payload)
      ElMessage.success('规格模板创建成功')
    }
    showDialog.value = false
    fetchTemplates()
  } finally {
    submitLoading.value = false
  }
}

async function handleToggleStatus(row: SkuTemplateItem) {
  try {
    await updateSkuTemplateApi(row.id, { is_active: row.is_active })
    ElMessage.success(`规格 [${row.name}] 状态已更新`)
  } catch (e) {
    row.is_active = !row.is_active
  }
}

async function handleDelete(id: number) {
  try {
    await deleteSkuTemplateApi(id)
    ElMessage.success('规格模板已删除')
    fetchTemplates()
  } catch (e) {
    //
  }
}

onMounted(() => {
  fetchTemplates()
  fetchMaterials()
})
</script>

<style scoped>
.section-card {
  border-radius: 8px;
  background-color: #fafafa;
}
.card-title {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
}
</style>
