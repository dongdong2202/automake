import http from './index'
import type { ApiResponse, PaginatedData, StoreItem } from '@/types'

export function getStoresApi(params?: any): Promise<ApiResponse<PaginatedData<StoreItem>>> {
  return http.get('/admin/stores/', { params })
}

export function getStoreDetailApi(id: number | string): Promise<ApiResponse<StoreItem>> {
  return http.get(`/admin/stores/${id}/`)
}

export function createStoreApi(data: any): Promise<ApiResponse<StoreItem>> {
  return http.post('/admin/stores/', data)
}

export function updateStoreApi(id: number | string, data: any): Promise<ApiResponse<StoreItem>> {
  return http.put(`/admin/stores/${id}/`, data)
}

export function deleteStoreApi(id: number | string): Promise<ApiResponse<any>> {
  return http.delete(`/admin/stores/${id}/`)
}

export function getStoreInventoryApi(storeId?: number | string, params?: any): Promise<ApiResponse<PaginatedData<any>>> {
  if (storeId) {
    return http.get(`/admin/stores/${storeId}/inventory/`, { params })
  }
  return http.get('/admin/stores/inventory/', { params })
}

export function dispatchStoreInventoryToDeviceApi(storeId: number | string, data: any): Promise<ApiResponse<any>> {
  return http.post(`/admin/stores/${storeId}/dispatch-to-device/`, data)
}

export function getStoreInventoryRecordsApi(storeId?: number | string, params?: any): Promise<ApiResponse<PaginatedData<any>>> {
  if (storeId) {
    return http.get(`/admin/stores/${storeId}/records/`, { params })
  }
  return http.get('/admin/stores/records/', { params })
}
