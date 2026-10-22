<script setup lang="ts">
import { ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import type { Conversation } from '@/api/types'
import { formatDateTime } from '@/utils/format'
import { RISK_META, SCENARIO_LABEL, STATUS_META } from '@/utils/meta'

defineProps<{ conversations: Conversation[]; activeId: string | null; loading: boolean }>()
const emit = defineEmits<{
  select: [id: string]
  create: []
  seed: [scenario: string]
}>()

const seedOpen = ref(false)

const scenarios = [
  { id: 'product_damage', label: 'AI 破损图索赔' },
  { id: 'medical_claim', label: '诊断单与陈述矛盾' },
  { id: 'seeding_post', label: '种草帖真伪' },
]

function pickScenario(id: string): void {
  seedOpen.value = false
  emit('seed', id)
}

function initial(name: string): string {
  return (name || '客').slice(0, 1)
}
</script>

<template>
  <aside class="panel flex min-h-0 flex-col overflow-hidden" aria-label="会话列表">
    <header class="flex items-center gap-2 border-b border-line px-3.5 py-3">
      <h2 class="text-sm font-semibold">会话</h2>
      <span class="num text-xs text-ink-faint">{{ conversations.length }}</span>
      <div class="ml-auto flex items-center gap-1">
        <div class="relative">
          <button
            class="btn btn-ghost px-2 py-1 text-xs"
            :aria-expanded="seedOpen"
            @click="seedOpen = !seedOpen"
          >
            <AppIcon name="sparkle" :size="13" /> 演示剧本
          </button>
          <div
            v-if="seedOpen"
            class="absolute right-0 z-20 mt-1 w-48 overflow-hidden rounded-xl border border-line bg-surface shadow-lg"
          >
            <button
              v-for="item in scenarios"
              :key="item.id"
              class="block w-full px-3 py-2 text-left text-xs text-ink-muted transition-colors hover:bg-surface-2 hover:text-primary"
              @click="pickScenario(item.id)"
            >
              {{ item.label }}
            </button>
          </div>
        </div>
        <button class="btn btn-primary px-2.5 py-1 text-xs" @click="emit('create')">
          <AppIcon name="plus" :size="13" /> 新建
        </button>
      </div>
    </header>

    <div class="min-h-0 flex-1 overflow-y-auto">
      <p v-if="loading && !conversations.length" class="p-4 text-xs text-ink-faint">加载中…</p>
      <p v-else-if="!conversations.length" class="p-4 text-xs text-ink-faint">
        暂无会话。点击「新建」或选择「演示剧本」开始。
      </p>
      <ul v-else class="divide-y divide-line/70">
        <li v-for="conv in conversations" :key="conv.id">
          <button
            class="flex w-full items-start gap-2.5 px-3 py-2.5 text-left transition-colors"
            :class="
              conv.id === activeId
                ? 'bg-primary-weak/70'
                : 'hover:bg-surface-2/70'
            "
            @click="emit('select', conv.id)"
          >
            <span
              class="flex size-9 shrink-0 items-center justify-center rounded-full text-sm font-semibold"
              :class="conv.id === activeId ? 'bg-primary text-white' : 'bg-surface-2 text-primary'"
            >
              {{ initial(conv.customer_name) }}
            </span>
            <span class="min-w-0 flex-1">
              <span class="flex items-center gap-1.5">
                <span class="truncate text-[13px] font-medium">{{ conv.customer_name }}</span>
                <span class="ml-auto shrink-0 text-[10px] text-ink-faint">
                  {{ formatDateTime(conv.updated_at) }}
                </span>
              </span>
              <span class="mt-0.5 line-clamp-1 block text-[11.5px] text-ink-faint">
                {{ conv.last_message || '（暂无消息）' }}
              </span>
              <span v-if="conv.latest_analysis" class="mt-1 flex flex-wrap items-center gap-1">
                <StatusBadge
                  :label="STATUS_META[conv.latest_analysis.status].label"
                  :tone="STATUS_META[conv.latest_analysis.status].tone"
                  :dot="false"
                />
                <StatusBadge
                  v-if="conv.latest_analysis.risk_level"
                  :label="RISK_META[conv.latest_analysis.risk_level].label"
                  :tone="RISK_META[conv.latest_analysis.risk_level].tone"
                  :dot="false"
                />
                <span
                  v-if="conv.latest_analysis.scenario"
                  class="text-[10px] text-ink-faint"
                >
                  {{ SCENARIO_LABEL[conv.latest_analysis.scenario] ?? conv.latest_analysis.scenario }}
                </span>
              </span>
            </span>
          </button>
        </li>
      </ul>
    </div>
  </aside>
</template>
