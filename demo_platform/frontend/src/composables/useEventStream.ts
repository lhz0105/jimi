import { onScopeDispose, ref } from 'vue'

import type { RunEvent } from '@/api/types'

const RECONNECT_DELAY_MS = 1500

export interface EventStreamOptions {
  /** 演示平台的分析 ID */
  analysisId: () => string
  /** 流正常结束但未收到 run_end 时，询问是否已终态 */
  checkDone?: () => Promise<boolean>
  onEvent?: (event: RunEvent) => void
}

/**
 * 分析事件流（fetch SSE）。
 * 演示平台后端把事件原样代理自 agent 的 /api/v1/analyze/runs/{id}/stream，
 * 因此这里与"真实接入"的写法完全一致：支持断线续传（?from_seq=）。
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
    const frames = buffer.split(/\r?\n\r?\n/)
    const rest = frames.pop() ?? ''
    for (const frame of frames) {
      const dataLines: string[] = []
      for (const line of frame.split(/\r?\n/)) {
        if (line.startsWith(':')) continue
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
    const url = `/api/analyses/${options.analysisId()}/stream?from_seq=${lastSeq.value}`
    const response = await fetch(url, {
      headers: { Accept: 'text/event-stream' },
      signal: controller.signal,
    })
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
