<template>
  <div class="page-container global-menu-list-page">
    <PageHeader
      title="全局菜谱商品库 (GlobalMenuItem)"
      subtitle="定义标准产品档案、基准售价、750px宽详情页海报，并直接配置关联的规格模板 (SKU) 与加价"
    >
      <template #actions>
        <el-button type="primary" icon="Plus" @click="openCreateDialog">
          + 新建全局商品
        </el-button>
      </template>
    </PageHeader>

    <!-- 筛选条件 -->
    <div class="chart-card">
      <el-form :inline="true" size="default">
        <el-form-item label="所属菜单分类">
          <el-select
            v-model="selectedCategory"
            placeholder="全部分类"
            clearable
            style="width: 220px;"
            @change="fetchItems"
          >
            <el-option
              v-for="c in categoryList"
              :key="c.id"
              :label="`${c.name} (${c.device_model_name || '机型'})`"
              :value="c.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="商品名称">
          <el-input v-model="searchKeyword" placeholder="输入商品名称" clearable />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" icon="Search" @click="fetchItems">查询</el-button>
        </el-form-item>
      </el-form>

      <!-- 全局商品大表 -->
      <el-table v-loading="loading" :data="itemList" stripe style="width: 100%">
        <el-table-column prop="id" label="ID" width="65" align="center" />

        <el-table-column label="商品主图" width="80" align="center">
          <template #default="{ row }">
            <el-image
              v-if="row.image_url"
              :src="row.image_url"
              :preview-src-list="[row.image_url]"
              fit="cover"
              preview-teleported
              style="width: 44px; height: 44px; border-radius: 4px; border: 1px solid #ebeef5; cursor: pointer;"
            />
            <span v-else style="color: #c0c4cc; font-size: 11px;">无主图</span>
          </template>
        </el-table-column>

        <el-table-column label="详情页图" width="80" align="center">
          <template #default="{ row }">
            <el-image
              v-if="row.detail_page"
              :src="row.detail_page"
              :preview-src-list="[row.detail_page]"
              fit="cover"
              preview-teleported
              style="width: 44px; height: 44px; border-radius: 4px; border: 1px solid #ebeef5; cursor: pointer;"
            />
            <span v-else style="color: #c0c4cc; font-size: 11px;">无详情图</span>
          </template>
        </el-table-column>

        <el-table-column prop="name" label="商品名称" min-width="140" />

        <el-table-column prop="category_name" label="所属分类" min-width="130">
          <template #default="{ row }">
            <el-tag size="small" type="info">{{ row.category_name }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="device_model_name" label="适配机型" width="130">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.device_model_name || '-' }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="base_price" label="基准售价" width="110">
          <template #default="{ row }">
            <span style="font-weight: bold; color: #E6A23C;">
              {{ formatCurrency(row.base_price) }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="挂载规格 (SKU)" min-width="260">
          <template #default="{ row }">
            <div v-if="row.skus && row.skus.length > 0" style="display: flex; flex-wrap: wrap; gap: 4px;">
              <el-tag
                v-for="sku in row.skus"
                :key="sku.id"
                size="small"
                :type="sku.is_active ? 'primary' : 'info'"
                effect="plain"
              >
                {{ sku.template_name || sku.name }}
                <span v-if="sku.price_delta > 0" style="color: #E6A23C; font-weight: 600;">
                  (+{{ formatCurrency(sku.price_delta) }})
                </span>
              </el-tag>
            </div>
            <span v-else style="color: #909399; font-size: 12px;">未配置规格</span>
          </template>
        </el-table-column>

        <el-table-column prop="sort_order" label="排序" width="75" align="center" sortable />

        <el-table-column label="上架状态" width="95" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.is_active" @change="handleToggleStatus(row)" />
          </template>
        </el-table-column>

        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="openEditDialog(row)">
              编辑商品
            </el-button>
            <el-button type="warning" link size="small" @click="openRecipeModal(row)">
              定制配方
            </el-button>
            <el-popconfirm title="确定删除该全局商品吗？" @confirm="handleDelete(row.id)">
              <template #reference>
                <el-button type="danger" link size="small">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 新建/编辑全局商品完整档案弹窗 (包含基本信息、图片、详情图、规格模板内联子表) -->
    <el-dialog
      v-model="showDialog"
      :title="isEdit ? `编辑全局商品档案 (ID: ${currentId})` : '新建全局商品档案'"
      width="900px"
      top="3vh"
      :close-on-click-modal="false"
    >
      <el-form :model="formData" label-position="top">
        <!-- 分区 1: 基本档案与定价 -->
        <el-card shadow="never" class="form-section-card">
          <template #header>
            <span class="section-title">📋 基本档案与定价</span>
          </template>

          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="商品名称" required>
                <el-input v-model="formData.name" placeholder="如 经典美式、生椰拿铁" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="所属菜单分类" required>
                <el-select v-model="formData.category" placeholder="请选择分类" style="width: 100%;">
                  <el-option
                    v-for="c in categoryList"
                    :key="c.id"
                    :label="`${c.name} (${c.device_model_name || '机型'})`"
                    :value="c.id"
                  />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>

          <el-row :gutter="16">
            <el-col :span="8">
              <el-form-item label="全局基准售价 (元)" required>
                <el-input-number
                  v-model="formData.priceYuan"
                  :min="0.01"
                  :step="1"
                  :precision="2"
                  style="width: 100%;"
                />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="排序权重">
                <el-input-number v-model="formData.sort_order" :min="0" :max="999" style="width: 100%;" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="是否上架">
                <el-switch v-model="formData.is_active" active-text="上架" inactive-text="下架" />
              </el-form-item>
            </el-col>
          </el-row>

          <el-form-item label="主要原料说明 (原料卡片展示)">
            <el-input
              v-model="formData.main_ingredients"
              type="textarea"
              :rows="2"
              placeholder="请输入主要原料说明（如：优质新鲜赣南脐橙、纯净冰块、天然果糖）"
            />
          </el-form-item>

          <el-form-item label="商品说明">
            <el-input
              v-model="formData.price_description"
              type="textarea"
              :rows="2"
              placeholder="请输入商品说明（如：阳光黄金脐橙整颗冷榨，不加一滴水与蔗糖，建议30分钟内饮用口感最佳）"
            />
          </el-form-item>
        </el-card>

        <!-- 分区 2: 商品主图与详情页海报 -->
        <el-card shadow="never" class="form-section-card" style="margin-top: 14px;">
          <template #header>
            <span class="section-title">🖼 商品图片与详情页海报</span>
          </template>

          <el-row :gutter="20">
            <!-- 主图 -->
            <el-col :span="12">
              <div class="image-upload-box">
                <div class="box-title">商品主图 (点单大图)</div>
                <div class="img-preview square-box">
                  <el-image v-if="formData.image_url" :src="formData.image_url" fit="cover" class="preview-inner" />
                  <div v-else class="empty-txt">暂无主图</div>
                </div>
                <div class="btn-group">
                  <el-upload
                    action=""
                    :auto-upload="false"
                    :show-file-list="false"
                    accept="image/png,image/jpeg,image/jpg,image/webp"
                    :on-change="(file: any) => handleUploadImage(file, 'image_url')"
                  >
                    <el-button size="small" type="primary" icon="Upload">上传主图</el-button>
                  </el-upload>
                  <el-button v-if="formData.image_url" size="small" type="danger" link @click="formData.image_url = ''">
                    清空
                  </el-button>
                </div>
                <el-input v-model="formData.image_url" size="small" placeholder="或直接输入主图 URL" style="margin-top: 8px;" />
              </div>
            </el-col>

            <!-- 详情页海报 -->
            <el-col :span="12">
              <div class="image-upload-box">
                <div class="box-title">商品详情页图 (detail_page)</div>
                <div class="box-sub" style="font-size: 12px; color: #e6a23c; margin-bottom: 6px; font-weight: 500;">
                  严格规范：宽必须为 750px (如 750×1334px)，大小 &lt; 1MB
                </div>
                <div class="img-preview detail-box">
                  <el-image v-if="formData.detail_page" :src="formData.detail_page" fit="contain" class="preview-inner" />
                  <div v-else class="empty-txt">暂无详情图</div>
                </div>
                <div class="btn-group">
                  <el-upload
                    action=""
                    :auto-upload="false"
                    :show-file-list="false"
                    accept="image/png,image/jpeg,image/jpg,image/webp"
                    :on-change="(file: any) => handleUploadImage(file, 'detail_page')"
                  >
                    <el-button size="small" type="primary" icon="Upload">上传详情图</el-button>
                  </el-upload>
                  <el-button v-if="formData.detail_page" size="small" type="danger" link @click="formData.detail_page = ''">
                    清空
                  </el-button>
                </div>
                <el-input v-model="formData.detail_page" size="small" placeholder="或直接输入详情页图 URL" style="margin-top: 8px;" />
              </div>
            </el-col>
          </el-row>
        </el-card>

        <!-- 分区 3: 挂载规格与定价 (GlobalSkuTemplate 映射子表) -->
        <el-card shadow="never" class="form-section-card" style="margin-top: 14px;">
          <template #header>
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <div>
                <span class="section-title">🏷 挂载商品规格与定价 (GlobalSkuTemplate 映射)</span>
                <span style="color: #909399; font-size: 12px; margin-left: 8px;">
                  选择该商品支持的规格（杯型/温度/糖度等），并可直接在此调整专属加价
                </span>
              </div>
              <el-button type="primary" size="small" icon="Plus" @click="handleAddSkuRow">
                + 添加规格
              </el-button>
            </div>
          </template>

          <div v-if="formData.skus.length === 0" style="text-align: center; color: #909399; padding: 20px 0;">
            暂未挂载任何规格模板，请点击右上角“+ 添加规格”选择规格
          </div>

          <el-table v-else :data="formData.skus" size="small" border style="width: 100%">
            <!-- 规格选择 -->
            <el-table-column label="选择规格模板 (GlobalSkuTemplate)" min-width="220">
              <template #default="{ row }">
                <el-select
                  v-model="row.template"
                  placeholder="选择规格模板"
                  filterable
                  style="width: 100%;"
                  @change="(val: any) => handleSkuTemplateSelect(row, val)"
                >
                  <el-option
                    v-for="t in allTemplates"
                    :key="t.id"
                    :label="`[${t.category}] ${t.name} (默认+${formatCurrency(t.default_price_delta)})`"
                    :value="t.id"
                    :disabled="isTemplateAlreadySelected(row, t.id)"
                  />
                </el-select>
              </template>
            </el-table-column>

            <!-- 规格分类 -->
            <el-table-column label="分类" width="90" align="center">
              <template #default="{ row }">
                <el-tag size="small" type="info">{{ row.template_category || '-' }}</el-tag>
              </template>
            </el-table-column>


            <!-- 商品专属加价 (可编辑) -->
            <el-table-column label="本商品加价 (元)" width="150" align="center">
              <template #default="{ row }">
                <el-input-number
                  v-model="row.priceDeltaYuan"
                  :min="-999"
                  :step="0.5"
                  :precision="2"
                  size="small"
                  style="width: 100%;"
                />
              </template>
            </el-table-column>


            <!-- 状态 -->
            <el-table-column label="启用" width="75" align="center">
              <template #default="{ row }">
                <el-switch v-model="row.is_active" size="small" />
              </template>
            </el-table-column>

            <!-- 操作 -->
            <el-table-column label="操作" width="75" align="center">
              <template #default="{ $index }">
                <el-button type="danger" link size="small" @click="formData.skus.splice($index, 1)">
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
          确认保存商品与规格
        </el-button>
      </template>
    </el-dialog>

    <!-- 弹窗 2: 定制商品专属原料配方 (Recipe Customization Modal) -->
    <el-dialog
      v-model="showRecipeModal"
      :title="`定制商品原料配方：${activeItem?.name || ''}`"
      width="750px"
      top="5vh"
    >
      <div v-if="activeItem">
        <div style="margin-bottom: 14px; font-size: 13px; color: #606266;">
          为商品的每个规格单独定制物料消耗配方（若不单独定制，则默认继承规格模板的标准配料）。
        </div>

        <el-collapse v-model="activeCollapse">
          <el-collapse-item
            v-for="sku in activeItem.skus || []"
            :key="sku.id"
            :title="`规格: [${sku.template_category}] ${sku.template_name} (加价: +¥${(sku.price_delta / 100).toFixed(2)})`"
            :name="sku.id"
          >
            <div style="margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;">
              <span style="font-size: 12px; font-weight: 600; color: #303133;">
                专属物料配比清单:
              </span>
              <el-button type="primary" size="small" icon="Plus" @click="handleAddSkuIngredient(sku)">
                添加物料
              </el-button>
            </div>

            <el-table :data="sku.ingredients || []" size="small" border style="width: 100%">
              <el-table-column label="物料名称" min-width="180">
                <template #default="{ row }">
                  <el-select
                    v-model="row.material"
                    placeholder="选择物料"
                    filterable
                    style="width: 100%;"
                    @change="(val: any) => handleRecipeMaterialSelect(row, val)"
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

              <el-table-column label="用量" width="130">
                <template #default="{ row }">
                  <el-input-number v-model="row.quantity" :min="0.01" :step="1" :precision="2" style="width: 100%;" />
                </template>
              </el-table-column>

              <el-table-column label="单位" width="100">
                <template #default="{ row }">
                  <el-input v-model="row.unit" placeholder="单位" />
                </template>
              </el-table-column>

              <el-table-column label="操作" width="70" align="center">
                <template #default="{ $index }">
                  <el-button type="danger" link size="small" @click="sku.ingredients && sku.ingredients.splice($index, 1)">
                    删除
                  </el-button>
                </template>
              </el-table-column>
            </el-table>

            <div style="margin-top: 8px; text-align: right;">
              <el-button
                type="primary"
                size="small"
                :loading="savingSkuId === sku.id"
                @click="handleSaveSkuRecipe(sku)"
              >
                保存此规格配方
              </el-button>
            </div>
          </el-collapse-item>
        </el-collapse>
      </div>
      <template #footer>
        <el-button @click="showRecipeModal = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { Plus, Search, Upload } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import {
  getGlobalItemsApi,
  getGlobalCategoriesApi,
  createGlobalItemApi,
  updateGlobalItemApi,
  deleteGlobalItemApi,
  getSkuTemplatesApi,
  updateItemSkuApi,
} from '@/api/menus'
import { getMaterialsApi } from '@/api/inventory'
import { uploadFileApi } from '@/api/common'
import { fenToYuan, yuanToFen, formatCurrency } from '@/utils/money'
import type { GlobalMenuItem, GlobalMenuSku, SkuTemplateItem, MaterialItem, CategoryItem } from '@/types'

const loading = ref(false)
const itemList = ref<GlobalMenuItem[]>([])
const categoryList = ref<CategoryItem[]>([])
const allTemplates = ref<SkuTemplateItem[]>([])
const materialOptions = ref<MaterialItem[]>([])

const selectedCategory = ref<number | ''>('')
const searchKeyword = ref('')

const showDialog = ref(false)
const isEdit = ref(false)
const submitLoading = ref(false)
const currentId = ref<number | null>(null)

// 创建/编辑商品表单数据
const formData = reactive<any>({
  name: '',
  category: undefined,
  priceYuan: 18.00,
  main_ingredients: '',
  price_description: '',
  image_url: '',
  detail_page: '',
  description: '',
  sort_order: 0,
  is_active: true,
  skus: [] as Array<{
    template: number | undefined
    template_name?: string
    template_category?: string
    default_price_delta?: number
    priceDeltaYuan: number
    is_active: boolean
    sort_order: number
  }>,
})

// 定制配方弹窗状态
const showRecipeModal = ref(false)
const activeItem = ref<GlobalMenuItem | null>(null)
const activeCollapse = ref<any[]>([])
const savingSkuId = ref<number | null>(null)

async function fetchItems() {
  loading.value = true
  try {
    const params: any = {}
    if (selectedCategory.value) params.category_id = selectedCategory.value
    if (searchKeyword.value) params.search = searchKeyword.value

    const [itemRes, catRes, tplRes, matRes] = await Promise.all([
      getGlobalItemsApi(params),
      getGlobalCategoriesApi(),
      getSkuTemplatesApi(),
      getMaterialsApi({ page_size: 200 }),
    ])
    itemList.value = itemRes.data?.results || []
    categoryList.value = catRes.data || []
    allTemplates.value = tplRes.data || []
    materialOptions.value = matRes.data?.results || []
  } finally {
    loading.value = false
  }
}

function openCreateDialog() {
  isEdit.value = false
  currentId.value = null
  fetchItems()
  Object.assign(formData, {
    name: '',
    category: categoryList.value[0]?.id,
    priceYuan: 18.00,
    main_ingredients: '',
    price_description: '',
    image_url: '',
    detail_page: '',
    description: '',
    sort_order: 0,
    is_active: true,
    skus: [],
  })

  // 默认自动填入 1~2 个常用模板供快速配置
  if (allTemplates.value.length > 0) {
    const defaultTpl = allTemplates.value[0]
    formData.skus.push({
      template: defaultTpl.id,
      template_name: defaultTpl.name,
      template_category: defaultTpl.category,
      default_price_delta: defaultTpl.default_price_delta,
      priceDeltaYuan: fenToYuan(defaultTpl.default_price_delta),
      is_active: true,
      sort_order: 0,
    })
  }

  showDialog.value = true
}

function openEditDialog(row: GlobalMenuItem) {
  isEdit.value = true
  currentId.value = row.id
  fetchItems()
  Object.assign(formData, {
    name: row.name,
    category: row.category,
    priceYuan: fenToYuan(row.base_price),
    main_ingredients: row.main_ingredients || '',
    price_description: row.price_description || '',
    image_url: row.image_url || '',
    detail_page: row.detail_page || '',
    description: row.description || '',
    sort_order: row.sort_order || 0,
    is_active: row.is_active,
    skus: (row.skus || []).map((sku) => ({
      template: sku.template,
      template_name: sku.template_name,
      template_category: sku.template_category,
      default_price_delta: sku.default_price_delta,
      priceDeltaYuan: fenToYuan(sku.price_delta),
      is_active: sku.is_active,
      sort_order: sku.sort_order || 0,
    })),
  })
  showDialog.value = true
}

function handleAddSkuRow() {
  const unusedTpl = allTemplates.value.find(
    (t) => !formData.skus.some((s: any) => s.template === t.id)
  ) || allTemplates.value[0]

  if (unusedTpl) {
    formData.skus.push({
      template: unusedTpl.id,
      template_name: unusedTpl.name,
      template_category: unusedTpl.category,
      default_price_delta: unusedTpl.default_price_delta,
      priceDeltaYuan: fenToYuan(unusedTpl.default_price_delta),
      is_active: true,
      sort_order: formData.skus.length,
    })
  } else {
    ElMessage.info('已挂载全部规格模板')
  }
}

function handleSkuTemplateSelect(row: any, tplId: number) {
  const target = allTemplates.value.find((t) => t.id === tplId)
  if (target) {
    row.template_name = target.name
    row.template_category = target.category
    row.default_price_delta = target.default_price_delta
    row.priceDeltaYuan = fenToYuan(target.default_price_delta)
  }
}

function isTemplateAlreadySelected(currentRow: any, tplId: number) {
  return formData.skus.some((s: any) => s !== currentRow && s.template === tplId)
}


async function handleUploadImage(uploadFile: any, field: 'image_url' | 'detail_page') {
  const rawFile = uploadFile.raw
  if (!rawFile) return

  // 1. 检查大小
  if (field === 'detail_page') {
    if (rawFile.size > 1 * 1024 * 1024) {
      ElMessage.error('商品详情页图大小不能超过 1MB，请压缩后重试')
      return
    }
  } else if (field === 'image_url') {
    if (rawFile.size > 2 * 1024 * 1024) {
      ElMessage.error('商品主图大小不能超过 2MB，请压缩后重试')
      return
    }
  }

  // 2. 检查图片尺寸
  const objectUrl = URL.createObjectURL(rawFile)
  const img = new Image()
  img.onload = async () => {
    try {
      if (field === 'detail_page') {
        if (img.width !== 750) {
          ElMessage.error(`商品详情页图宽度必须严格为 750px（当前检测为 ${img.width}px），请调整尺寸后再上传`)
          URL.revokeObjectURL(objectUrl)
          return
        }
      } else if (field === 'image_url') {
        const diff = Math.abs(img.width - img.height)
        if (diff > 40) {
          ElMessage.warning(`提示：当前主图尺寸为 ${img.width}x${img.height}，推荐使用 1:1 正方形比例 (如 800x800)`)
        }
      }

      const res = await uploadFileApi(rawFile, 'menus')
      if (res.data && res.data.url) {
        formData[field] = res.data.url
        ElMessage.success(`图片上传成功 (${img.width}x${img.height})`)
      }
    } catch (e) {
      ElMessage.error('图片上传失败，请重试')
    } finally {
      URL.revokeObjectURL(objectUrl)
    }
  }
  img.onerror = () => {
    ElMessage.error('无法读取图片文件，请上传有效的 JPG/PNG/WebP 格式图片')
    URL.revokeObjectURL(objectUrl)
  }
  img.src = objectUrl
}

async function handleSubmit() {
  if (!formData.name || !formData.category) {
    ElMessage.warning('商品名称和所属分类为必填项')
    return
  }

  submitLoading.value = true
  try {
    const payload = {
      name: formData.name,
      category: formData.category,
      base_price: yuanToFen(formData.priceYuan),
      main_ingredients: formData.main_ingredients,
      price_description: formData.price_description,
      image_url: formData.image_url,
      detail_page: formData.detail_page || null,
      description: formData.description,
      sort_order: formData.sort_order,
      is_active: formData.is_active,
      skus: formData.skus
        .filter((s: any) => s.template)
        .map((s: any) => ({
          template_id: s.template,
          price_delta: yuanToFen(s.priceDeltaYuan),
          is_active: s.is_active,
          sort_order: s.sort_order,
        })),
    }

    if (isEdit.value && currentId.value) {
      await updateGlobalItemApi(currentId.value, payload)
      ElMessage.success('商品档案及规格已同步保存')
    } else {
      await createGlobalItemApi(payload)
      ElMessage.success('商品档案及规格已创建')
    }
    showDialog.value = false
    fetchItems()
  } finally {
    submitLoading.value = false
  }
}

async function handleToggleStatus(row: GlobalMenuItem) {
  try {
    await updateGlobalItemApi(row.id, { is_active: row.is_active })
    ElMessage.success(`商品 [${row.name}] 状态已更新`)
  } catch (e) {
    row.is_active = !row.is_active
  }
}

async function handleDelete(id: number) {
  try {
    await deleteGlobalItemApi(id)
    ElMessage.success('全局商品已删除')
    fetchItems()
  } catch (e) {
    //
  }
}

// ============================================================
// 定制配方弹窗交互
// ============================================================
function openRecipeModal(row: GlobalMenuItem) {
  activeItem.value = JSON.parse(JSON.stringify(row))
  activeCollapse.value = (row.skus || []).map((s) => s.id)
  showRecipeModal.value = true
}

function handleAddSkuIngredient(sku: GlobalMenuSku) {
  if (!sku.ingredients) sku.ingredients = []
  const firstMat = materialOptions.value[0]
  sku.ingredients.push({
    material: firstMat ? firstMat.name : '',
    quantity: 1,
    unit: firstMat ? firstMat.unit : 'g',
  })
}

function handleRecipeMaterialSelect(row: any, matName: string) {
  const target = materialOptions.value.find((m) => m.name === matName)
  if (target) {
    row.unit = target.unit
  }
}

async function handleSaveSkuRecipe(sku: GlobalMenuSku) {
  savingSkuId.value = sku.id
  try {
    await updateItemSkuApi(sku.id, {
      ingredients: (sku.ingredients || []).map((ing) => ({
        material: ing.material,
        quantity: ing.quantity,
        unit: ing.unit,
      })) as any,
    })
    ElMessage.success(`规格 [${sku.template_name}] 配方已更新`)
    fetchItems()
  } finally {
    savingSkuId.value = null
  }
}

onMounted(() => {
  fetchItems()
})
</script>

<style scoped>
.form-section-card {
  border-radius: 8px;
  background-color: #fafafa;
}
.section-title {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
}
.image-upload-box {
  background: #ffffff;
  padding: 14px;
  border-radius: 6px;
  border: 1px solid #ebeef5;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.box-title {
  font-weight: 600;
  font-size: 13px;
  color: #303133;
}
.box-sub {
  font-size: 11px;
  color: #909399;
  margin-bottom: 8px;
}
.img-preview {
  border: 1px dashed #dcdfe6;
  border-radius: 6px;
  background: #f8fafc;
  display: flex;
  justify-content: center;
  align-items: center;
  overflow: hidden;
  margin-bottom: 10px;
}
.square-box {
  width: 140px;
  height: 140px;
}
.detail-box {
  width: 140px;
  height: 180px;
}
.preview-inner {
  width: 100%;
  height: 100%;
}
.empty-txt {
  color: #c0c4cc;
  font-size: 12px;
}
.btn-group {
  display: flex;
  gap: 8px;
  align-items: center;
}
</style>
