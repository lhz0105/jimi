import type { IconName } from '@/components/icons'
import type { RiskLevel, RunStatus } from '@/api/types'

export type ToneKey = 'accent' | 'danger' | 'warn' | 'info' | 'violet' | 'teal' | 'slate'

export interface ToneClass {
  text: string
  bg: string
  border: string
  dot: string
}

export const TONE: Record<ToneKey, ToneClass> = {
  accent: { text: 'text-accent', bg: 'bg-accent/10', border: 'border-accent/45', dot: 'bg-accent' },
  danger: { text: 'text-danger', bg: 'bg-danger/10', border: 'border-danger/45', dot: 'bg-danger' },
  warn: { text: 'text-warn', bg: 'bg-warn/10', border: 'border-warn/45', dot: 'bg-warn' },
  info: { text: 'text-info', bg: 'bg-info/10', border: 'border-info/45', dot: 'bg-info' },
  violet: { text: 'text-violet', bg: 'bg-violet/10', border: 'border-violet/45', dot: 'bg-violet' },
  teal: { text: 'text-teal', bg: 'bg-teal/10', border: 'border-teal/45', dot: 'bg-teal' },
  slate: {
    text: 'text-ink-muted',
    bg: 'bg-surface-2/70',
    border: 'border-line-soft',
    dot: 'bg-ink-muted',
  },
}

/* ------------------------------- 运行状态 ------------------------------- */

export const STATUS_META: Record<RunStatus, { label: string; tone: ToneKey }> = {
  queued: { label: '已入队', tone: 'slate' },
  awaiting_confirm: { label: '等待确认', tone: 'warn' },
  running: { label: '运行中', tone: 'info' },
  succeeded: { label: '已完成', tone: 'accent' },
  failed: { label: '失败', tone: 'danger' },
  cancelled: { label: '已取消', tone: 'slate' },
}

export const ACTIVE_STATUSES: RunStatus[] = ['queued', 'awaiting_confirm', 'running']

export const RISK_META: Record<RiskLevel, { label: string; tone: ToneKey }> = {
  critical: { label: '极高', tone: 'danger' },
  high: { label: '高', tone: 'danger' },
  medium: { label: '中', tone: 'warn' },
  low: { label: '低', tone: 'info' },
  none: { label: '无', tone: 'accent' },
}

export const REVIEW_STATUS_META: Record<string, { label: string; tone: ToneKey }> = {
  needed: { label: '待复核', tone: 'warn' },
  pending: { label: '待复核', tone: 'warn' },
  in_dialogue: { label: '复核中', tone: 'info' },
  generated: { label: '已复核', tone: 'accent' },
  none: { label: '', tone: 'slate' },
}

export const HUMAN_VERDICT_META: Record<string, { label: string; tone: ToneKey }> = {
  fraud: { label: '欺诈', tone: 'danger' },
  genuine: { label: '真实', tone: 'accent' },
  insufficient: { label: '证据不足', tone: 'warn' },
}

export const PRIOR_FEEDBACK_META: Record<string, { label: string; tone: ToneKey }> = {
  adopted: { label: '采纳', tone: 'accent' },
  overturned: { label: '推翻', tone: 'danger' },
  not_applicable: { label: '不适用', tone: 'slate' },
  neutral: { label: '中性', tone: 'warn' },
}

export const SEMANTIC_ANCHOR_LABEL: Record<string, string> = {
  refund_intent: '退款意图',
  product_damage: '商品损坏',
  medical_claim: '医疗索赔',
  seeding_intent: '种草意图',
}

export const CONCLUSION_META: Record<string, { label: string; tone: ToneKey }> = {
  fake_claim: { label: '判定欺诈', tone: 'danger' },
  suspicious: { label: '疑似欺诈', tone: 'warn' },
  inconclusive: { label: '证据不足', tone: 'slate' },
  likely_genuine: { label: '倾向真实', tone: 'accent' },
}

export const DIRECTION_META: Record<string, { label: string; tone: ToneKey }> = {
  supports_fake: { label: '支持欺诈', tone: 'danger' },
  supports_genuine: { label: '支持真实', tone: 'accent' },
  neutral: { label: '中性', tone: 'slate' },
  unknown: { label: '未知', tone: 'slate' },
}

export const SCENARIO_LABEL: Record<string, string> = {
  product_damage_claim: '产品破损索赔',
  medical_cert_claim: '医疗单据索赔',
  seeding_post: '种草内容真伪',
  generic: '通用',
}

export const EVIDENCE_CATEGORY_LABEL: Record<string, string> = {
  aigc_artifact: 'AIGC 痕迹',
  image_manipulation: '图像篡改',
  metadata: '元数据',
  duplicate_image: '图片复用',
  document_field: '单据字段',
  statement_contradiction: '陈述矛盾',
  rag_precedent: '先例/知识库',
  web_fact: '联网事实',
  marketing_pattern: '营销特征',
  customer_behavior: '行为特征',
}

export const NODE_LABEL: Record<string, string> = {
  prepare_case: '案件准备',
  route_scenario: '场景路由',
  local_forensics: '本地取证',
  ai_image_detection: 'AI 生成预检',
  rag_recall: '知识库召回',
  prior_case_recall: '先前案例召回',
  vision_analysis: '视觉分析',
  investigate: '调查',
  consistency: '一致性核对',
  adjudicate: '裁决',
  report: '报告生成',
  finalize: '收尾',
  runner: '运行器',
}

export const TOOL_LABEL: Record<string, string> = {
  vision_analyze: '识图分析',
  sightengine_detect: 'AI 生成复核',
  lookup_kb: '知识库检索',
  prior_case_recall: '先前案例',
  web_search: '联网搜索',
  find_similar_claim_images: '复用图检测',
  get_customer_statements: '会话记录',
  read_file: '读文件',
  write_file: '写文件',
}

/* -------------------------------- 事件类型 -------------------------------- */

export interface EventMeta {
  label: string
  tone: ToneKey
  icon: IconName
}

export const EVENT_META: Record<string, EventMeta> = {
  run_queued: { label: '已入队', tone: 'slate', icon: 'clock' },
  run_awaiting_confirm: { label: '等待确认', tone: 'warn', icon: 'pause' },
  run_confirmed: { label: '已确认', tone: 'accent', icon: 'check' },
  run_start: { label: '开始分析', tone: 'accent', icon: 'play' },
  node_start: { label: '节点开始', tone: 'slate', icon: 'chevronRight' },
  node_end: { label: '节点完成', tone: 'slate', icon: 'check' },
  thought: { label: '思考', tone: 'info', icon: 'brain' },
  llm_call: { label: '模型调用', tone: 'violet', icon: 'zap' },
  llm_result: { label: '模型返回', tone: 'violet', icon: 'zap' },
  tool_call: { label: '工具调用', tone: 'teal', icon: 'tool' },
  tool_result: { label: '工具返回', tone: 'teal', icon: 'tool' },
  tool_error: { label: '工具错误', tone: 'danger', icon: 'alert' },
  rag_hit: { label: '检索命中', tone: 'teal', icon: 'database' },
  evidence: { label: '证据', tone: 'warn', icon: 'scale' },
  verdict: { label: '裁决', tone: 'warn', icon: 'scale' },
  report: { label: '报告', tone: 'accent', icon: 'fileText' },
  budget_warning: { label: '预算告警', tone: 'warn', icon: 'alert' },
  warning: { label: '提示', tone: 'warn', icon: 'info' },
  error: { label: '错误', tone: 'danger', icon: 'alert' },
  run_end: { label: '运行结束', tone: 'accent', icon: 'stop' },
}

export function eventMeta(type: string): EventMeta {
  return EVENT_META[type] ?? { label: type, tone: 'slate', icon: 'info' }
}

/** 时间线上默认折叠的噪声事件（可在面板中切换显示） */
export const QUIET_EVENT_TYPES = new Set(['node_start', 'node_end', 'llm_result'])
