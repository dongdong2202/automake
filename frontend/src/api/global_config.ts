import http from './index'
import type { ApiResponse, DeviceModelItem } from '@/types'

export function getDeviceModelsApi(): Promise<ApiResponse<DeviceModelItem[]>> {
  return http.get('/admin/global-config/device-models/')
}

export function createDeviceModelApi(data: Partial<DeviceModelItem>): Promise<ApiResponse<DeviceModelItem>> {
  return http.post('/admin/global-config/device-models/', data)
}

export function updateDeviceModelApi(id: number, data: Partial<DeviceModelItem>): Promise<ApiResponse<DeviceModelItem>> {
  return http.put(`/admin/global-config/device-models/${id}/`, data)
}

export function deleteDeviceModelApi(id: number): Promise<ApiResponse<null>> {
  return http.delete(`/admin/global-config/device-models/${id}/`)
}
