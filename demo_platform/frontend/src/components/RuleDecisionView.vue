<script setup lang="ts">
import { computed } from 'vue'

import StatusBadge from '@/components/StatusBadge.vue'
import { RISK_META, SCENARIO_LABEL, SEMANTIC_ANCHOR_LABEL } from '@/utils/meta'

const props = defineProps<{ decision: Record<string, any> }>()

const matchedRules = computed<Array<Record<string, any>>>(
  () => props.decision.matched_rules ?? [],
)
const semanticHits = computed(() =>
  Object.entries(props.decision.semantic_hits ?? {}).map(([key, score]) => ({
    label: SEMANTIC_ANCHOR_LABEL[key] ?? key,
    level: (props.decision.semantic_levels ?? {})[key] ?? '',
    score: Number(score),
  })),
)
</script>

<template>
  <div class="mt-1 space-y-1.5 rounded-lg border border-line bg-canvas/70 p-2.5">
    <div class="flex flex-wrap items-center gap-1.5">
      <StatusBadge
        :label="SCENARIO_LABEL[decision.scenario] ?? decision.scenario ?? '通用'"
        tone="slate"
        :dot="false"
      />
      <StatusBadge
        :label="decision.need_analysis ? '建议分析' : '不进入分析'"
        :tone="decision.need_analysis ? 'primary' : 'slate'"
        :dot="false"
      />
      <StatusBadge
        v-if="decision.risk_hint"
        :label="`规则风险 ${RISK_META[decision.risk_hint as keyof typeof RISK_META]?.label ?? decision.risk_hint}`"
        :tone="RISK_META[decision.risk_hint as keyof typeof RISK_META]?.tone ?? 'slate'"
        :dot="false"
      />
      <StatusBadge
        v-if="decision.require_confirm"
        label="需人工确认"
        tone="warn"
        :dot="false"
      />
    </div>
    <p v-if="decision.reason" class="text-[11px] text-ink-muted">{{ decision.reason }}</p>
    <div v-if="matchedRules.length" class="flex flex-wrap items-center gap-1">
      <span class="text-[10px] text-ink-faint">命中规则</span>
      <StatusBadge
        v-for="rule in matchedRules.slice(0, 6)"
        :key="rule.id"
        :label="rule.id"
        tone="slate"
        :dot="false"
      />
    </div>
    <div v-if="semanticHits.length" class="flex flex-wrap items-center gap-1.5">
      <span class="text-[10px] text-ink-faint">语义</span>
      <StatusBadge
        v-for="hit in semanticHits"
        :key="hit.label"
        :label="`${hit.label}${hit.level ? `·${hit.level}` : ''} ${hit.score.toFixed(2)}`"
        tone="primary"
        :dot="false"
      />
    </div>
  </div>
</template>
