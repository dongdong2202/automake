import http from './index'
import type { ApiResponse } from '@/types'

export function uploadFileApi(
  file: File,
  type: string = 'posters'
): Promise<ApiResponse<{ url: string; path: string; filename: string; size: number }>> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('type', type)
  return http.post('/admin/upload/', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
}
