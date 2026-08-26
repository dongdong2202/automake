<template>
  <div class="page-container store-menu-page">
    <PageHeader
      title="门店菜单与差异化定价"
      subtitle="根据门店商圈微调商品售价 (±20% 范围内)、控制商品上下架状态，并支持一键同步最新全局菜谱"
    >
      <template #actions>
        <el-button type="success" icon="Refresh" @click="handleSyncMenu">
          从全局同步最新商品
        </el-button>
      </template>
    </PageHeader>

    <div class="guide-tip">
      💡 提示：门店商品售价允许在全局基准价格的 ±20% 范围内微调。修改价格或滑动“是否上架”开关均会自动实时保存生效。
    </div>

    <div class="chart-card">
      <el-table v-loading="loading" :data="itemList" stripe style="width: 100%">
        <el-table-column prop="store_name" label="所属门店" width="140" />
        <el-table-column prop="global_item_name" label="商品名称" min-width="160" />
        <el-table-column prop="category_name" label="分类" width="120" />
        <el-table-column prop="global_base_price" label="全局基准价" width="120">
          <template #default="{ row }">{{ formatCurrency(row.global_base_price) }}</template>
        </el-table-column>
        <el-table-column label="门店售价 (元)" width="180">
          <template #default="{ row }">
            <el-input-number
              v-model="row.editPriceYuan"
              :min="Number((row.global_base_price * 0.8 / 100).toFixed(2))"
              :max="Number((row.global_base_price * 1.2 / 100).toFixed(2))"
              :step="0.5"
              :precision="2"
              size="small"
              @change="handlePriceChange(row)"
            />
          </template>
        </el-table-column>
        <el-table-column label="是否上架" width="140" align="center">
          <template #default="{ row }">
            <el-switch
              v-model="row.is_active"
              :loading="row.statusLoading"
              active-text="上架"
              inactive-text="下架"
              @change="handleToggleStatus(row)"
            />
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import { getStoreMenuItemsApi, updateStoreMenuItemApi, syncStoreMenuApi } from '@/api/menus'
import { useAuthStore } from '@/stores/auth'
import { fenToYuan, yuanToFen, formatCurrency } from '@/utils/money'

const authStore = useAuthStore()
const loading = ref(false)
const itemList = ref<any[]>([])

async function fetchItems() {
  loading.value = true
  try {
    const res = await getStoreMenuItemsApi()
    if (res.data) {
      itemList.value = (res.data.results || []).map((item: any) => ({
        ...item,
        statusLoading: false,
        editPriceYuan: fenToYuan(item.base_price),
      }))
    }
  } finally {
    loading.value = false
  }
}

async function handleToggleStatus(row: any) {
  row.statusLoading = true
  try {
    await updateStoreMenuItemApi(row.id, {
      is_active: row.is_active,
    })
    ElMessage.success(`商品 [${row.global_item_name}] 已${row.is_active ? '上架' : '下架'}`)
  } catch (e) {
    row.is_active = !row.is_active
  } finally {
    row.statusLoading = false
  }
}

async function handlePriceChange(row: any) {
  try {
    const priceFen = yuanToFen(row.editPriceYuan)
    await updateStoreMenuItemApi(row.id, {
      base_price: priceFen,
    })
    ElMessage.success(`商品 [${row.global_item_name}] 售价已更新为 ¥${row.editPriceYuan.toFixed(2)}`)
  } catch (e) {
    fetchItems()
  }
}

async function handleSyncMenu() {
  const currentStoreId = authStore.selectedStoreId || authStore.user?.stores[0]?.id
  if (!currentStoreId) {
    ElMessage.warning('请先在顶部选择要同步的门店')
    return
  }

  try {
    await syncStoreMenuApi(currentStoreId)
    ElMessage.success('门店菜单已成功同步最新全局商品')
    fetchItems()
  } catch (e) {
    //
  }
}

onMounted(() => {
  fetchItems()
})
</script>

<style scoped>
.guide-tip {
  margin-bottom: 16px;
  padding: 10px 16px;
  background-color: #ecf5ff;
  border-radius: 6px;
  color: #409eff;
  font-size: 13px;
  border: 1px solid #d9ecff;
}
</style>
