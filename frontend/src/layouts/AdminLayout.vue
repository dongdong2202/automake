<template>
  <el-container class="layout-container">
    <!-- 左侧菜单栏 -->
    <el-aside :width="isCollapse ? '64px' : '230px'" class="layout-aside">
      <div class="logo-box">
        <el-icon class="logo-icon"><CoffeeCup /></el-icon>
        <span v-if="!isCollapse" class="logo-text">AutoMake 运营平台</span>
      </div>

      <el-scrollbar>
        <el-menu
          :default-active="activeRoute"
          :collapse="isCollapse"
          background-color="#001529"
          text-color="#c0c4cc"
          active-text-color="#409EFF"
          router
          class="sidebar-menu"
        >
          <!-- 驾驶舱 -->
          <el-menu-item index="/dashboard">
            <el-icon><Odometer /></el-icon>
            <template #title>运营驾驶舱</template>
          </el-menu-item>

          <!-- 📈 数据分析中心 (全套图表与监控) -->
          <el-sub-menu index="analytics">
            <template #title>
              <el-icon><DataAnalysis /></el-icon>
              <span>数据分析中心</span>
            </template>
            <el-menu-item index="/analytics/sales">
              <el-icon><TrendCharts /></el-icon>
              <template #title>销售业绩分析</template>
            </el-menu-item>
            <el-menu-item index="/analytics/finance">
              <el-icon><Money /></el-icon>
              <template #title>财务状况概览</template>
            </el-menu-item>
            <el-menu-item index="/analytics/products">
              <el-icon><GobletSquareFull /></el-icon>
              <template #title>产品与品类分析</template>
            </el-menu-item>
            <el-menu-item index="/analytics/devices">
              <el-icon><Monitor /></el-icon>
              <template #title>设备运维分析</template>
            </el-menu-item>
            <el-menu-item index="/analytics/materials">
              <el-icon><Box /></el-icon>
              <template #title>物料进销存分析</template>
            </el-menu-item>
            <el-menu-item index="/analytics/customers">
              <el-icon><User /></el-icon>
              <template #title>客户与复购分析</template>
            </el-menu-item>
          </el-sub-menu>

          <!-- 🖥 实时监控大屏 -->
          <el-menu-item index="/monitor">
            <el-icon><Platform /></el-icon>
            <template #title>实时监控大屏</template>
          </el-menu-item>

          <!-- ⚙️ 业务运营管理 -->
          <el-sub-menu index="management">
            <template #title>
              <el-icon><Management /></el-icon>
              <span>业务运营管理</span>
            </template>

            <!-- 设备管理 (超管/店长) - 包含设备档案、设备型号、设备菜单定制、设备海报屏保 4 大平行卡片 -->
            <el-menu-item v-if="!isMaterialAdmin" index="/devices">
              <el-icon><Cpu /></el-icon>
              <template #title>设备综合管理</template>
            </el-menu-item>

            <!-- 门店管理 (超管/店长) - 包含门店档案管理、门店库存管理、门店调拨流水 3 大平行卡片 -->
            <el-menu-item v-if="!isMaterialAdmin" index="/stores">
              <el-icon><Shop /></el-icon>
              <template #title>门店管理</template>
            </el-menu-item>

            <!-- 库存管理 (物料员/超管) - 包含物料仓库档案、进出库流水记录 2 大平行卡片 -->
            <el-menu-item v-if="isSuperAdmin || isMaterialAdmin" index="/inventory">
              <el-icon><TakeawayBox /></el-icon>
              <template #title>库存管理</template>
            </el-menu-item>

            <!-- 菜单与规格配方管理 (超管/店长) - 包含全局商品、规格模板、品类分类 3 大平行卡片 -->
            <el-menu-item v-if="isSuperAdmin" index="/menus">
              <el-icon><Food /></el-icon>
              <template #title>全局菜单档案管理</template>
            </el-menu-item>

            <!-- 订单管理 (超管/店长) -->
            <el-menu-item v-if="!isMaterialAdmin" index="/orders">
              <el-icon><List /></el-icon>
              <template #title>订单与履约列表</template>
            </el-menu-item>

            <!-- 告警通知 (全员) -->
            <el-menu-item index="/notifications">
              <el-icon><Bell /></el-icon>
              <template #title>
                <span>异常告警事件</span>
                <el-badge
                  v-if="appStore.unhandledAlarmsCount > 0"
                  :value="appStore.unhandledAlarmsCount"
                  type="danger"
                  class="menu-badge"
                />
              </template>
            </el-menu-item>
          </el-sub-menu>

          <!-- 🔧 系统管理 (超管专属) -->
          <el-sub-menu v-if="isSuperAdmin" index="system">
            <template #title>
              <el-icon><Setting /></el-icon>
              <span>系统权限设置</span>
            </template>
            <el-menu-item index="/users">
              <el-icon><Avatar /></el-icon>
              <template #title>管理员账号管理</template>
            </el-menu-item>
          </el-sub-menu>
        </el-menu>
      </el-scrollbar>
    </el-aside>

    <el-container class="main-container">
      <!-- 顶部 Header -->
      <el-header height="56px" class="layout-header">
        <div class="header-left">
          <el-button
            type="text"
            class="collapse-btn"
            @click="appStore.toggleSidebar"
          >
            <el-icon :size="20">
              <Expand v-if="isCollapse" />
              <Fold v-else />
            </el-icon>
          </el-button>

          <!-- 门店快速切换选择器 -->
          <div class="store-selector">
            <span class="selector-label">当前运营视角：</span>
            <el-select
              v-model="authStore.selectedStoreId"
              placeholder="全部门店"
              size="default"
              clearable
              class="store-select"
              @change="handleStoreChange"
            >
              <el-option
                v-for="store in availableStores"
                :key="store.id"
                :label="`${store.name} (ID: ${store.id})`"
                :value="store.id"
              />
            </el-select>
          </div>
        </div>

        <div class="header-right">
          <!-- 告警铃铛 -->
          <el-tooltip content="未处理告警事件" placement="bottom">
            <div class="alarm-bell" @click="$router.push('/notifications')">
              <el-badge :value="appStore.unhandledAlarmsCount" :hidden="appStore.unhandledAlarmsCount === 0" type="danger">
                <el-icon :size="20"><Bell /></el-icon>
              </el-badge>
            </div>
          </el-tooltip>

          <!-- 角色标签 -->
          <el-tag :type="roleTagType" size="small" effect="plain" class="role-tag">
            {{ roleName }}
          </el-tag>

          <!-- 用户名与退出菜单 -->
          <el-dropdown trigger="click" @command="handleUserCommand">
            <span class="user-dropdown-link">
              <el-avatar :size="28" icon="UserFilled" class="user-avatar" />
              <span class="username">{{ authStore.user?.username || '运营人员' }}</span>
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile">个人资料</el-dropdown-item>
                <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <!-- 内容主体 -->
      <el-main class="layout-main">
        <router-view v-slot="{ Component }">
          <transition name="fade-transform" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Odometer,
  DataAnalysis,
  TrendCharts,
  Money,
  GobletSquareFull,
  Monitor,
  Box,
  User,
  Platform,
  Management,
  Cpu,
  TakeawayBox,
  Tickets,
  Shop,
  Food,
  Dish,
  List,
  Bell,
  Setting,
  Avatar,
  Expand,
  Fold,
  ArrowDown,
  CoffeeCup,
  UserFilled,
  Files,
  Operation,
  Picture,
  SetUp
} from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useAppStore } from '@/stores/app'
import { usePermission } from '@/composables/usePermission'
import { useWebSocket } from '@/composables/useWebSocket'
import { useMonitorStore } from '@/stores/monitor'
import { getNotifyEventsApi } from '@/api/notifications'
import { getStoresApi } from '@/api/stores'
import { ref } from 'vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const appStore = useAppStore()
const monitorStore = useMonitorStore()
const { isSuperAdmin, isMaterialAdmin, roleName } = usePermission()

const isCollapse = computed(() => appStore.isCollapse)
const activeRoute = computed(() => route.path)
const availableStores = ref<any[]>(authStore.user?.stores || [])

const roleTagType = computed(() => {
  if (isSuperAdmin.value) return 'danger'
  if (isMaterialAdmin.value) return 'warning'
  return 'primary'
})

async function fetchAvailableStores() {
  if (isSuperAdmin.value) {
    try {
      const res = await getStoresApi({ page_size: 200 })
      if (res.data) {
        availableStores.value = res.data.results || []
      }
    } catch (e) {
      availableStores.value = authStore.user?.stores || []
    }
  } else {
    availableStores.value = authStore.user?.stores || []
  }
}

function handleStoreChange(val: number | '') {
  authStore.setStore(val)
  // 刷新当前页面路由以重新获取特定门店数据
  window.location.reload()
}

function handleUserCommand(command: string) {
  if (command === 'logout') {
    authStore.logout()
    router.push('/login')
  }
}

// 建立全局实时 WebSocket 接收设备状态广播
useWebSocket('/ws/monitor/', (data) => {
  monitorStore.updateDeviceStatus(data)
})

// 初始拉取未处理告警数量
async function fetchAlarmsCount() {
  try {
    const res = await getNotifyEventsApi({ is_handled: 'false' })
    if (res.data) {
      appStore.setUnhandledAlarms(res.data.count || 0)
    }
  } catch (e) {
    // 忽略异常
  }
}

onMounted(() => {
  fetchAlarmsCount()
  fetchAvailableStores()
})
</script>

<style scoped lang="scss">
.layout-container {
  width: 100vw;
  height: 100vh;
  overflow: hidden;
}

.layout-aside {
  background-color: #001529;
  transition: width 0.3s cubic-bezier(0.2, 0, 0, 1);
  display: flex;
  flex-direction: column;
  box-shadow: 2px 0 6px rgba(0, 21, 41, 0.2);
  z-index: 10;

  .logo-box {
    height: 56px;
    display: flex;
    align-items: center;
    padding: 0 16px;
    background: #002140;
    color: #ffffff;
    gap: 10px;
    overflow: hidden;
    white-space: nowrap;

    .logo-icon {
      font-size: 24px;
      color: #409EFF;
    }

    .logo-text {
      font-size: 15px;
      font-weight: bold;
      letter-spacing: 0.5px;
    }
  }

  .sidebar-menu {
    border-right: none;
  }
}

.menu-badge {
  margin-left: 8px;
}

.main-container {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.layout-header {
  background: #ffffff;
  border-bottom: 1px solid #e8e8e8;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.05);

  .header-left {
    display: flex;
    align-items: center;
    gap: 16px;

    .collapse-btn {
      color: #595959;
      padding: 0;
      font-size: 18px;
    }

    .store-selector {
      display: flex;
      align-items: center;
      gap: 6px;

      .selector-label {
        font-size: 13px;
        color: #595959;
      }

      .store-select {
        width: 180px;
      }
    }
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 16px;

    .alarm-bell {
      cursor: pointer;
      color: #595959;
      display: flex;
      align-items: center;
      padding: 6px;
      border-radius: 4px;
      transition: background 0.2s;

      &:hover {
        background: #f5f5f5;
        color: #409EFF;
      }
    }

    .role-tag {
      font-weight: 500;
    }

    .user-dropdown-link {
      display: flex;
      align-items: center;
      gap: 8px;
      cursor: pointer;
      color: #333333;
      font-size: 14px;

      .user-avatar {
        background: #409EFF;
      }

      .username {
        font-weight: 500;
      }
    }
  }
}

.layout-main {
  background-color: #f0f2f5;
  padding: 16px 20px;
  overflow-y: auto;
}

/* 页面切换淡入淡出动画 */
.fade-transform-leave-active,
.fade-transform-enter-active {
  transition: all 0.25s;
}
.fade-transform-enter-from {
  opacity: 0;
  transform: translateY(10px);
}
.fade-transform-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}
</style>
