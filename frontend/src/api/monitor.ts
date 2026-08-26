import http from './index'
import type { ApiResponse } from '@/types'

export function getMonitorDevicesApi(): Promise<ApiResponse<any[]>> {
  return http.get('/monitor/devices/')
}

export function getMonitorDeviceDetailApi(sn: string): Promise<ApiResponse<any>> {
  return http.get(`/monitor/devices/${sn}/`)
}
