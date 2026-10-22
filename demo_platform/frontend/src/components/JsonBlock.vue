<script setup lang="ts">
import { computed, ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'

const props = withDefaults(
  defineProps<{ value: unknown; title?: string; collapsedLines?: number }>(),
  { collapsedLines: 12 },
)

const expanded = ref(false)

const text = computed(() => {
  if (typeof props.value === 'string') return props.value
  try {
    return JSON.stringify(props.value, null, 2)
  } catch {
    return String(props.value)
  }
})

const lineCount = computed(() => text.value.split('\n').length)
const collapsible = computed(() => lineCount.value > props.collapsedLines)
const shown = computed(() =>
  !collapsible.value || expanded.value
    ? text.value
    : text.value.split('\n').slice(0, props.collapsedLines).join('\n'),
)
</script>

<template>
  <div class="rounded-lg border border-line bg-canvas/70">
    <div
      v-if="title || collapsible"
      class="flex items-center justify-between gap-2 border-b border-line px-2.5 py-1"
    >
      <span class="num text-[11px] text-ink-faint">{{ title ?? `${lineCount} 行` }}</span>
      <button
        v-if="collapsible"
        class="btn btn-ghost px-1.5 py-0.5 text-[11px]"
        :aria-expanded="expanded"
        @click="expanded = !expanded"
      >
        <AppIcon :name="expanded ? 'chevronDown' : 'chevronRight'" :size="12" />
        {{ expanded ? '收起' : `展开（${lineCount} 行）` }}
      </button>
    </div>
    <pre class="num overflow-x-auto px-2.5 py-2 text-[12px] leading-relaxed whitespace-pre-wrap text-ink-muted">{{ shown }}</pre>
  </div>
</template>
