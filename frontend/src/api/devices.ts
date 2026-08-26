import http from './index'
import type { ApiResponse, PaginatedData, DeviceItem, BarrelDictItem, PosterItem } from '@/types'

export function getDevicesApi(params?: any): Promise<ApiResponse<PaginatedData<DeviceItem>>> {
  return http.get('/admin/devices/', { params })
}

export function getDeviceDetailApi(sn: string): Promise<ApiResponse<DeviceItem>> {
  return http.get(`/admin/devices/${sn}/`)
}

export function createDeviceApi(data: any): Promise<ApiResponse<DeviceItem>> {
  return http.post('/admin/devices/', data)
}

export function updateDeviceApi(sn: string, data: any): Promise<ApiResponse<DeviceItem>> {
  return http.put(`/admin/devices/${sn}/`, data)
}

export function deleteDeviceApi(sn: string): Promise<ApiResponse<null>> {
  return http.delete(`/admin/devices/${sn}/`)
}

// 单设备料桶
export function getDeviceBarrelsApi(sn: string): Promise<ApiResponse<BarrelDictItem[]>> {
  return http.get(`/admin/devices/${sn}/barrels/`)
}

export function bindDeviceBarrelApi(sn: string, data: { barrel_code: string; material_code: string }): Promise<ApiResponse<BarrelDictItem>> {
  return http.post(`/admin/devices/${sn}/barrels/`, data)
}

// 全局料桶字典映射大表
export function getGlobalBarrelsApi(params?: { device_sn?: string; material_code?: string; search?: string }): Promise<ApiResponse<BarrelDictItem[]>> {
  return http.get('/admin/devices/barrel-dicts/', { params })
}

export function createGlobalBarrelApi(data: { device_sn: string; barrel_code: string; material_code: string }): Promise<ApiResponse<BarrelDictItem>> {
  return http.post('/admin/devices/barrel-dicts/', data)
}

export function deleteBarrelDictApi(id: number): Promise<ApiResponse<null>> {
  return http.delete(`/admin/devices/barrel-dicts/${id}/`)
}

// 海报屏保管理
export function getPostersApi(): Promise<ApiResponse<PosterItem[]>> {
  return http.get('/admin/posters/')
}

export function createPosterApi(data: Partial<PosterItem>): Promise<ApiResponse<PosterItem>> {
  return http.post('/admin/posters/', data)
}

export function updatePosterApi(id: number, data: Partial<PosterItem>): Promise<ApiResponse<PosterItem>> {
  return http.put(`/admin/posters/${id}/`, data)
}

export function deletePosterApi(id: number): Promise<ApiResponse<null>> {
  return http.delete(`/admin/posters/${id}/`)
}

// 设备物料与耗材传感器库存看板
export function getDeviceStocksOverviewApi(params?: { store_id?: number | string; device_sn?: string }): Promise<ApiResponse<any[]>> {
  return http.get('/admin/devices/stocks-overview/', { params })
}

// 设备库存加料调拨流水台账
export function getDeviceInventoryRecordsApi(params?: { store_id?: number | string; device_sn?: string; search?: string; page?: number; page_size?: number }): Promise<ApiResponse<PaginatedData<any>>> {
  return http.get('/admin/devices/records/', { params })
}
