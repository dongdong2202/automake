import http from './index'
import type { ApiResponse, PaginatedData, OrderItemRecord } from '@/types'

export function getOrdersApi(params?: any): Promise<ApiResponse<PaginatedData<OrderItemRecord>>> {
  return http.get('/admin/orders/', { params })
}

export function getOrderDetailApi(orderNo: string): Promise<ApiResponse<OrderItemRecord>> {
  return http.get(`/admin/orders/${orderNo}/`)
}

export interface RefundParams {
  refund_type?: 'auto' | 'force'
  reason?: string
  offline?: boolean
  funds_account?: string
}

export function refundOrderApi(orderNo: string, data?: RefundParams): Promise<ApiResponse<any>> {
  return http.post(`/admin/orders/${orderNo}/refund/`, data || {})
}
