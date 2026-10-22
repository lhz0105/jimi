export function formatTime(ms?: number | null): string {
  if (!ms) return '—'
  const d = new Date(ms)
  return d.toLocaleTimeString('zh-CN', { hour12: false })
}

export function formatDateTime(ms?: number | null): string {
  if (!ms) return '—'
  const d = new Date(ms)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

export function formatRelative(ms?: number | null): string {
  if (!ms) return '—'
  const diff = Date.now() - ms
  if (diff < 0) return '刚刚'
  const s = Math.floor(diff / 1000)
  if (s < 60) return `${s} 秒前`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} 分钟前`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} 小时前`
  return `${Math.floor(h / 24)} 天前`
}

export function formatDuration(startMs?: number | null, endMs?: number | null): string {
  if (!startMs) return '—'
  const end = endMs ?? Date.now()
  const ms = end - startMs
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  const m = Math.floor(ms / 60000)
  const s = Math.round((ms % 60000) / 1000)
  return `${m}m${String(s).padStart(2, '0')}s`
}

export function formatNumber(value?: number | null): string {
  if (value === undefined || value === null) return '—'
  return value.toLocaleString('zh-CN')
}

export function formatTokens(value?: number | null): string {
  if (!value) return '0'
  if (value < 1000) return String(value)
  if (value < 1_000_000) return `${(value / 1000).toFixed(1)}k`
  return `${(value / 1_000_000).toFixed(2)}M`
}

export function formatCost(value?: number | null): string {
  if (!value) return '0'
  if (value < 0.01) return value.toFixed(5).replace(/0+$/, '').replace(/\.$/, '')
  return value.toFixed(3)
}

export function formatLatency(ms?: number | null): string {
  if (ms === undefined || ms === null) return '—'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

export function formatPercent(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`
}

export function shortId(id: string, keep = 8): string {
  const idx = id.indexOf('_')
  const prefix = idx >= 0 ? id.slice(0, idx + 1) : ''
  const body = idx >= 0 ? id.slice(idx + 1) : id
  return `${prefix}${body.slice(0, keep)}`
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
