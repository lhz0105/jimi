import axios, { AxiosError } from 'axios'
import { ref } from 'vue'

/** 后端地址前缀：留空走同源（Vite 代理）；独立部署时设 VITE_API_BASE。 */
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? ''

const STORAGE_KEY = 'match.admin.apiKey'

/** 管理接口密钥（后端配置了 ADMIN_API_KEY 时需要；未配置时本机免鉴权）。 */
export const apiKey = ref<string>(localStorage.getItem(STORAGE_KEY) ?? '')

export function setApiKey(value: string): void {
  apiKey.value = value.trim()
  if (apiKey.value) localStorage.setItem(STORAGE_KEY, apiKey.value)
  else localStorage.removeItem(STORAGE_KEY)
}

export interface ApiErrorShape {
  code: string
  message: string
  detail?: unknown
  status?: number
}

export class ApiError extends Error implements ApiErrorShape {
  code: string
  detail?: unknown
  status?: number

  constructor(shape: ApiErrorShape) {
    super(shape.message)
    this.name = 'ApiError'
    this.code = shape.code
    this.detail = shape.detail
    this.status = shape.status
  }
}

export const http = axios.create({
  baseURL: `${API_BASE}/api`,
  timeout: 20000,
})

http.interceptors.request.use((config) => {
  if (apiKey.value) config.headers.set('X-API-Key', apiKey.value)
  return config
})

http.interceptors.response.use(
  (response) => response,
  (error: AxiosError<any>) => {
    // 后端错误信封：{error: {code, message, detail}}；校验错误为 {error:{code:'VALIDATION_ERROR',...}}
    const payload = error.response?.data
    const envelope = payload?.error
    if (envelope?.message) {
      return Promise.reject(
        new ApiError({
          code: envelope.code ?? 'HTTP_ERROR',
          message: envelope.message,
          detail: envelope.detail,
          status: error.response?.status,
        }),
      )
    }
    if (error.response) {
      return Promise.reject(
        new ApiError({
          code: `HTTP_${error.response.status}`,
          message: `请求失败（HTTP ${error.response.status}）`,
          status: error.response.status,
        }),
      )
    }
    return Promise.reject(
      new ApiError({
        code: 'NETWORK_ERROR',
        message: error.code === 'ECONNABORTED' ? '请求超时，请重试' : '网络错误：无法连接后端服务',
      }),
    )
  },
)

export function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return String(error)
}
