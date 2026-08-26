import http from './index'
import type { ApiResponse } from '@/types'

export interface AnalyticsFilterParams {
  start_date?: string
  end_date?: string
  store_id?: number | string
  device_sn?: string
  granularity?: 'day' | 'week' | 'month'
}

// 1. 销售分析
export function getSalesTrendApi(params?: AnalyticsFilterParams): Promise<ApiResponse<any[]>> {
  return http.get('/admin/analytics/sales/trend', { params })
}

export function getSalesByHourApi(params?: AnalyticsFilterParams): Promise<ApiResponse<any[]>> {
  return http.get('/admin/analytics/sales/by-hour', { params })
}

export function getSalesByWeekdayApi(params?: AnalyticsFilterParams): Promise<ApiResponse<any[]>> {
  return http.get('/admin/analytics/sales/by-weekday', { params })
}

export function getSalesByStoreApi(params?: AnalyticsFilterParams): Promise<ApiResponse<any[]>> {
  return http.get('/admin/analytics/sales/by-store', { params })
}

export function getSalesByDeviceApi(params?: AnalyticsFilterParams): Promise<ApiResponse<any[]>> {
  return http.get('/admin/analytics/sales/by-device', { params })
}

export function getSalesFunnelApi(params?: AnalyticsFilterParams): Promise<ApiResponse<any[]>> {
  return http.get('/admin/analytics/sales/funnel', { params })
}

// 2. 财务概览
export function getFinanceSummaryApi(params?: AnalyticsFilterParams): Promise<ApiResponse<any>> {
  return http.get('/admin/analytics/finance/summary', { params })
}

export function getFinanceTrendApi(params?: AnalyticsFilterParams): Promise<ApiResponse<any[]>> {
  return http.get('/admin/analytics/finance/trend', { params })
}

export function getFinanceCategoryShareApi(params?: AnalyticsFilterParams): Promise<ApiResponse<any[]>> {
  return http.get('/admin/analytics/finance/category-share', { params })
}

// 3. 产品分析
export function getProductRankingApi(params?: AnalyticsFilterParams): Promise<ApiResponse<any[]>> {
  return http.get('/admin/analytics/products/ranking', { params })
}

export function getProductSkuPreferencesApi(params?: AnalyticsFilterParams): Promise<ApiResponse<any[]>> {
  return http.get('/admin/analytics/products/sku-preferences', { params })
}

// 4. 设备运维分析
export function getDeviceUptimeApi(params?: AnalyticsFilterParams): Promise<ApiResponse<any[]>> {
  return http.get('/admin/analytics/devices/uptime', { params })
}

export function getDeviceAlarmTrendApi(params?: AnalyticsFilterParams): Promise<ApiResponse<any[]>> {
  return http.get('/admin/analytics/devices/alarm-trend', { params })
}

// 5. 物料分析
export function getMaterialStockStatusApi(): Promise<ApiResponse<any[]>> {
  return http.get('/admin/analytics/materials/stock-status')
}

export function getMaterialConsumptionTrendApi(params?: AnalyticsFilterParams): Promise<ApiResponse<any[]>> {
  return http.get('/admin/analytics/materials/consumption', { params })
}

export function getMaterialForecastApi(): Promise<ApiResponse<any[]>> {
  return http.get('/admin/analytics/materials/replenishment-forecast')
}

// 6. 客户分析
export function getCustomerGrowthApi(params?: AnalyticsFilterParams): Promise<ApiResponse<any>> {
  return http.get('/admin/analytics/customers/growth', { params })
}

export function getCustomerFrequencyApi(): Promise<ApiResponse<any[]>> {
  return http.get('/admin/analytics/customers/order-frequency')
}
