<script setup lang="ts">
import { computed } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import ModelOutput from '@/components/ModelOutput.vue'
import RuleDecisionView from '@/components/RuleDecisionView.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import type { RunEvent } from '@/api/types'
import { formatLatency, formatTime, formatTokens } from '@/utils/format'
import {
  CONCLUSION_META,
  EVIDENCE_CATEGORY_LABEL,
  eventMeta,
  NODE_LABEL,
  RISK_META,
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

const evidence = computed<any>(() =>
  props.event.type === 'evidence' ? payload.value.evidence : null,
)
const ragHits = computed<Array<Record<string, any>>>(() =>
  props.event.type === 'rag_hit' ? (payload.value.hits ?? []) : [],
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
      return p.kind === 'reasoning' ? '深度推理' : '步骤摘要'
    case 'llm_call':
      return `${p.model ?? ''} · ${NODE_LABEL[p.purpose] ?? p.purpose ?? '模型'} · 输入 ${p.message_count ?? '?'} 条`
    case 'llm_result':
      return `${formatTokens(p.prompt_tokens)} → ${formatTokens(p.completion_tokens)} tokens · ${formatLatency(p.latency_ms)}`
    case 'tool_call':
      return `${TOOL_LABEL[p.tool] ?? p.tool}${p.cache_lookup ? '（缓存查询）' : ''}`
    case 'tool_result':
      return `${TOOL_LABEL[p.tool] ?? p.tool} · ${formatLatency(p.latency_ms)}${p.cache_hit ? ' · 缓存命中' : ''}`
    case 'rag_hit':
      return `${p.rag_mode ?? 'hybrid'} · 命中 ${ragHits.value.length} 条`
    case 'evidence':
      return EVIDENCE_CATEGORY_LABEL[evidence.value?.category] ?? evidence.value?.category ?? ''
    case 'verdict':
      return `置信度 ${Number(p.confidence ?? 0).toFixed(2)}`
    case 'node_start':
    case 'node_end':
      return props.event.type === 'node_end' ? formatLatency(p.latency_ms) : ''
    case 'run_start':
      return `图片 ${p.image_count ?? 0} 张 · 消息 ${p.message_count ?? 0} 条`
    case 'run_end':
      return `${p.status ?? ''}`
    default:
      return ''
  }
})
</script>

<template>
  <li class="flex gap-2.5 px-3 py-2">
    <div class="num w-14 shrink-0 pt-0.5 text-right text-[10px] leading-4 text-ink-faint">
      <div>#{{ event.seq }}</div>
      <div>{{ formatTime(event.ts) }}</div>
    </div>

    <div class="pt-0.5">
      <span
        class="flex size-6 items-center justify-center rounded-full border"
        :class="[tone.bg, tone.border, tone.text]"
      >
        <AppIcon :name="meta.icon" :size="12" />
      </span>
    </div>

    <div class="min-w-0 flex-1 pb-1">
      <header class="flex flex-wrap items-center gap-x-2 gap-y-0.5">
        <span class="text-xs font-semibold" :class="tone.text">{{ meta.label }}</span>
        <span v-if="nodeLabel" class="text-[11px] text-ink-faint">{{ nodeLabel }}</span>
        <span v-if="oneLine" class="num text-[11px] text-ink-muted">{{ oneLine }}</span>
      </header>

      <p
        v-if="event.type === 'thought'"
        class="mt-1 rounded-lg border-l-2 bg-canvas/80 py-1 pl-2.5 text-[12.5px] leading-relaxed whitespace-pre-wrap text-ink"
        :class="tone.border"
      >
        {{ payload.text }}
      </p>

      <p
        v-else-if="event.type === 'tool_result'"
        class="mt-1 rounded-lg border border-line bg-canvas/80 px-2 py-1 text-[12px] whitespace-pre-wrap text-ink-muted"
      >
        {{ payload.result_preview }}
      </p>

      <p
        v-else-if="event.type === 'tool_error' || event.type === 'error'"
        class="mt-1 rounded-lg border border-red-200 bg-red-50 px-2 py-1 text-[12px] whitespace-pre-wrap text-danger"
      >
        {{ payload.message }}
      </p>

      <p
        v-else-if="event.type === 'warning' || event.type === 'budget_warning'"
        class="mt-1 rounded-lg border border-amber-200 bg-amber-50 px-2 py-1 text-[12px] whitespace-pre-wrap text-warn"
      >
        {{ payload.message }}
      </p>

      <div
        v-else-if="event.type === 'tool_call' && toolArgs"
        class="mt-1 space-y-0.5 rounded-lg border border-line bg-canvas/70 px-2 py-1.5 text-[11px]"
      >
        <div v-for="(value, key) in toolArgs" :key="key" class="flex gap-2">
          <span class="shrink-0 text-ink-faint">{{ key }}</span>
          <span class="min-w-0 break-all text-ink-muted">{{ argText(value) }}</span>
        </div>
      </div>
      <p
        v-else-if="event.type === 'tool_call' && payload.args_preview"
        class="mt-1 rounded-lg border border-line bg-canvas/70 px-2 py-1 text-[11px] whitespace-pre-wrap text-ink-muted"
      >
        {{ payload.args_preview }}
      </p>

      <div
        v-else-if="evidence"
        class="mt-1 rounded-lg border border-amber-200 bg-amber-50/60 p-2"
      >
        <div class="flex flex-wrap items-center gap-2 text-[11px]">
          <span class="num text-ink-faint">{{ evidence.evidence_id }}</span>
          <span class="text-ink-muted">{{ EVIDENCE_CATEGORY_LABEL[evidence.category] ?? evidence.category }}</span>
          <span class="num text-ink-muted">权重 {{ evidence.weight }}</span>
        </div>
        <p class="mt-0.5 text-[12.5px]">{{ evidence.finding }}</p>
      </div>

      <div v-else-if="event.type === 'rag_hit'" class="mt-1 space-y-1">
        <p class="num text-[11px] text-ink-faint">查询：{{ payload.query }}</p>
        <div
          v-for="hit in ragHits"
          :key="hit.chunk_id"
          class="rounded-lg border border-line bg-canvas/70 px-2 py-1"
        >
          <div class="flex flex-wrap items-center gap-2 text-[11px]">
            <span class="text-[12px] font-medium text-ink">{{ hit.doc_title }}</span>
            <span class="num text-ink-muted">
              dense {{ hit.score_dense ?? '—' }} · bm25 {{ hit.score_bm25 ?? '—' }}
            </span>
          </div>
          <p class="mt-0.5 text-[11.5px] whitespace-pre-wrap text-ink-muted">{{ hit.preview }}</p>
        </div>
      </div>

      <div
        v-else-if="event.type === 'verdict'"
        class="mt-1 flex flex-wrap items-center gap-2 rounded-lg border border-line bg-canvas/70 px-2 py-1.5"
      >
        <StatusBadge
          :label="CONCLUSION_META[payload.conclusion]?.label ?? String(payload.conclusion ?? '')"
          :tone="CONCLUSION_META[payload.conclusion]?.tone ?? 'slate'"
          :dot="false"
        />
        <StatusBadge
          v-if="payload.risk_level"
          :label="`风险 ${RISK_META[payload.risk_level as keyof typeof RISK_META]?.label ?? payload.risk_level}`"
          :tone="RISK_META[payload.risk_level as keyof typeof RISK_META]?.tone ?? 'slate'"
          :dot="false"
        />
        <span class="text-[12px] text-ink-muted">{{ payload.summary }}</span>
      </div>

      <div
        v-else-if="event.type === 'llm_call'"
        class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-line bg-canvas/70 px-2 py-1.5 text-[11px] text-ink-muted"
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
