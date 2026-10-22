import { http } from './client'
import type {
  Analysis,
  Conversation,
  ConversationDetail,
  Health,
  Message,
  ReportJson,
} from './types'

export async function fetchHealth(): Promise<Health> {
  return (await http.get('/health')).data
}

export async function listConversations(): Promise<Conversation[]> {
  return (await http.get('/conversations')).data
}

export async function createConversation(customerName: string, channel = 'demo'): Promise<Conversation> {
  return (await http.post('/conversations', { customer_name: customerName, channel })).data
}

export async function getConversation(convId: string): Promise<ConversationDetail> {
  return (await http.get(`/conversations/${convId}`)).data
}

export async function deleteConversation(convId: string): Promise<{ ok: boolean }> {
  return (await http.delete(`/conversations/${convId}`)).data
}

export async function postMessage(
  convId: string,
  payload: { role: 'customer' | 'agent'; text: string; attachment_ids?: string[] },
): Promise<{ message: Message; analysis: Analysis | null }> {
  return (await http.post(`/conversations/${convId}/messages`, payload)).data
}

export async function uploadImage(convId: string, file: File): Promise<{ id: string; url: string }> {
  const form = new FormData()
  form.append('file', file)
  return (await http.post(`/conversations/${convId}/upload`, form)).data
}

export async function startAnalysis(
  convId: string,
  payload: { decision_id?: string; scenario?: string; auto_confirm?: boolean },
): Promise<{
  analysis: Analysis
  agent: { run_id: string; status: string; message?: string }
  reused?: boolean
}> {
  return (await http.post(`/conversations/${convId}/analyze`, payload)).data
}

export async function getAnalysis(analysisId: string): Promise<Analysis> {
  return (await http.get(`/analyses/${analysisId}`)).data
}

export async function confirmAnalysis(analysisId: string): Promise<Analysis> {
  return (await http.post(`/analyses/${analysisId}/confirm`)).data
}

export async function cancelAnalysis(analysisId: string): Promise<Analysis> {
  return (await http.post(`/analyses/${analysisId}/cancel`)).data
}

export async function getReportJson(analysisId: string): Promise<ReportJson> {
  return (await http.get(`/analyses/${analysisId}/report`, { params: { format: 'json' } })).data
}

export async function getReportMarkdown(analysisId: string): Promise<string> {
  const response = await http.get(`/analyses/${analysisId}/report`, {
    params: { format: 'markdown' },
    responseType: 'text',
    transformResponse: [(data: string) => data],
  })
  return response.data as string
}

export async function seedDemo(scenario: string): Promise<{ conversation: Conversation }> {
  return (await http.post(`/demo/seed/${scenario}`)).data
}

export async function recheckConversation(convId: string): Promise<{ checked: number }> {
  return (await http.post(`/conversations/${convId}/recheck`)).data
}
