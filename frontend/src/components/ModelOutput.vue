<script setup lang="ts">
import { computed } from 'vue'

import JsonBlock from '@/components/JsonBlock.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import {
  CONCLUSION_META,
  DIRECTION_META,
  EVIDENCE_CATEGORY_LABEL,
  NODE_LABEL,
  RISK_META,
} from '@/utils/meta'

type Tone = 'accent' | 'danger' | 'warn' | 'info' | 'violet' | 'teal' | 'slate'

const props = defineProps<{
  content?: string
  purpose?: string
  truncated?: boolean
}>()

function parseContent(raw?: string): Record<string, any> | null {
  if (!raw) return null
  let text = raw.trim()
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/i)
  if (fenced) text = fenced[1].trim()
  try {
    const value = JSON.parse(text)
    return value && typeof value === 'object' ? value : null
  } catch {
    /* 继续尝试截取 JSON */
  }
  const start = text.indexOf('{')
  const end = text.lastIndexOf('}')
  if (start >= 0 && end > start) {
    try {
      return JSON.parse(text.slice(start, end + 1))
    } catch {
      return null
    }
  }
  return null
}

const data = computed(() => parseContent(props.content))
const kind = computed<'adjudicate' | 'investigate' | 'consistency' | 'vision' | 'generic'>(() => {
  const d = data.value
  if (!d) return 'generic'
  if (d.conclusion && (d.risk_level || d.evidence_refs)) return 'adjudicate'
  if (Array.isArray(d.new_evidence)) return 'investigate'
  if (Array.isArray(d.contradictions) || Array.isArray(d.inconsistencies)) return 'consistency'
  if (
    d.product_region_verdict ||
    Array.isArray(d.regions) ||
    d.fields ||
    d.style ||
    d.tamper_suspected !== undefined
  ) {
    return 'vision'
  }
  return 'generic'
})

const severityMeta: Record<string, { label: string; tone: Tone }> = {
  clear: { label: '明确', tone: 'danger' },
  minor: { label: '轻微', tone: 'warn' },
  uncertain: { label: '不确定', tone: 'slate' },
}
const verdictMeta: Record<string, { label: string; tone: Tone }> = {
  genuine: { label: '真实区域', tone: 'accent' },
  suspected_ai: { label: '疑似 AIGC', tone: 'danger' },
  uncertain: { label: '不确定', tone: 'warn' },
}
const styleMeta: Record<string, { label: string; tone: Tone }> = {
  casual: { label: '随手拍', tone: 'accent' },
  commercial: { label: '商单/精修', tone: 'warn' },
  uncertain: { label: '不确定', tone: 'slate' },
}
const relationMeta: Record<string, { label: string; tone: Tone }> = {
  related: { label: '篡改涉及诉求', tone: 'danger' },
  unrelated: { label: '篡改与诉求无关', tone: 'accent' },
  uncertain: { label: '相关性不确定', tone: 'warn' },
}

function actionText(action: any): string {
  if (typeof action === 'string') return action
  return `${action?.action ?? ''}${action?.note ? ` · ${action.note}` : ''}`
}
</script>

<template>
  <div class="mt-1.5 rounded border border-line-soft bg-canvas/40 p-2.5">
    <div class="mb-1.5 flex flex-wrap items-center gap-2">
      <span class="text-[11px] font-semibold text-ink-muted">模型输出</span>
      <span v-if="purpose" class="text-[10px] text-ink-faint">
        {{ NODE_LABEL[purpose] ?? purpose }}
      </span>
      <span v-if="truncated" class="text-[10px] text-warn">（预览已截断）</span>
    </div>

    <template v-if="data">
      <!-- 裁决 -->
      <div v-if="kind === 'adjudicate'" class="space-y-1.5">
        <div class="flex flex-wrap items-center gap-2">
          <StatusBadge
            :label="CONCLUSION_META[data.conclusion]?.label ?? data.conclusion"
            :tone="CONCLUSION_META[data.conclusion]?.tone ?? 'slate'"
          />
          <StatusBadge
            v-if="data.risk_level"
            :label="`风险 ${RISK_META[data.risk_level as keyof typeof RISK_META]?.label ?? data.risk_level}`"
            :tone="RISK_META[data.risk_level as keyof typeof RISK_META]?.tone ?? 'slate'"
          />
          <span class="num text-[11px] text-ink-muted">
            置信度 {{ Number(data.confidence ?? 0).toFixed(2) }}
          </span>
        </div>
        <p class="text-[12.5px] leading-relaxed text-ink">{{ data.summary }}</p>
        <div v-if="data.evidence_refs?.length" class="flex flex-wrap items-center gap-1">
          <span class="text-[10px] text-ink-faint">证据引用</span>
          <StatusBadge
            v-for="ref in data.evidence_refs"
            :key="ref"
            :label="String(ref)"
            tone="slate"
            :dot="false"
          />
        </div>
        <ul v-if="data.key_counterpoints?.length" class="space-y-0.5 text-[11px] text-ink-muted">
          <li v-for="(item, index) in data.key_counterpoints" :key="index">· {{ item }}</li>
        </ul>
        <ul v-if="data.recommended_actions?.length" class="space-y-0.5 text-[11px] text-ink-muted">
          <li v-for="(action, index) in data.recommended_actions" :key="index">
            → {{ actionText(action) }}
          </li>
        </ul>
      </div>

      <!-- 调查 -->
      <div v-else-if="kind === 'investigate'" class="space-y-1.5">
        <div
          v-for="(ev, index) in data.new_evidence"
          :key="index"
          class="rounded border border-line-soft bg-canvas/50 p-2"
        >
          <div class="flex flex-wrap items-center gap-2">
            <StatusBadge
              :label="EVIDENCE_CATEGORY_LABEL[ev.category] ?? ev.category ?? '证据'"
              tone="slate"
              :dot="false"
            />
            <StatusBadge
              v-if="ev.direction"
              :label="DIRECTION_META[ev.direction]?.label ?? ev.direction"
              :tone="DIRECTION_META[ev.direction]?.tone ?? 'slate'"
            />
            <span v-if="ev.weight !== undefined" class="num text-[10px] text-ink-faint">
              权重 {{ ev.weight }}
            </span>
          </div>
          <p class="mt-1 text-[12.5px] text-ink">{{ ev.finding }}</p>
          <p v-if="ev.source_detail" class="mt-0.5 text-[10px] text-ink-faint">
            {{ ev.source_detail }}
          </p>
        </div>
        <div v-if="data.open_questions?.length" class="text-[11px] text-ink-muted">
          <span class="text-ink-faint">待确认：</span>
          <span v-for="(q, index) in data.open_questions" :key="index">
            {{ index ? '；' : '' }}{{ q }}
          </span>
        </div>
        <p v-if="data.notes" class="text-[11px] text-ink-muted">{{ data.notes }}</p>
      </div>

      <!-- 一致性 -->
      <div v-else-if="kind === 'consistency'" class="space-y-1.5">
        <div
          v-for="(item, index) in data.contradictions ?? []"
          :key="`c${index}`"
          class="rounded border border-line-soft bg-canvas/50 p-2 text-[12px]"
        >
          <div class="flex flex-wrap items-center gap-2">
            <StatusBadge
              :label="severityMeta[item.severity]?.label ?? item.severity ?? '不确定'"
              :tone="severityMeta[item.severity]?.tone ?? 'slate'"
              :dot="false"
            />
            <span class="font-medium">{{ item.field }}</span>
          </div>
          <p class="mt-0.5 text-ink-muted">客户：{{ item.customer_says }}</p>
          <p class="text-ink-muted">单据：{{ item.document_says }}</p>
          <p class="mt-0.5 text-ink">{{ item.finding }}</p>
        </div>
        <div
          v-for="(item, index) in data.inconsistencies ?? []"
          :key="`i${index}`"
          class="rounded border border-line-soft bg-canvas/50 p-2 text-[12px]"
        >
          <div class="flex flex-wrap items-center gap-2">
            <StatusBadge
              :label="severityMeta[item.severity]?.label ?? item.severity ?? '不确定'"
              :tone="severityMeta[item.severity]?.tone ?? 'slate'"
              :dot="false"
            />
            <span class="font-medium">{{ item.aspect }}</span>
          </div>
          <p class="mt-0.5 text-ink">{{ item.detail }}</p>
        </div>
        <div v-if="data.commercial_signals?.length" class="text-[11px] text-ink-muted">
          商业信号：{{ data.commercial_signals.join('、') }}
        </div>
        <p v-if="data.consistency_score !== undefined" class="num text-[11px] text-ink-muted">
          一致性评分 {{ Number(data.consistency_score).toFixed(2) }}
        </p>
        <p v-if="data.notes" class="text-[11px] text-ink-muted">{{ data.notes }}</p>
      </div>

      <!-- 识图 -->
      <div v-else-if="kind === 'vision'" class="space-y-1.5">
        <p class="text-[12.5px] text-ink">{{ data.summary }}</p>
        <div class="flex flex-wrap items-center gap-2">
          <StatusBadge
            v-if="data.product_region_verdict"
            :label="verdictMeta[data.product_region_verdict]?.label ?? data.product_region_verdict"
            :tone="verdictMeta[data.product_region_verdict]?.tone ?? 'slate'"
          />
          <StatusBadge
            v-if="data.style"
            :label="styleMeta[data.style]?.label ?? data.style"
            :tone="styleMeta[data.style]?.tone ?? 'slate'"
          />
          <StatusBadge
            v-if="data.tamper_relation_to_claim"
            :label="relationMeta[data.tamper_relation_to_claim]?.label ?? data.tamper_relation_to_claim"
            :tone="relationMeta[data.tamper_relation_to_claim]?.tone ?? 'slate'"
          />
          <StatusBadge
            v-if="data.tamper_suspected"
            label="疑似篡改"
            tone="danger"
            :dot="false"
          />
          <span v-if="data.raw_confidence !== undefined" class="num text-[10px] text-ink-muted">
            置信度 {{ Number(data.raw_confidence).toFixed(2) }}
          </span>
        </div>
        <div v-if="data.fields" class="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px]">
          <template v-for="(value, key) in data.fields" :key="key">
            <span class="text-ink-faint">{{ key }}</span>
            <span class="text-ink-muted">{{ value ?? '—' }}</span>
          </template>
        </div>
        <ul v-if="data.regions?.length" class="space-y-0.5 text-[11px] text-ink-muted">
          <li v-for="(region, index) in data.regions" :key="index">
            · {{ region.name }}：{{ region.aigc_suspected ? '疑似 AIGC' : '未见 AIGC' }}
            <span v-if="region.aigc_suspected && region.relation_to_claim" class="text-ink-faint">
              （{{ relationMeta[region.relation_to_claim]?.label ?? region.relation_to_claim }}）
            </span>
            <span v-if="region.reason" class="text-ink-faint">（{{ region.reason }}）</span>
          </li>
        </ul>
        <p v-if="data.tamper_location_summary" class="text-[11px] text-ink-muted">
          篡改位置：{{ data.tamper_location_summary }}
        </p>
        <p v-if="data.claim_relevance_reason" class="text-[11px] text-ink-muted">
          诉求相关性：{{ data.claim_relevance_reason }}
        </p>
        <p v-if="data.signals?.length" class="text-[11px] text-ink-muted">
          信号：{{ data.signals.join('、') }}
        </p>
        <p v-if="data.tamper_hints?.length" class="text-[11px] text-ink-muted">
          篡改线索：{{ data.tamper_hints.join('、') }}
        </p>
        <p v-if="data.irrelevant_region_aigc" class="text-[11px] text-ink-faint">
          与诉求无关区域存在 AIGC，按判定原则不计入风险升级
        </p>
        <p v-if="data.caveats?.length" class="text-[11px] text-ink-faint">
          不确定因素：{{ data.caveats.join('、') }}
        </p>
      </div>

      <JsonBlock v-else :value="data" title="模型输出 JSON" :collapsed-lines="8" />
    </template>

    <p v-else class="text-[12px] whitespace-pre-wrap text-ink-muted">
      {{ content || '（无模型正文）' }}
    </p>
  </div>
</template>
