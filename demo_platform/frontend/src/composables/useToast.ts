import { ref } from 'vue'

export interface Toast {
  id: number
  kind: 'success' | 'error' | 'info'
  message: string
}

const toasts = ref<Toast[]>([])
let seed = 0

function push(kind: Toast['kind'], message: string, ttlMs = 4000): void {
  const id = ++seed
  toasts.value = [...toasts.value, { id, kind, message }]
  window.setTimeout(() => dismiss(id), ttlMs)
}

export function dismiss(id: number): void {
  toasts.value = toasts.value.filter((t) => t.id !== id)
}

export function useToast() {
  return {
    toasts,
    dismiss,
    success: (message: string) => push('success', message),
    error: (message: string) => push('error', message, 6000),
    info: (message: string) => push('info', message),
  }
}
