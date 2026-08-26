import http from './index'
import type { ApiResponse, PaginatedData, MaterialItem, InventoryRecordItem } from '@/types'

export function getMaterialsApi(params?: any): Promise<ApiResponse<PaginatedData<MaterialItem>>> {
  return http.get('/admin/inventory/materials/', { params })
}

export function getMaterialDetailApi(id: number | string): Promise<ApiResponse<MaterialItem>> {
  return http.get(`/admin/inventory/materials/${id}/`)
}

export function createMaterialApi(data: any): Promise<ApiResponse<MaterialItem>> {
  return http.post('/admin/inventory/materials/', data)
}

export function updateMaterialApi(id: number | string, data: any): Promise<ApiResponse<MaterialItem>> {
  return http.put(`/admin/inventory/materials/${id}/`, data)
}

export function deleteMaterialApi(id: number | string): Promise<ApiResponse<any>> {
  return http.delete(`/admin/inventory/materials/${id}/`)
}

export function getInventoryRecordsApi(params?: any): Promise<ApiResponse<PaginatedData<InventoryRecordItem>>> {
  return http.get('/admin/inventory/records/', { params })
}

export function createInventoryRecordApi(data: {
  material_id: number | string
  record_type: 'in' | 'out'
  quantity: number | string
  price?: number | string
  store_id?: number | string
  remarks?: string
}): Promise<ApiResponse<InventoryRecordItem>> {
  return http.post('/admin/inventory/records/', data)
}

export function checkInventoryExpirationApi(data?: { days?: number; force?: boolean }): Promise<ApiResponse<any>> {
  return http.post('/admin/inventory/check-expiration/', data || {})
}

export function getExpirationSummaryApi(): Promise<ApiResponse<any>> {
  return http.get('/admin/inventory/expiration-summary/')
}

