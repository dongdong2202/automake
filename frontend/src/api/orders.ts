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
  funds_account?: string
}

export function refundOrderApi(orderNo: string, data?: RefundParams): Promise<ApiResponse<any>> {
  const endpoint = data?.refund_type === 'force' ? 'force' : 'auto'
  return http.post(`/admin/orders/${orderNo}/refund/${endpoint}/`, data || {})
}

export function autoRefundOrderApi(orderNo: string, data?: Omit<RefundParams, 'refund_type'>): Promise<ApiResponse<any>> {
  return http.post(`/admin/orders/${orderNo}/refund/auto/`, data || {})
}

export function forceRefundOrderApi(orderNo: string, data?: Omit<RefundParams, 'refund_type'>): Promise<ApiResponse<any>> {
  return http.post(`/admin/orders/${orderNo}/refund/force/`, data || {})
}

