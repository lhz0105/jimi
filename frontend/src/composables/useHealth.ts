import { onMounted, onScopeDispose, ref } from 'vue'

import { fetchHealth } from '@/api/admin'
import { errorText } from '@/api/client'
import type { HealthResponse } from '@/api/types'

const POLL_INTERVAL_MS = 15000

const health = ref<HealthResponse | null>(null)
const healthError = ref<string | null>(null)
let timer: number | null = null

/** 全局健康状态（顶栏状态灯 + 系统页共用），组件挂载时启动轮询。 */
export function useHealth() {
  async function refresh(): Promise<void> {
    try {
      health.value = await fetchHealth()
      healthError.value = null
    } catch (error) {
      healthError.value = errorText(error)
    }
  }

  onMounted(() => {
    void refresh()
    if (timer === null) {
      timer = window.setInterval(() => void refresh(), POLL_INTERVAL_MS)
    }
  })

  onScopeDispose(() => {
    if (timer !== null) {
      window.clearInterval(timer)
      timer = null
    }
  })

  return { health, healthError, refresh }
}
