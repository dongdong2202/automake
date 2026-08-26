import http from './index'
import type { ApiResponse, PaginatedData, NotifyEventItem } from '@/types'

export function getNotifyEventsApi(params?: any): Promise<ApiResponse<PaginatedData<NotifyEventItem>>> {
  return http.get('/admin/notifications/events/', { params })
}

export function handleNotifyEventApi(id: number | string): Promise<ApiResponse<any>> {
  return http.post(`/admin/notifications/events/${id}/handle/`)
}
