import http from './index'
import type { ApiResponse, PaginatedData, UserInfo } from '@/types'

export function getUsersApi(params?: any): Promise<ApiResponse<PaginatedData<UserInfo>>> {
  return http.get('/admin/users/', { params })
}

export function getUserDetailApi(id: number | string): Promise<ApiResponse<UserInfo>> {
  return http.get(`/admin/users/${id}/`)
}

export function createUserApi(data: any): Promise<ApiResponse<UserInfo>> {
  return http.post('/admin/users/', data)
}

export function updateUserApi(id: number | string, data: any): Promise<ApiResponse<UserInfo>> {
  return http.put(`/admin/users/${id}/`, data)
}

export function deleteUserApi(id: number | string): Promise<ApiResponse<any>> {
  return http.delete(`/admin/users/${id}/`)
}
