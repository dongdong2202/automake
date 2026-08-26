<template>
  <div class="page-container poster-list-page">
    <PageHeader
      title="设备海报与轮播屏保 (DevicePoster)"
      subtitle="统一管理设备待机屏保、点单机横幅广告（横屏/竖屏/Banner 3类比例素材），支持多选门店与设备定向投放"
    >
      <template #actions>
        <el-button type="primary" icon="Plus" @click="openCreateDialog">
          + 新建海报配置
        </el-button>
      </template>
    </PageHeader>

    <div class="chart-card">
      <el-table v-loading="loading" :data="posterList" stripe style="width: 100%">
        <el-table-column prop="version" label="版本" width="90" align="center">
          <template #default="{ row }">
            <el-tag size="small" type="success" effect="dark">v{{ row.version }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="title" label="海报配置名称" min-width="160" />

        <el-table-column label="图片缩略图 (横/竖/Banner)" width="200" align="center">
          <template #default="{ row }">
            <div style="display: flex; gap: 6px; justify-content: center; align-items: center;">
              <!-- 横屏 -->
              <el-tooltip content="横屏海报 (Horizontal)" placement="top">
                <el-image
                  v-if="row.horizontal_image"
                  :src="row.horizontal_image"
                  :preview-src-list="[row.horizontal_image]"
                  fit="cover"
                  preview-teleported
                  style="width: 56px; height: 36px; border-radius: 4px; border: 1px solid #dcdfe6; cursor: pointer;"
                />
              </el-tooltip>
              <!-- 竖屏 -->
              <el-tooltip content="竖屏海报 (Vertical)" placement="top">
                <el-image
                  v-if="row.vertical_image"
                  :src="row.vertical_image"
                  :preview-src-list="[row.vertical_image]"
                  fit="cover"
                  preview-teleported
                  style="width: 28px; height: 36px; border-radius: 4px; border: 1px solid #dcdfe6; cursor: pointer;"
                />
              </el-tooltip>
              <!-- Banner -->
              <el-tooltip content="Banner横幅" placement="top">
                <el-image
                  v-if="row.banner_image"
                  :src="row.banner_image"
                  :preview-src-list="[row.banner_image]"
                  fit="cover"
                  preview-teleported
                  style="width: 66px; height: 36px; border-radius: 4px; border: 1px solid #dcdfe6; cursor: pointer;"
                />
              </el-tooltip>

              <span
                v-if="!row.horizontal_image && !row.vertical_image && !row.banner_image"
                style="color: #909399; font-size: 12px;"
              >
                未上传图片
              </span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="适用门店" min-width="160">
          <template #default="{ row }">
            <span v-if="!row.stores_info || row.stores_info.length === 0" style="color: #67C23A; font-weight: 500;">
              全部门店 (全局)
            </span>
            <span v-else>
              {{ row.stores_info.slice(0, 3).map((s: any) => s.name).join('、') }}
              <span v-if="row.stores_info.length > 3" style="color: #909399;">等 {{ row.stores_info.length }} 家</span>
            </span>
          </template>
        </el-table-column>

        <el-table-column label="适用设备" min-width="160">
          <template #default="{ row }">
            <span v-if="!row.devices_info || row.devices_info.length === 0" style="color: #909399;">
              全部设备 (通用)
            </span>
            <span v-else>
              {{ row.devices_info.slice(0, 3).map((d: any) => d.device_name || d.device_sn).join('、') }}
              <span v-if="row.devices_info.length > 3" style="color: #909399;">等 {{ row.devices_info.length }} 台</span>
            </span>
          </template>
        </el-table-column>

        <el-table-column prop="remarks" label="备注" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.remarks || '-' }}</template>
        </el-table-column>

        <el-table-column prop="sort_order" label="排序权重" width="100" align="center" sortable />

        <el-table-column label="是否启用" width="100" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.is_active" @change="handleToggleStatus(row)" />
          </template>
        </el-table-column>

        <el-table-column prop="created_at" label="创建时间" width="170" />

        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="openEditDialog(row)">
              编辑配置
            </el-button>
            <el-popconfirm title="确定删除该海报配置吗？" @confirm="handleDelete(row.id)">
              <template #reference>
                <el-button type="danger" link size="small">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 新增/编辑海报对话框 (参照 Django Admin DevicePosterAdmin 设计) -->
    <el-dialog
      v-model="showDialog"
      :title="isEdit ? `编辑海报配置 (ID: ${currentId})` : '新建海报配置'"
      width="780px"
      top="4vh"
    >
      <el-form :model="formData" label-position="top">
        <!-- 分区 1: 基本配置 -->
        <el-card shadow="never" class="form-section-card">
          <template #header>
            <span class="section-title">📌 基本配置</span>
          </template>
          <el-row :gutter="16">
            <el-col :span="16">
              <el-form-item label="海报配置名称" required>
                <el-input v-model="formData.title" placeholder="例如：秋季新品推广、默认轮播海报等" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="版本号 (整数唯一)">
                <el-input-number
                  v-model="formData.version"
                  :min="1"
                  :step="1"
                  placeholder="留空自动在最大版本+1"
                  style="width: 100%;"
                />
              </el-form-item>
            </el-col>
          </el-row>

          <el-row :gutter="16">
            <el-col :span="16">
              <el-form-item label="备注说明">
                <el-input v-model="formData.remarks" placeholder="例如：秋季开业海报、中秋限定海报等" />
              </el-form-item>
            </el-col>
            <el-col :span="4">
              <el-form-item label="排序权重">
                <el-input-number v-model="formData.sort_order" :min="0" :max="999" style="width: 100%;" />
              </el-form-item>
            </el-col>
            <el-col :span="4">
              <el-form-item label="是否启用">
                <el-switch v-model="formData.is_active" active-text="启用" inactive-text="下架" />
              </el-form-item>
            </el-col>
          </el-row>
        </el-card>

        <!-- 分区 2: 海报图片上传 (3个独立上传项与预览) -->
        <el-card shadow="never" class="form-section-card" style="margin-top: 14px;">
          <template #header>
            <span class="section-title">🖼 海报图片上传 (3个独立上传项)</span>
          </template>

          <el-row :gutter="16">
            <!-- 横屏海报 -->
            <el-col :span="8">
              <div class="poster-upload-box">
                <div class="upload-label">横屏海报 (horizontal)</div>
                <div class="upload-desc">用于横屏点单机/待机屏保</div>
                <div class="preview-container horizontal-box">
                  <el-image
                    v-if="formData.horizontal_image"
                    :src="formData.horizontal_image"
                    fit="contain"
                    class="preview-img"
                  />
                  <div v-else class="empty-tip">暂无图片</div>
                </div>
                <div class="upload-actions">
                  <el-upload
                    action=""
                    :auto-upload="false"
                    :show-file-list="false"
                    :on-change="(file: any) => handleUploadFile(file, 'horizontal_image')"
                  >
                    <el-button size="small" type="primary" icon="Upload">上传横屏</el-button>
                  </el-upload>
                  <el-button
                    v-if="formData.horizontal_image"
                    size="small"
                    type="danger"
                    link
                    @click="formData.horizontal_image = ''"
                  >
                    清空
                  </el-button>
                </div>
                <el-input
                  v-model="formData.horizontal_image"
                  size="small"
                  placeholder="或直接粘贴图片 URL"
                  style="margin-top: 6px;"
                />
              </div>
            </el-col>

            <!-- 竖屏海报 -->
            <el-col :span="8">
              <div class="poster-upload-box">
                <div class="upload-label">竖屏海报 (vertical)</div>
                <div class="upload-desc">用于竖屏机器/立式屏幕</div>
                <div class="preview-container vertical-box">
                  <el-image
                    v-if="formData.vertical_image"
                    :src="formData.vertical_image"
                    fit="contain"
                    class="preview-img"
                  />
                  <div v-else class="empty-tip">暂无图片</div>
                </div>
                <div class="upload-actions">
                  <el-upload
                    action=""
                    :auto-upload="false"
                    :show-file-list="false"
                    :on-change="(file: any) => handleUploadFile(file, 'vertical_image')"
                  >
                    <el-button size="small" type="primary" icon="Upload">上传竖屏</el-button>
                  </el-upload>
                  <el-button
                    v-if="formData.vertical_image"
                    size="small"
                    type="danger"
                    link
                    @click="formData.vertical_image = ''"
                  >
                    清空
                  </el-button>
                </div>
                <el-input
                  v-model="formData.vertical_image"
                  size="small"
                  placeholder="或直接粘贴图片 URL"
                  style="margin-top: 6px;"
                />
              </div>
            </el-col>

            <!-- Banner海报 -->
            <el-col :span="8">
              <div class="poster-upload-box">
                <div class="upload-label">横幅海报 (banner)</div>
                <div class="upload-desc">用于小程序顶部横幅/通栏广告</div>
                <div class="preview-container banner-box">
                  <el-image
                    v-if="formData.banner_image"
                    :src="formData.banner_image"
                    fit="contain"
                    class="preview-img"
                  />
                  <div v-else class="empty-tip">暂无图片</div>
                </div>
                <div class="upload-actions">
                  <el-upload
                    action=""
                    :auto-upload="false"
                    :show-file-list="false"
                    :on-change="(file: any) => handleUploadFile(file, 'banner_image')"
                  >
                    <el-button size="small" type="primary" icon="Upload">上传Banner</el-button>
                  </el-upload>
                  <el-button
                    v-if="formData.banner_image"
                    size="small"
                    type="danger"
                    link
                    @click="formData.banner_image = ''"
                  >
                    清空
                  </el-button>
                </div>
                <el-input
                  v-model="formData.banner_image"
                  size="small"
                  placeholder="或直接粘贴图片 URL"
                  style="margin-top: 6px;"
                />
              </div>
            </el-col>
          </el-row>
        </el-card>

        <!-- 分区 3: 适用范围 (门店与设备多选) -->
        <el-card shadow="never" class="form-section-card" style="margin-top: 14px;">
          <template #header>
            <span class="section-title">🏢 适用范围 (门店与设备多选)</span>
            <span style="color: #909399; font-size: 12px; margin-left: 10px;">
              留空则表示对全系统所有门店与设备全局生效
            </span>
          </template>

          <el-form-item label="指定适用门店 (多选)">
            <el-select
              v-model="formData.stores"
              multiple
              filterable
              placeholder="留空表示全部门店生效"
              style="width: 100%;"
            >
              <el-option
                v-for="s in storeOptions"
                :key="s.id"
                :label="`${s.name} (ID: ${s.id})`"
                :value="s.id"
              />
            </el-select>
          </el-form-item>

          <el-form-item label="指定适用设备 (多选)">
            <el-select
              v-model="formData.devices"
              multiple
              filterable
              placeholder="留空表示全部设备通用"
              style="width: 100%;"
            >
              <el-option
                v-for="d in deviceOptions"
                :key="d.id"
                :label="`${d.device_name || '咖啡机'} (${d.device_sn})`"
                :value="d.id"
              />
            </el-select>
          </el-form-item>
        </el-card>

        <!-- 分区 4: 审计信息 (编辑时展示) -->
        <div v-if="isEdit" style="margin-top: 10px; color: #909399; font-size: 12px; text-align: right;">
          创建时间：{{ formData.created_at || '-' }} | 最后更新：{{ formData.updated_at || '-' }}
        </div>
      </el-form>

      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" :loading="submitLoading" @click="handleSubmit">
          确认保存配置
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { Plus, Upload } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import { getPostersApi, createPosterApi, updatePosterApi, deletePosterApi, getDevicesApi } from '@/api/devices'
import { getStoresApi } from '@/api/stores'
import { uploadFileApi } from '@/api/common'
import type { PosterItem, StoreItem, DeviceItem } from '@/types'

const loading = ref(false)
const posterList = ref<PosterItem[]>([])
const storeOptions = ref<StoreItem[]>([])
const deviceOptions = ref<DeviceItem[]>([])

const showDialog = ref(false)
const isEdit = ref(false)
const submitLoading = ref(false)
const currentId = ref<number | null>(null)

const formData = reactive<any>({
  title: '',
  version: undefined,
  remarks: '',
  sort_order: 0,
  is_active: true,
  horizontal_image: '',
  vertical_image: '',
  banner_image: '',
  stores: [],
  devices: [],
  created_at: '',
  updated_at: '',
})

async function fetchPosters() {
  loading.value = true
  try {
    const res = await getPostersApi()
    if (res.data) {
      posterList.value = res.data
    }
  } finally {
    loading.value = false
  }
}

async function loadOptions() {
  try {
    const [storeRes, devRes] = await Promise.all([
      getStoresApi({ page_size: 200 }),
      getDevicesApi({ page_size: 200 }),
    ])
    if (storeRes.data) storeOptions.value = storeRes.data.results || []
    if (devRes.data) deviceOptions.value = devRes.data.results || []
  } catch (e) {
    //
  }
}

function openCreateDialog() {
  isEdit.value = false
  currentId.value = null
  loadOptions()
  Object.assign(formData, {
    title: '',
    version: undefined,
    remarks: '',
    sort_order: 0,
    is_active: true,
    horizontal_image: '',
    vertical_image: '',
    banner_image: '',
    stores: [],
    devices: [],
    created_at: '',
    updated_at: '',
  })
  showDialog.value = true
}

function openEditDialog(row: PosterItem) {
  isEdit.value = true
  currentId.value = row.id
  loadOptions()
  Object.assign(formData, {
    title: row.title,
    version: row.version,
    remarks: row.remarks || '',
    sort_order: row.sort_order || 0,
    is_active: row.is_active,
    horizontal_image: row.horizontal_image || '',
    vertical_image: row.vertical_image || '',
    banner_image: row.banner_image || '',
    stores: row.stores || [],
    devices: row.devices || [],
    created_at: row.created_at || '',
    updated_at: row.updated_at || '',
  })
  showDialog.value = true
}

async function handleUploadFile(uploadFile: any, field: 'horizontal_image' | 'vertical_image' | 'banner_image') {
  const rawFile = uploadFile.raw
  if (!rawFile) return

  try {
    const res = await uploadFileApi(rawFile, 'posters')
    if (res.data && res.data.url) {
      formData[field] = res.data.url
      ElMessage.success('图片上传成功并已实时预览')
    }
  } catch (e) {
    ElMessage.error('图片上传失败，请稍后重试')
  }
}

async function handleSubmit() {
  if (!formData.title) {
    ElMessage.warning('海报配置名称为必填项')
    return
  }

  submitLoading.value = true
  try {
    const payload: any = {
      title: formData.title,
      remarks: formData.remarks,
      sort_order: formData.sort_order,
      is_active: formData.is_active,
      horizontal_image: formData.horizontal_image || null,
      vertical_image: formData.vertical_image || null,
      banner_image: formData.banner_image || null,
      stores: formData.stores,
      devices: formData.devices,
    }

    if (formData.version) {
      payload.version = formData.version
    }

    if (isEdit.value && currentId.value) {
      await updatePosterApi(currentId.value, payload)
      ElMessage.success('海报配置已更新')
    } else {
      await createPosterApi(payload)
      ElMessage.success('海报配置已保存')
    }
    showDialog.value = false
    fetchPosters()
  } finally {
    submitLoading.value = false
  }
}

async function handleToggleStatus(row: PosterItem) {
  try {
    await updatePosterApi(row.id, { is_active: row.is_active })
    ElMessage.success(`海报 [${row.title}] 状态已更新`)
  } catch (e) {
    row.is_active = !row.is_active
  }
}

async function handleDelete(id: number) {
  try {
    await deletePosterApi(id)
    ElMessage.success('海报配置已删除')
    fetchPosters()
  } catch (e) {
    //
  }
}

onMounted(() => {
  fetchPosters()
  loadOptions()
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
.poster-upload-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  background: #ffffff;
  padding: 12px;
  border-radius: 6px;
  border: 1px solid #ebeef5;
}
.upload-label {
  font-weight: 600;
  font-size: 13px;
  color: #303133;
}
.upload-desc {
  font-size: 11px;
  color: #909399;
  margin-bottom: 8px;
}
.preview-container {
  display: flex;
  justify-content: center;
  align-items: center;
  border: 1px dashed #dcdfe6;
  border-radius: 6px;
  background: #f8fafc;
  overflow: hidden;
  margin-bottom: 8px;
}
.horizontal-box {
  width: 180px;
  height: 100px;
}
.vertical-box {
  width: 100px;
  height: 130px;
}
.banner-box {
  width: 200px;
  height: 60px;
}
.preview-img {
  width: 100%;
  height: 100%;
}
.empty-tip {
  color: #c0c4cc;
  font-size: 12px;
}
.upload-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}
</style>
