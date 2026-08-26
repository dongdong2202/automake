import http from './index'
import type { ApiResponse } from '@/types'

export function getDashboardStatsApi(): Promise<ApiResponse<any>> {
  return http.get('/admin/dashboard/stats')
}
