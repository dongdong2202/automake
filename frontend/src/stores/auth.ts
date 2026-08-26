import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { loginApi, type LoginParams } from '@/api/auth'
import type { UserInfo } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(localStorage.getItem('access_token') || '')
  const user = ref<UserInfo | null>((() => {
    try {
      const stored = localStorage.getItem('user_info')
      return stored ? JSON.parse(stored) : null
    } catch {
      return null
    }
  })())
  const selectedStoreId = ref<number | ''>((() => {
    const s = localStorage.getItem('selected_store_id')
    return s ? Number(s) : ''
  })())

  const isLoggedIn = computed(() => !!token.value && !!user.value)

  async function login(params: LoginParams) {
    const res = await loginApi(params)
    if (res.data) {
      token.value = res.data.access
      user.value = res.data.user
      localStorage.setItem('access_token', res.data.access)
      localStorage.setItem('refresh_token', res.data.refresh)
      localStorage.setItem('user_info', JSON.stringify(res.data.user))

      // 默认选择第一个门店
      if (res.data.user.stores && res.data.user.stores.length > 0) {
        selectedStoreId.value = res.data.user.stores[0].id
        localStorage.setItem('selected_store_id', String(selectedStoreId.value))
      }
    }
    return res
  }

  function setStore(storeId: number | '') {
    selectedStoreId.value = storeId
    if (storeId) {
      localStorage.setItem('selected_store_id', String(storeId))
    } else {
      localStorage.removeItem('selected_store_id')
    }
  }

  function logout() {
    token.value = ''
    user.value = null
    selectedStoreId.value = ''
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('user_info')
    localStorage.removeItem('selected_store_id')
  }

  return {
    token,
    user,
    selectedStoreId,
    isLoggedIn,
    login,
    logout,
    setStore,
  }
})
