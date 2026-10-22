export function formatTime(ms?: number | null): string {
  if (!ms) return '—'
  return new Date(ms).toLocaleTimeString('zh-CN', { hour12: false })
}

export function formatDateTime(ms?: number | null): string {
  if (!ms) return '—'
  const d = new Date(ms)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function formatTokens(value?: number | null): string {
  if (value === undefined || value === null) return '—'
  if (value < 1000) return String(value)
  if (value < 1_000_000) return `${(value / 1000).toFixed(1)}k`
  return `${(value / 1_000_000).toFixed(2)}M`
}

export function formatLatency(ms?: number | null): string {
  if (ms === undefined || ms === null) return '—'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

export function formatCost(value?: number | null): string {
  if (!value) return '0'
  return value < 0.01 ? value.toFixed(5).replace(/0+$/, '').replace(/\.$/, '') : value.toFixed(3)
}

export function downloadText(filename: string, text: string, mime = 'text/markdown'): void {
  const blob = new Blob([text], { type: `${mime};charset=utf-8` })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
