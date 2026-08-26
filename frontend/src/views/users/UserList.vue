<template>
  <div class="page-container user-list-page">
    <PageHeader
      title="运营管理员账号权限"
      subtitle="管理系统超级管理员、门店管理员及物料员账号，分配关联门店与权限范围"
    >
      <template #actions>
        <el-button type="primary" icon="Plus" @click="openCreateDialog">
          + 创建运营管理员
        </el-button>
      </template>
    </PageHeader>

    <div class="chart-card">
      <el-table v-loading="loading" :data="userList" stripe style="width: 100%">
        <el-table-column prop="id" label="用户ID" width="90" align="center" />
        <el-table-column prop="username" label="用户名" min-width="150" />
        <el-table-column prop="role" label="运营角色" width="140">
          <template #default="{ row }">
            <el-tag
              :type="row.role === 'super_admin' ? 'danger' : row.role === 'material_admin' ? 'warning' : 'primary'"
              size="small"
            >
              {{ row.role_display || row.role }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="phone" label="联系手机号" width="140">
          <template #default="{ row }">{{ row.phone || '-' }}</template>
        </el-table-column>
        <el-table-column prop="stores_info" label="关联管理门店" min-width="200">
          <template #default="{ row }">
            <span v-if="row.role === 'super_admin'" style="color: #67C23A; font-weight: 500;">全网全局门店</span>
            <span v-else-if="row.stores_info && row.stores_info.length > 0">
              {{ row.stores_info.map((s: any) => s.name).join('，') }}
            </span>
            <span v-else style="color: #909399;">暂未绑定门店</span>
          </template>
        </el-table-column>
        <el-table-column prop="is_active" label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
              {{ row.is_active ? '正常' : '已禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="170" />
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="openEditDialog(row)">
              编辑
            </el-button>
            <el-popconfirm title="确定禁用此账号吗？" @confirm="handleDelete(row.id)">
              <template #reference>
                <el-button type="danger" link size="small">禁用</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 创建/编辑管理员对话框 -->
    <el-dialog
      v-model="showDialog"
      :title="isEdit ? '编辑运营管理员账号' : '创建运营管理员账号'"
      width="560px"
    >
      <el-form :model="formData" label-width="110px">
        <el-form-item label="用户名" required>
          <el-input v-model="formData.username" :disabled="isEdit" placeholder="请输入登录账号" />
        </el-form-item>
        <el-form-item :label="isEdit ? '重置密码' : '登录密码'" :required="!isEdit">
          <el-input
            v-model="formData.password"
            type="password"
            :placeholder="isEdit ? '若不修改密码请留空' : '请输入初始密码'"
            show-password
          />
        </el-form-item>
        <el-form-item label="运营角色" required>
          <el-radio-group v-model="formData.role">
            <el-radio label="admin">店面管理员</el-radio>
            <el-radio label="material_admin">物料员</el-radio>
            <el-radio label="super_admin">超级管理员</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="手机号码">
          <el-input v-model="formData.phone" placeholder="用于接收告警短信" />
        </el-form-item>
        <el-form-item v-if="formData.role !== 'super_admin'" label="关联管理门店">
          <el-select
            v-model="formData.stores"
            multiple
            placeholder="请选择关联门店（可多选）"
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
        <el-form-item v-if="isEdit" label="账号状态">
          <el-switch v-model="formData.is_active" active-text="正常" inactive-text="禁用" />
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
import { getUsersApi, createUserApi, updateUserApi, deleteUserApi } from '@/api/users'
import { getStoresApi } from '@/api/stores'

const loading = ref(false)
const userList = ref<any[]>([])
const storeOptions = ref<any[]>([])

const showDialog = ref(false)
const isEdit = ref(false)
const submitLoading = ref(false)
const currentId = ref<number | null>(null)

const formData = reactive({
  username: '',
  password: '',
  role: 'admin',
  phone: '',
  stores: [] as number[],
  is_active: true,
})

async function fetchUsers() {
  loading.value = true
  try {
    const res = await getUsersApi()
    if (res.data) {
      userList.value = res.data.results || []
    }
  } finally {
    loading.value = false
  }
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

function openCreateDialog() {
  isEdit.value = false
  currentId.value = null
  fetchStores()
  Object.assign(formData, {
    username: '',
    password: '',
    role: 'admin',
    phone: '',
    stores: [],
    is_active: true,
  })
  showDialog.value = true
}

function openEditDialog(row: any) {
  isEdit.value = true
  currentId.value = row.id
  fetchStores()
  Object.assign(formData, {
    username: row.username,
    password: '',
    role: row.role,
    phone: row.phone || '',
    stores: row.stores || [],
    is_active: row.is_active,
  })
  showDialog.value = true
}

async function handleSubmit() {
  if (!formData.username) {
    ElMessage.warning('用户名不能为空')
    return
  }
  if (!isEdit.value && !formData.password) {
    ElMessage.warning('初始登录密码不能为空')
    return
  }

  submitLoading.value = true
  try {
    if (isEdit.value && currentId.value) {
      const payload: any = {
        role: formData.role,
        phone: formData.phone,
        stores: formData.stores,
        is_active: formData.is_active,
      }
      if (formData.password) {
        payload.password = formData.password
      }
      await updateUserApi(currentId.value, payload)
      ElMessage.success('管理员信息更新成功')
    } else {
      await createUserApi(formData)
      ElMessage.success('管理员账号创建成功')
    }
    showDialog.value = false
    fetchUsers()
  } finally {
    submitLoading.value = false
  }
}

async function handleDelete(id: number) {
  try {
    await deleteUserApi(id)
    ElMessage.success('账号已成功禁用')
    fetchUsers()
  } catch (e) {
    //
  }
}

onMounted(() => {
  fetchUsers()
  fetchStores()
})
</script>
