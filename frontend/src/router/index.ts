import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/login/LoginView.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    component: () => import('@/layouts/AdminLayout.vue'),
    children: [
      {
        path: '',
        redirect: '/dashboard',
      },
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/dashboard/DashboardView.vue'),
        meta: { roles: ['super_admin', 'admin', 'material_admin'], title: '运营驾驶舱' },
      },
      // 📈 数据分析中心 6 大页面
      {
        path: 'analytics/sales',
        name: 'SalesAnalysis',
        component: () => import('@/views/analytics/SalesAnalysis.vue'),
        meta: { roles: ['super_admin', 'admin', 'material_admin'], title: '销售业绩分析' },
      },
      {
        path: 'analytics/finance',
        name: 'FinanceOverview',
        component: () => import('@/views/analytics/FinanceOverview.vue'),
        meta: { roles: ['super_admin', 'admin', 'material_admin'], title: '财务状况概览' },
      },
      {
        path: 'analytics/products',
        name: 'ProductAnalysis',
        component: () => import('@/views/analytics/ProductAnalysis.vue'),
        meta: { roles: ['super_admin', 'admin', 'material_admin'], title: '产品与品类分析' },
      },
      {
        path: 'analytics/devices',
        name: 'DeviceAnalysis',
        component: () => import('@/views/analytics/DeviceAnalysis.vue'),
        meta: { roles: ['super_admin', 'admin', 'material_admin'], title: '设备运维分析' },
      },
      {
        path: 'analytics/materials',
        name: 'MaterialAnalysis',
        component: () => import('@/views/analytics/MaterialAnalysis.vue'),
        meta: { roles: ['super_admin', 'material_admin', 'admin'], title: '物料进销存分析' },
      },
      {
        path: 'analytics/customers',
        name: 'CustomerAnalysis',
        component: () => import('@/views/analytics/CustomerAnalysis.vue'),
        meta: { roles: ['super_admin', 'admin'], title: '客户与复购分析' },
      },

      // 🖥 实时监控
      {
        path: 'monitor',
        name: 'MonitorDashboard',
        component: () => import('@/views/monitor/MonitorDashboard.vue'),
        meta: { roles: ['super_admin', 'admin', 'material_admin'], title: '实时监控大屏' },
      },
      {
        path: 'monitor/:sn',
        name: 'DeviceDetail',
        component: () => import('@/views/monitor/DeviceDetail.vue'),
        meta: { roles: ['super_admin', 'admin', 'material_admin'], title: '设备监控详情' },
      },

      // 业务运营管理
      {
        path: 'devices',
        name: 'DeviceManagement',
        component: () => import('@/views/devices/DeviceManagement.vue'),
        meta: { roles: ['super_admin', 'admin'], title: '设备综合管理' },
      },
      {
        path: 'devices/models',
        redirect: '/devices?tab=models',
      },
      {
        path: 'devices/posters',
        redirect: '/devices?tab=posters',
      },
      {
        path: 'stores',
        name: 'StoreList',
        component: () => import('@/views/stores/StoreList.vue'),
        meta: { roles: ['super_admin', 'admin'], title: '门店管理' },
      },
      {
        path: 'menus',
        name: 'MenuManagement',
        component: () => import('@/views/menus/MenuManagement.vue'),
        meta: { roles: ['super_admin'], title: '全局菜单档案管理' },
      },
      {
        path: 'menus/categories',
        redirect: '/menus?tab=categories',
      },
      {
        path: 'menus/templates',
        redirect: '/menus?tab=templates',
      },
      {
        path: 'menus/store',
        redirect: '/devices?tab=menus',
      },
      {
        path: 'inventory',
        name: 'InventoryManagement',
        component: () => import('@/views/inventory/InventoryManagement.vue'),
        meta: { roles: ['super_admin', 'material_admin'], title: '库存管理' },
      },
      {
        path: 'inventory/records',
        redirect: '/inventory?tab=records',
      },
      {
        path: 'inventory/materials',
        redirect: '/inventory?tab=materials',
      },
      {
        path: 'orders',
        name: 'OrderList',
        component: () => import('@/views/orders/OrderList.vue'),
        meta: { roles: ['super_admin', 'admin'], title: '订单中心' },
      },
      {
        path: 'notifications',
        name: 'AlertList',
        component: () => import('@/views/notifications/AlertList.vue'),
        meta: { roles: ['super_admin', 'admin', 'material_admin'], title: '异常告警' },
      },

      // 系统设置
      {
        path: 'users',
        name: 'UserList',
        component: () => import('@/views/users/UserList.vue'),
        meta: { roles: ['super_admin'], title: '管理员账号' },
      },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, from, next) => {
  const authStore = useAuthStore()

  if (to.meta.public) {
    if (authStore.isLoggedIn && to.path === '/login') {
      return next('/dashboard')
    }
    return next()
  }

  if (!authStore.isLoggedIn) {
    ElMessage.warning('请先登录运营管理账号')
    return next({ path: '/login', query: { redirect: to.fullPath } })
  }

  const allowedRoles = (to.meta.roles as string[]) || []
  if (allowedRoles.length > 0 && authStore.user) {
    if (authStore.user.role !== 'super_admin' && !allowedRoles.includes(authStore.user.role)) {
      ElMessage.error('您当前的账号角色无权访问该功能模块')
      return next('/dashboard')
    }
  }

  next()
})

export default router
