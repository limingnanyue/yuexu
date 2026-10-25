import axios from 'axios'
import { ElMessage } from 'element-plus'

const request = axios.create({
  baseURL: '/api',
  timeout: 60000,
})

request.interceptors.request.use((config) => {
  const token = localStorage.getItem('yuexu_token')
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

request.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const status = error.response?.status
    const data = error.response?.data
    const message = data?.message || data?.detail || error.message || '请求失败'

    if (status === 401) {
      localStorage.removeItem('yuexu_token')
      localStorage.removeItem('yuexu_user')
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`
      }
    } else if (!error.config?.silent) {
      ElMessage.error(message)
    }
    return Promise.reject(error)
  },
)

export default request
