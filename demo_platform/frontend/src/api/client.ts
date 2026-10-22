import axios, { AxiosError } from 'axios'

export interface ApiErrorShape {
  code: string
  message: string
  status?: number
}

export class ApiError extends Error implements ApiErrorShape {
  code: string
  status?: number

  constructor(shape: ApiErrorShape) {
    super(shape.message)
    this.name = 'ApiError'
    this.code = shape.code
    this.status = shape.status
  }
}

export const http = axios.create({ baseURL: '/api', timeout: 60000 })

http.interceptors.response.use(
  (response) => response,
  (error: AxiosError<any>) => {
    const payload = error.response?.data
    const envelope = payload?.error
    if (envelope?.message) {
      return Promise.reject(
        new ApiError({
          code: envelope.code ?? 'HTTP_ERROR',
          message: envelope.message,
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
        message: error.code === 'ECONNABORTED' ? '请求超时，请重试' : '网络错误：无法连接演示平台后端',
      }),
    )
  },
)

export function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return String(error)
}
