<script setup lang="ts">
import { computed } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import ModelOutput from '@/components/ModelOutput.vue'
import RuleDecisionView from '@/components/RuleDecisionView.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import type { Evidence, RunEvent } from '@/api/types'
import { formatLatency, formatTime, formatTokens } from '@/utils/format'
import {
  CONCLUSION_META,
  DIRECTION_META,
  EVIDENCE_CATEGORY_LABEL,
  eventMeta,
  HUMAN_VERDICT_META,
  NODE_LABEL,
  RISK_META,
  SCENARIO_LABEL,
  TONE,
  TOOL_LABEL,
} from '@/utils/meta'

const props = defineProps<{ event: RunEvent }>()

const meta = computed(() => eventMeta(props.event.type))
const tone = computed(() => TONE[meta.value.tone])
const payload = computed<Record<string, any>>(() => props.event.payload ?? {})
const nodeLabel = computed(() =>
  props.event.node ? (NODE_LABEL[props.event.node] ?? props.event.node) : '',
)

const evidence = computed<Evidence | null>(() =>
  props.event.type === 'evidence' ? (payload.value.evidence as Evidence) : null,
)
const ragHits = computed<Array<Record<string, any>>>(() =>
  props.event.type === 'rag_hit' ? ((payload.value.hits as Array<Record<string, any>>) ?? []) : [],
)
const toolArgs = computed<Record<string, any> | null>(() => {
  if (props.event.type !== 'tool_call') return null
  const raw = payload.value.args_preview
  if (typeof raw !== 'string') return null
  try {
    const value = JSON.parse(raw)
    return value && typeof value === 'object' ? value : null
  } catch {
    return null
  }
})

function argText(value: any): string {
  return typeof value === 'string' ? value : JSON.stringify(value)
}

const oneLine = computed(() => {
  const p = payload.value
  switch (props.event.type) {
    case 'thought':
      return p.kind === 'reasoning' ? '推理' : '步骤摘要'
    case 'llm_call':
      return `${p.model ?? ''} · 输入 ${p.message_count ?? '?'} 条消息 · 约 ${formatTokens(p.est_prompt_tokens)} tokens`
    case 'llm_result':
      return `${formatTokens(p.prompt_tokens)} → ${formatTokens(p.completion_tokens)} tokens · ${formatLatency(p.latency_ms)}`
    case 'tool_call':
      return `${TOOL_LABEL[p.tool] ?? p.tool}${p.cache_lookup ? '（缓存查询）' : ''}`
    case 'tool_result':
      return `${TOOL_LABEL[p.tool] ?? p.tool} · ${formatLatency(p.latency_ms)}${p.cache_hit ? ' · 缓存命中' : ''}`
    case 'tool_error':
      return `${TOOL_LABEL[p.tool] ?? p.tool} · ${p.error_code ?? ''}`
    case 'rag_hit':
      return `${p.source === 'prior_cases' ? '先前案例' : '知识库'} · ${p.rag_mode ?? 'hybrid'} · 命中 ${ragHits.value.length} 条`
    case 'evidence':
      return evidence.value
        ? `${EVIDENCE_CATEGORY_LABEL[evidence.value.category] ?? evidence.value.category}`
        : ''
    case 'verdict':
      return `${CONCLUSION_META[p.conclusion]?.label ?? p.conclusion} · 置信度 ${Number(p.confidence ?? 0).toFixed(2)}`
    case 'report':
      return `证据 ${p.evidence_count ?? '?'} 条`
    case 'node_start':
    case 'node_end':
      return props.event.type === 'node_end' ? `${formatLatency(p.latency_ms)}` : (nodeLabel.value || '')
    case 'run_start':
      return `图片 ${p.image_count ?? 0} 张 · 消息 ${p.message_count ?? 0} 条 · 摘要 ${p.digest_chars ?? 0} 字`
    case 'run_end':
      return `${p.status ?? ''} · 耗时 ${formatLatency(p.duration_ms)}`
    case 'warning':
    case 'error':
    case 'budget_warning':
      return `${p.code ?? ''}`
    default:
      return ''
  }
})
</script>

<template>
  <li class="flex gap-3 px-3 py-2.5">
    <!-- 左侧轨道：序号 + 时间 -->
    <div class="num w-20 shrink-0 pt-0.5 text-right text-[11px] leading-4 text-ink-faint">
      <div>#{{ event.seq }}</div>
      <div>{{ formatTime(event.ts) }}</div>
    </div>

    <div class="relative w-4 shrink-0">
      <div class="absolute top-2 bottom-0 left-1/2 w-px -translate-x-1/2 bg-line-soft/70" />
      <div
        class="relative z-10 mt-0.5 flex size-4 items-center justify-center rounded-full border"
        :class="[tone.bg, tone.border, tone.text]"
      >
        <AppIcon :name="meta.icon" :size="10" />
      </div>
    </div>

    <div class="min-w-0 flex-1">
      <header class="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span class="text-xs font-semibold" :class="tone.text">{{ meta.label }}</span>
        <StatusBadge v-if="nodeLabel" :label="nodeLabel" tone="slate" :dot="false" />
        <span v-if="oneLine" class="num text-[11px] text-ink-muted">{{ oneLine }}</span>
        <span v-if="event.level !== 'info'" class="text-[11px]" :class="tone.text">· {{
          event.level === 'error' ? '错误' : '警告'
        }}</span>
      </header>

      <!-- thought：完整思维链文本 -->
      <p
        v-if="event.type === 'thought'"
        class="mt-1.5 border-l-2 pl-2.5 text-[13px] whitespace-pre-wrap text-ink"
        :class="tone.border"
      >
        {{ payload.text }}
        <span v-if="payload.truncated" class="text-ink-faint">（已截断）</span>
      </p>

      <!-- tool_result：结果预览 -->
      <p
        v-else-if="event.type === 'tool_result'"
        class="num mt-1.5 rounded border border-line-soft bg-canvas/50 px-2 py-1.5 text-[12px] whitespace-pre-wrap text-ink-muted"
      >
        {{ payload.result_preview }}
      </p>

      <p
        v-else-if="event.type === 'tool_error' || event.type === 'error'"
        class="mt-1.5 rounded border px-2 py-1.5 text-[12px] whitespace-pre-wrap"
        :class="[TONE.danger.bg, TONE.danger.border, TONE.danger.text]"
      >
        {{ payload.message }}
      </p>

      <p
        v-else-if="event.type === 'warning' || event.type === 'budget_warning'"
        class="mt-1.5 rounded border px-2 py-1.5 text-[12px] whitespace-pre-wrap"
        :class="[TONE.warn.bg, TONE.warn.border, TONE.warn.text]"
      >
        {{ payload.message }}
        <span v-if="payload.metric" class="num">（{{ payload.metric }}: {{ payload.used }}/{{ payload.limit }}）</span>
      </p>

      <!-- evidence：证据卡 -->
      <div
        v-else-if="evidence"
        class="mt-1.5 rounded-md border p-2"
        :class="[TONE[DIRECTION_META[evidence.direction]?.tone ?? 'slate'].border, 'bg-canvas/40']"
      >
        <div class="flex flex-wrap items-center gap-2">
          <span class="num text-[11px] text-ink-faint">{{ evidence.evidence_id }}</span>
          <StatusBadge
            :label="DIRECTION_META[evidence.direction]?.label ?? evidence.direction"
            :tone="DIRECTION_META[evidence.direction]?.tone ?? 'slate'"
          />
          <span class="num text-[11px] text-ink-muted">权重 {{ evidence.weight }}</span>
          <span class="text-[11px] text-ink-faint">via {{ TOOL_LABEL[evidence.tool] ?? evidence.tool }}</span>
        </div>
        <p class="mt-1 text-[13px] text-ink">{{ evidence.finding }}</p>
        <p class="mt-0.5 text-[11px] text-ink-faint">
          来源：{{ evidence.source?.type }}
          <template v-if="evidence.source?.detail">｜{{ evidence.source.detail }}</template>
          <template v-if="evidence.notes">｜{{ evidence.notes }}</template>
        </p>
      </div>

      <!-- rag_hit：命中清单（三路分数） -->
      <div v-else-if="event.type === 'rag_hit'" class="mt-1.5 space-y-1.5">
        <div class="flex flex-wrap items-center gap-2">
          <p class="num text-[11px] text-ink-faint">查询：{{ payload.query }}</p>
          <StatusBadge
            v-if="payload.source === 'prior_cases'"
            label="先前案例库"
            tone="violet"
            :dot="false"
          />
          <StatusBadge v-else-if="payload.source" label="知识库" tone="slate" :dot="false" />
        </div>
        <div
          v-for="hit in ragHits"
          :key="hit.chunk_id"
          class="rounded border border-line-soft bg-canvas/40 px-2 py-1.5"
        >
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-[12px] font-medium text-ink">{{ hit.doc_title }}</span>
            <StatusBadge
              v-if="hit.scenario && hit.scenario !== 'generic'"
              :label="SCENARIO_LABEL[hit.scenario] ?? hit.scenario"
              tone="slate"
              :dot="false"
            />
            <StatusBadge
              v-if="hit.human_verdict"
              :label="HUMAN_VERDICT_META[hit.human_verdict]?.label ?? hit.human_verdict"
              :tone="HUMAN_VERDICT_META[hit.human_verdict]?.tone ?? 'slate'"
              :dot="false"
            />
            <StatusBadge
              v-if="hit.reliability !== undefined && hit.reliability !== null"
              :label="`可靠性 ${Number(hit.reliability).toFixed(2)}`"
              tone="violet"
              :dot="false"
            />
            <span class="num text-[11px] text-ink-muted">
              dense {{ hit.score_dense ?? '—' }} · bm25 {{ hit.score_bm25 ?? '—' }} · rrf
              {{ hit.score_rrf }}
            </span>
          </div>
          <p class="mt-0.5 text-[12px] whitespace-pre-wrap text-ink-muted">{{ hit.preview }}</p>
        </div>
      </div>

      <!-- verdict：结论摘要 -->
      <div
        v-else-if="event.type === 'verdict'"
        class="mt-1.5 flex flex-wrap items-center gap-2 rounded border border-line-soft bg-canvas/40 px-2 py-1.5"
      >
        <StatusBadge
          :label="CONCLUSION_META[payload.conclusion]?.label ?? String(payload.conclusion)"
          :tone="CONCLUSION_META[payload.conclusion]?.tone ?? 'slate'"
        />
        <StatusBadge
          v-if="payload.risk_level"
          :label="`风险 ${RISK_META[payload.risk_level as keyof typeof RISK_META]?.label ?? payload.risk_level}`"
          :tone="RISK_META[payload.risk_level as keyof typeof RISK_META]?.tone ?? 'slate'"
        />
        <span class="num text-[11px] text-ink-muted">置信度 {{ Number(payload.confidence ?? 0).toFixed(2) }}</span>
        <p class="w-full text-[12px] text-ink-muted">{{ payload.summary }}</p>
      </div>

      <!-- 工具调用参数：字段化展示，避免原始 JSON -->
      <div
        v-else-if="event.type === 'tool_call' && toolArgs"
        class="mt-1.5 space-y-0.5 rounded border border-line-soft bg-canvas/40 px-2 py-1.5 text-[11px]"
      >
        <div v-for="(value, key) in toolArgs" :key="key" class="flex gap-2">
          <span class="shrink-0 text-ink-faint">{{ key }}</span>
          <span class="min-w-0 break-all text-ink-muted">{{ argText(value) }}</span>
        </div>
      </div>
      <p
        v-else-if="event.type === 'tool_call' && payload.args_preview"
        class="mt-1.5 rounded border border-line-soft bg-canvas/40 px-2 py-1.5 text-[11px] whitespace-pre-wrap text-ink-muted"
      >
        {{ payload.args_preview }}
      </p>
      <div
        v-else-if="event.type === 'llm_call'"
        class="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 rounded border border-line-soft bg-canvas/40 px-2 py-1.5 text-[11px] text-ink-muted"
      >
        <span>模型 {{ payload.model }}</span>
        <span>用途 {{ NODE_LABEL[payload.purpose] ?? payload.purpose ?? '—' }}</span>
        <span class="num">
          输入 {{ payload.message_count ?? '—' }} 条 · 约 {{ formatTokens(payload.est_prompt_tokens) }} tokens
        </span>
      </div>
      <div v-else-if="event.type === 'llm_result'">
        <ModelOutput
          v-if="payload.content_preview"
          :content="payload.content_preview"
          :purpose="payload.purpose"
          :truncated="payload.content_truncated"
        />
        <div class="num mt-1 flex flex-wrap gap-x-3 text-[10px] text-ink-faint">
          <span>
            prompt {{ payload.prompt_tokens ?? '—' }} · completion {{ payload.completion_tokens ?? '—' }}
          </span>
          <span>{{ formatLatency(payload.latency_ms) }}</span>
          <span v-if="payload.finish_reason">finish {{ payload.finish_reason }}</span>
        </div>
      </div>
      <RuleDecisionView
        v-else-if="event.type === 'run_start' && payload.rules_decision"
        :decision="payload.rules_decision"
      />
    </div>
  </li>
</template>
