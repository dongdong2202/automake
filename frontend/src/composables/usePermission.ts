import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'

export function usePermission() {
  const authStore = useAuthStore()

  const isSuperAdmin = computed(() => authStore.user?.role === 'super_admin')
  const isMaterialAdmin = computed(() => authStore.user?.role === 'material_admin')
  const isStoreAdmin = computed(() => authStore.user?.role === 'admin')
  const roleName = computed(() => {
    switch (authStore.user?.role) {
      case 'super_admin':
        return '超级管理员'
      case 'material_admin':
        return '物料员'
      case 'admin':
        return '店面管理员'
      default:
        return '运营人员'
    }
  })

  function hasRole(roles: string[]): boolean {
    if (!authStore.user) return false
    if (authStore.user.role === 'super_admin') return true
    return roles.includes(authStore.user.role)
  }

  return {
    isSuperAdmin,
    isMaterialAdmin,
    isStoreAdmin,
    roleName,
    hasRole,
  }
}
