import { onScopeDispose, ref } from 'vue'

import { API_BASE, apiKey } from '@/api/client'
import type { RunEvent } from '@/api/types'

const RECONNECT_DELAY_MS = 1500

export interface EventStreamOptions {
  /** 运行 ID（响应式取值） */
  runId: () => string
  /** 流正常结束（服务端关闭）后调用；返回 true 表示运行已终态、无需重连 */
  checkDone?: () => Promise<boolean>
  /** 每收到一条事件的回调（用于滚动等副作用） */
  onEvent?: (event: RunEvent) => void
}

/**
 * 运行事件流（fetch + ReadableStream 实现的 SSE 客户端）。
 * 相比原生 EventSource：支持自定义头（X-API-Key）与断线续传（?from_seq=），
 * 服务端会从 DB 回放缺失事件，因此重连不丢事件。
 */
export function useEventStream(options: EventStreamOptions) {
  const events = ref<RunEvent[]>([])
  const lastSeq = ref(0)
  const state = ref<'idle' | 'connecting' | 'live' | 'paused' | 'done' | 'error'>('idle')
  const error = ref<string | null>(null)

  let running = false
  let controller: AbortController | null = null

  function reset(): void {
    events.value = []
    lastSeq.value = 0
    error.value = null
    state.value = 'idle'
  }

  function push(event: RunEvent): void {
    if (event.seq <= lastSeq.value) return
    lastSeq.value = event.seq
    events.value = [...events.value, event]
    options.onEvent?.(event)
  }

  function parseFrames(buffer: string): string {
    // SSE 帧以空行分隔；返回未完成的尾部
    const frames = buffer.split(/\r?\n\r?\n/)
    const rest = frames.pop() ?? ''
    for (const frame of frames) {
      const dataLines: string[] = []
      for (const line of frame.split(/\r?\n/)) {
        if (line.startsWith(':')) continue // 心跳注释
        if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
      }
      if (!dataLines.length) continue
      try {
        push(JSON.parse(dataLines.join('\n')) as RunEvent)
      } catch {
        // 忽略无法解析的帧
      }
    }
    return rest
  }

  async function connectOnce(): Promise<{ received: number; sawEnd: boolean }> {
    controller = new AbortController()
    const runId = options.runId()
    const url = `${API_BASE}/api/admin/runs/${runId}/stream?from_seq=${lastSeq.value}`
    const headers: Record<string, string> = { Accept: 'text/event-stream' }
    if (apiKey.value) headers['X-API-Key'] = apiKey.value

    const response = await fetch(url, { headers, signal: controller.signal })
    if (!response.ok || !response.body) {
      throw new Error(`事件流连接失败（HTTP ${response.status}）`)
    }
    state.value = 'live'

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let received = 0
    let sawEnd = false
    const before = lastSeq.value

    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      buffer = parseFrames(buffer)
      if (lastSeq.value > before) {
        received = lastSeq.value - before
        if (events.value.at(-1)?.type === 'run_end') {
          sawEnd = true
          await reader.cancel().catch(() => undefined)
          break
        }
      }
    }
    return { received, sawEnd }
  }

  async function loop(): Promise<void> {
    state.value = 'connecting'
    while (running) {
      try {
        const { received, sawEnd } = await connectOnce()
        error.value = null
        if (sawEnd) {
          state.value = 'done'
          break
        }
        // 流结束但未终态：可能是网络中断或已追平——询问调用方是否已完成
        if (received === 0 && options.checkDone && (await options.checkDone())) {
          state.value = 'done'
          break
        }
      } catch (err) {
        if (!running) break
        if ((err as Error).name === 'AbortError') break
        error.value = (err as Error).message
        state.value = 'error'
      }
      if (!running) break
      await new Promise((resolve) => setTimeout(resolve, RECONNECT_DELAY_MS))
    }
    if (running && state.value !== 'done') state.value = 'done'
    running = false
  }

  function start(): void {
    if (running) return
    running = true
    void loop()
  }

  function stop(): void {
    running = false
    controller?.abort()
    controller = null
    if (state.value !== 'done') state.value = 'paused'
  }

  async function restart(): Promise<void> {
    stop()
    await new Promise((resolve) => setTimeout(resolve, 50))
    reset()
    start()
  }

  onScopeDispose(() => stop())

  return { events, lastSeq, state, error, start, stop, restart, reset }
}
