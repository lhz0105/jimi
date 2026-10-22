/** 与后端 app/api 契约对应的类型（见 backend/README.md 与 /docs）。 */

export type RunStatus = 'queued' | 'awaiting_confirm' | 'running' | 'succeeded' | 'failed' | 'cancelled'
export type RiskLevel = 'critical' | 'high' | 'medium' | 'low' | 'none'
export type EventLevel = 'info' | 'warn' | 'error'

export interface PageMeta {
  total: number
  page: number
  page_size: number
  has_more: boolean
}

export interface ExternalRef {
  source?: string | null
  conversation_id?: string | null
  customer_name?: string | null
}

export type HumanVerdict = 'fraud' | 'genuine' | 'insufficient'
export type ReviewStatus = 'pending' | 'in_dialogue' | 'generated'
export type ReviewBadgeStatus = 'needed' | 'in_dialogue' | 'generated' | 'none'

export interface ReviewMessage {
  id: string
  review_id: string
  role: 'human' | 'agent' | 'system'
  content: string
  meta: Record<string, unknown>
  created_at: number
}

export interface RunReview {
  id: string
  run_id: string
  verdict: HumanVerdict
  reason: string
  reviewer: string
  status: ReviewStatus
  agent_turns: number
  llm_usage: Record<string, number>
  generation_error: string | null
  created_at: number
  updated_at: number
  generated_at: number | null
}

export type PriorFeedbackOutcome = 'adopted' | 'overturned' | 'not_applicable' | 'neutral'

export interface PriorCaseFeedback {
  id: string
  case_id: string
  run_id: string | null
  review_id: string | null
  signal: PriorFeedbackOutcome
  source: string
  confidence: number | null
  weight_before: number
  weight_after: number
  rationale: string
  evidence_ids: string[]
  created_at: number
}

export interface PriorCase {
  id: string
  review_id: string | null
  run_id: string | null
  title: string
  scenario: string
  human_verdict: HumanVerdict
  markdown: string
  metadata: Record<string, unknown>
  content_hash: string
  indexed_at: number | null
  index_error: string | null
  alpha: number
  beta: number
  reliability: number
  adopted_count: number
  overturned_count: number
  feedback_count: number
  last_feedback_at: number | null
  created_at: number
}

export interface ReviewState {
  run_id: string
  eligible: boolean
  review: RunReview | null
  messages: ReviewMessage[]
  case: PriorCase | null
  feedback: PriorCaseFeedback[]
  max_turns: number
  turns_left: number
  can_generate: boolean
}

export interface RunBrief {
  run_id: string
  conversation_id: string | null
  customer_name?: string | null
  external_ref?: ExternalRef | null
  input_summary?: string | null
  review_required?: boolean
  review_status?: ReviewBadgeStatus | null
  scenario: string
  trigger_mode: string
  status: RunStatus
  risk_level: RiskLevel | null
  confidence: number | null
  cost: CostSummary
  created_at: number
  started_at?: number | null
  finished_at: number | null
}

export interface CostByNode {
  llm_calls: number
  prompt_tokens: number
  completion_tokens: number
  cost: number
}

export interface CostSummary {
  llm_calls?: number
  prompt_tokens?: number
  completion_tokens?: number
  tool_calls?: number
  vision_calls?: number
  tavily_calls?: number
  est_cost?: number
  per_tool?: Record<string, number>
  by_node?: Record<string, CostByNode>
}

export interface RunRecord {
  id: string
  conversation_id: string | null
  external_ref?: ExternalRef | null
  review_required?: boolean
  scenario: string
  trigger_mode: string
  status: RunStatus
  rules_decision: Record<string, unknown>
  input_snapshot: Record<string, unknown>
  verdict: Verdict | null
  risk_level: RiskLevel | null
  confidence: number | null
  error: string | null
  cost_json: CostSummary
  progress_json: { node?: string; percent?: number }
  created_at: number
  started_at: number | null
  finished_at: number | null
}

export interface Verdict {
  conclusion?: string
  risk_level?: RiskLevel
  confidence?: number
  summary?: string
  evidence_refs?: string[]
  key_counterpoints?: string[]
  recommended_actions?: RecommendedAction[]
  needs_more_evidence?: boolean
}

export interface RecommendedAction {
  action: string
  priority?: number
  note?: string
}

export interface RunEvent {
  v?: number
  run_id: string
  seq: number
  ts: number
  type: string
  node: string | null
  level: EventLevel
  payload: Record<string, any>
}

export interface Evidence {
  evidence_id: string
  category: string
  source: { type?: string; ref?: string; detail?: string }
  tool: string
  finding: string
  direction: 'supports_fake' | 'supports_genuine' | 'neutral' | 'unknown'
  weight: number
  raw_ref?: Record<string, unknown>
  notes?: string
}

export interface ToolCallRecord {
  id: string
  seq: number
  tool: string
  args: Record<string, unknown>
  result: Record<string, unknown> | null
  result_ref: string | null
  status: string
  latency_ms: number | null
  cost: Record<string, unknown>
  created_at: number
}

export interface RunDetail {
  run: RunRecord
  rules_decision: Record<string, any>
  input_snapshot: Record<string, any>
  confirmations: Array<{ id: string; decision: string; decided_by: string; created_at: number }>
  event_counts: Record<string, number>
  tool_calls: ToolCallRecord[]
  report_id: string | null
}

export interface ReportJson {
  report_id: string
  run_id: string
  generated_at: number
  scenario: string
  summary: { conclusion: string; risk_level: RiskLevel; confidence: number; one_line: string }
  evidence_chain: Evidence[]
  thought_timeline: Array<{ seq: number; ts: number; node: string | null; summary: string }>
  recommended_actions: RecommendedAction[]
  key_counterpoints: string[]
  input_digest: {
    conversation_id: string | null
    message_count: number
    image_sha256s: string[]
    rules_version: string | null
    loop_count: number
  }
  cost: CostSummary
  versions: { rules: string; kb: string; prompts: string; models: { main: string; vision: string } }
  limitations: string[]
}

export interface KbDocument {
  id: string
  path: string
  title: string
  scenario: string
  doc_type: string
  tags: string
  content_hash: string
  chunk_count: number
  enabled: number
  updated_at: number
}

export interface KbStats {
  mode: string
  chunks: number
  dense_chunks?: number
  bm25_chunks?: number
}

export interface KbDocumentsResponse {
  items: KbDocument[]
  stats: KbStats
  kb_version: string
  rag_mode: string
}

export interface KbSearchHit {
  chunk_id: string
  doc_id: string
  doc_title: string
  scenario: string
  heading_path: string
  text: string
  score_dense: number | null
  score_bm25: number | null
  score_rrf: number
}

export interface KbSearchResponse {
  query: string
  rag_mode: string
  kb_version: string
  items: KbSearchHit[]
}

export interface StatsResponse {
  window_days: number
  totals: {
    runs: number
    succeeded: number
    failed: number
    cancelled: number
    active: number
    llm_calls: number
    prompt_tokens: number
    completion_tokens: number
    tool_calls: number
    est_cost: number
  }
  by_scenario: Record<string, number>
  by_day: Record<string, { runs: number; est_cost: number }>
}

export interface HealthResponse {
  status: string
  uptime_s: number
  db: { ok: boolean; error: string | null }
  rag: { mode: string; kb_version: string | null }
  rules: { version: string | null }
  sse_connections: number
  llm_mode: string
  runner_ready: boolean
}

export interface ConfigSnapshot {
  llm_mode: string
  llm_main: { base_url: string; model: string; api_key: string }
  llm_vision: { base_url: string; model: string; api_key: string }
  tavily_api_key: string
  rag: { embedding_model: string; top_k: number; mode: string }
  budget: Record<string, number>
  paths: Record<string, string>
}

export interface RulesResponse {
  version: string
  yaml: string
}

export interface RunConversationMessage {
  seq: number
  role: 'customer' | 'agent' | 'system'
  content: string
  ts: number | null
}

export interface RunConversation {
  run_id: string
  source: 'conversation' | 'inline' | 'digest'
  note: string
  messages: RunConversationMessage[]
  message_count: number
  image_count: number
}
