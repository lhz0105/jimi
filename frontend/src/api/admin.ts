import { API_BASE, apiKey, http } from './client'
import type {
  ConfigSnapshot,
  HealthResponse,
  HumanVerdict,
  KbDocumentsResponse,
  KbSearchResponse,
  PageMeta,
  PriorCase,
  PriorCaseFeedback,
  ReportJson,
  ReviewState,
  RulesResponse,
  RunBrief,
  RunConversation,
  RunDetail,
  RunEvent,
  StatsResponse,
} from './types'

export interface RunsQuery {
  status?: string
  scenario?: string
  conversation_id?: string
  q?: string
  review?: string
  page?: number
  page_size?: number
}

export async function fetchHealth(): Promise<HealthResponse> {
  return (await http.get('/admin/health')).data
}

export async function fetchStats(days = 7): Promise<StatsResponse> {
  return (await http.get('/admin/stats', { params: { days } })).data
}

export async function fetchRuns(query: RunsQuery): Promise<{ items: RunBrief[]; meta: PageMeta }> {
  const params = Object.fromEntries(
    Object.entries(query).filter(([, v]) => v !== undefined && v !== '' && v !== null),
  )
  return (await http.get('/admin/runs', { params })).data
}

export async function fetchRunDetail(runId: string): Promise<RunDetail> {
  return (await http.get(`/admin/runs/${runId}`)).data
}

export async function fetchRunConversation(runId: string): Promise<RunConversation> {
  return (await http.get(`/admin/runs/${runId}/conversation`)).data
}

/* ------------------------------ 人工复核 ------------------------------ */

export async function fetchRunReview(runId: string): Promise<ReviewState> {
  return (await http.get(`/admin/runs/${runId}/review`)).data
}

export async function startRunReview(
  runId: string,
  payload: { verdict: HumanVerdict; reason: string; reviewer: string },
): Promise<ReviewState> {
  return (await http.post(`/admin/runs/${runId}/review`, payload)).data
}

export async function sendRunReviewMessage(runId: string, content: string): Promise<ReviewState> {
  return (await http.post(`/admin/runs/${runId}/review/messages`, { content })).data
}

export async function generatePriorCase(runId: string): Promise<ReviewState> {
  return (await http.post(`/admin/runs/${runId}/review/generate`)).data
}

export interface ReviewStreamHandlers {
  onStatus?: (text: string) => void
  onToken?: (text: string, kind: 'interview' | 'case') => void
  onState?: (state: ReviewState) => void
  onError?: (message: string) => void
}

export async function streamRunReview(
  runId: string,
  payload: Record<string, unknown>,
  handlers: ReviewStreamHandlers,
): Promise<void> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  }
  if (apiKey.value) headers['X-API-Key'] = apiKey.value
  const response = await fetch(`${API_BASE}/api/admin/runs/${runId}/review/stream`, {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
  })
  if (!response.ok || !response.body) {
    let message = `请求失败（HTTP ${response.status}）`
    try {
      const data = await response.json()
      message = data?.error?.message ?? message
    } catch {
      /* 非 JSON 错误响应 */
    }
    throw new Error(message)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    buffer = buffer.replace(/\r\n/g, '\n')
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() ?? ''
    for (const block of blocks) {
      let event = 'message'
      const dataLines: string[] = []
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
      }
      if (!dataLines.length) continue
      let data: any
      try {
        data = JSON.parse(dataLines.join('\n'))
      } catch {
        continue
      }
      if (event === 'status') handlers.onStatus?.(String(data.text ?? ''))
      else if (event === 'token') {
        handlers.onToken?.(
          String(data.text ?? ''),
          data.kind === 'case' ? 'case' : 'interview',
        )
      } else if (event === 'state') handlers.onState?.(data as ReviewState)
      else if (event === 'error') handlers.onError?.(String(data.message ?? '流式输出失败'))
    }
  }
}

export async function fetchPriorCases(params: {
  scenario?: string
  page?: number
  page_size?: number
}): Promise<{ items: PriorCase[]; meta: PageMeta }> {
  return (await http.get('/admin/prior-cases', { params })).data
}

export async function reindexPriorCases(): Promise<{ ok: boolean; stats: Record<string, unknown> }> {
  return (await http.post('/admin/prior-cases/reindex')).data
}

export async function deletePriorCase(caseId: string): Promise<{
  ok: boolean
  case_id: string
  title: string
  index_chunks_removed: number
  review_reset: boolean
}> {
  return (await http.delete(`/admin/prior-cases/${caseId}`)).data
}

export async function fetchPriorCaseFeedback(
  caseId: string,
): Promise<{ case: PriorCase; feedback: PriorCaseFeedback[] }> {
  return (await http.get(`/admin/prior-cases/${caseId}/feedback`)).data
}

export async function fetchRunEvents(
  runId: string,
  sinceSeq = 0,
  limit = 500,
): Promise<{ items: RunEvent[]; next_seq: number | null }> {
  return (await http.get(`/admin/runs/${runId}/events`, { params: { since_seq: sinceSeq, limit } }))
    .data
}

export async function fetchReportJson(runId: string): Promise<ReportJson> {
  return (await http.get(`/admin/runs/${runId}/report`, { params: { format: 'json' } })).data
}

export async function fetchReportMarkdown(runId: string): Promise<string> {
  const response = await http.get(`/admin/runs/${runId}/report`, {
    params: { format: 'markdown' },
    responseType: 'text',
    transformResponse: [(data: string) => data],
  })
  return response.data as string
}

export async function cancelRun(runId: string): Promise<{ run_id: string; status: string }> {
  return (await http.post(`/admin/runs/${runId}/cancel`)).data
}

export async function fetchConfig(): Promise<ConfigSnapshot> {
  return (await http.get('/admin/config')).data
}

/* ------------------------------- 规则 ------------------------------- */

export async function fetchRules(): Promise<RulesResponse> {
  return (await http.get('/admin/rules')).data
}

export async function saveRules(yaml: string): Promise<{ version: string; rules: number }> {
  return (await http.put('/admin/rules', { yaml })).data
}

export async function reloadRules(): Promise<{ version: string; rules: number }> {
  return (await http.post('/admin/rules/reload')).data
}

/* ------------------------------ 知识库 ------------------------------ */

export async function fetchKbDocuments(): Promise<KbDocumentsResponse> {
  return (await http.get('/admin/kb/documents')).data
}

export async function addKbDocument(path: string, content: string): Promise<{ ok: boolean }> {
  return (await http.post('/admin/kb/documents', { path, content })).data
}

export async function deleteKbDocument(docId: string): Promise<{ ok: boolean }> {
  return (await http.delete(`/admin/kb/documents/${docId}`)).data
}

export async function reindexKb(rebuild = false): Promise<{ ok: boolean; stats: Record<string, unknown> }> {
  return (await http.post('/admin/kb/reindex', null, { params: { rebuild } })).data
}

export async function searchKb(
  query: string,
  scenario?: string,
  topK = 5,
): Promise<KbSearchResponse> {
  const params: Record<string, unknown> = { q: query, top_k: topK }
  if (scenario) params.scenario = scenario
  return (await http.get('/admin/kb/search', { params })).data
}
