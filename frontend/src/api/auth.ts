import http from './index'
import type { ApiResponse, UserInfo } from '@/types'

export interface LoginParams {
  username: string
  password: string
}

export interface LoginResult {
  access: string
  refresh: string
  user: UserInfo
}

export function loginApi(params: LoginParams): Promise<ApiResponse<LoginResult>> {
  return http.post('/user/admin/login', params)
}

export function getProfileApi(): Promise<ApiResponse<UserInfo>> {
  return http.get('/user/profile')
}
