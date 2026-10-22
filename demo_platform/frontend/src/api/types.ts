/** 演示平台后端契约（其内部再调用 agent 对外接口）。 */

export type RunStatus = 'queued' | 'awaiting_confirm' | 'running' | 'succeeded' | 'failed' | 'cancelled'
export type RiskLevel = 'critical' | 'high' | 'medium' | 'low' | 'none'

export interface Attachment {
  id: string
  conversation_id: string
  message_id: string | null
  sha256: string
  mime: string
  width: number | null
  height: number | null
  bytes: number | null
  created_at: number
  url: string
}

export interface MatchedRule {
  id: string
  priority: number
  scenario: string | null
  hits: string[]
}

export interface CheckResult {
  need_analysis: boolean
  scenario: string | null
  risk_hint: string | null
  require_confirm: boolean
  matched_rules: MatchedRule[]
  reason: string
  decision_id: string
  image_count: number
  window_size: number
  semantic_status: string
  semantic_hits: Record<string, number>
  semantic_levels?: Record<string, string>
  message?: string
  error?: string
  code?: string
}

export interface Message {
  id: string
  conversation_id: string
  seq: number
  role: 'customer' | 'agent'
  content: string
  check_result: CheckResult | null
  created_at: number
}

export interface AnalysisSummary {
  id: string
  run_id: string
  status: RunStatus
  risk_level: RiskLevel | null
  scenario: string | null
}

export interface Conversation {
  id: string
  customer_name: string
  channel: string
  created_at: number
  updated_at: number
  last_message?: string | null
  message_count?: number
  image_count?: number
  attachments?: Attachment[]
  latest_analysis?: AnalysisSummary | null
}

export interface Analysis {
  id: string
  conversation_id: string
  run_id: string
  decision_id: string | null
  scenario: string | null
  status: RunStatus
  risk_level: RiskLevel | null
  confidence: number | null
  verdict: {
    conclusion?: string
    risk_level?: RiskLevel
    confidence?: number
    summary?: string
    evidence_refs?: string[]
    recommended_actions?: Array<{ action: string; priority?: number; note?: string }>
  } | null
  cost?: Record<string, number>
  last_error: string | null
  progress?: { node?: string; percent?: number }
  error?: string | null
  created_at: number
  updated_at: number
}

export interface ConversationDetail {
  conversation: Conversation
  messages: Message[]
  attachments: Attachment[]
  analyses: Analysis[]
}

export interface RunEvent {
  v?: number
  run_id: string
  seq: number
  ts: number
  type: string
  node: string | null
  level: 'info' | 'warn' | 'error'
  payload: Record<string, any>
}

export interface ReportJson {
  report_id: string
  run_id: string
  generated_at: number
  scenario: string
  summary: { conclusion: string; risk_level: RiskLevel; confidence: number; one_line: string }
  evidence_chain: Array<{
    evidence_id: string
    category: string
    source: { type?: string; ref?: string; detail?: string }
    tool: string
    finding: string
    direction: string
    weight: number
    notes?: string
  }>
  recommended_actions: Array<{ action: string; priority?: number; note?: string }>
  key_counterpoints: string[]
  limitations: string[]
  cost: Record<string, number>
}

export interface Health {
  status: string
  agent: { ok: boolean; base_url: string; error: string | null }
}
