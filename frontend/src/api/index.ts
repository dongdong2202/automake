import axios from 'axios'
import { ElMessage } from 'element-plus'
import nprogress from 'nprogress'
import router from '@/router'
import 'nprogress/nprogress.css'

nprogress.configure({ showSpinner: false })

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/api',
  timeout: 20000,
})

// 请求拦截器
http.interceptors.request.use(
  (config) => {
    nprogress.start()
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    nprogress.done()
    return Promise.reject(error)
  }
)

// 响应拦截器
http.interceptors.response.use(
  (response) => {
    nprogress.done()
    const res = response.data
    // 如果返回了标准格式 code !== 0 视为业务异常
    if (res && typeof res.code === 'number' && res.code !== 0) {
      ElMessage.error(res.message || '请求处理失败')
      return Promise.reject(new Error(res.message || 'Error'))
    }
    return res
  },
  async (error) => {
    nprogress.done()
    const { response } = error

    if (response) {
      if (response.status === 401) {
        // 尝试使用 Refresh Token
        const refreshToken = localStorage.getItem('refresh_token')
        if (refreshToken && !error.config._retry) {
          error.config._retry = true
          try {
            const refreshRes = await axios.post('/api/user/token/refresh', {
              refresh: refreshToken,
            })
            if (refreshRes.data && refreshRes.data.access) {
              const newAccess = refreshRes.data.access
              localStorage.setItem('access_token', newAccess)
              error.config.headers.Authorization = `Bearer ${newAccess}`
              return http(error.config)
            }
          } catch (e) {
            localStorage.removeItem('access_token')
            localStorage.removeItem('refresh_token')
            localStorage.removeItem('user_info')
            window.location.href = '/login'
          }
        } else {          localStorage.removeItem('access_token')
          localStorage.removeItem('refresh_token')
          localStorage.removeItem('user_info')
          router.push({ path: '/login', query: { redirect: router.currentRoute.value.fullPath } })
        }
      } else if (response.status === 403) {
        ElMessage.error('权限不足，无法执行该操作')
      } else if (response.status === 500) {
        ElMessage.error('服务器内部错误，请稍后重试')
      } else {
        const msg = response.data?.message || response.data?.detail || '请求失败'
        ElMessage.error(msg)
      }
    } else {
      ElMessage.error('网络连接超时或异常，请检查网络')
    }

    return Promise.reject(error)
  }
)

export default http
