<script setup lang="ts">
import { computed, ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import CopyButton from '@/components/CopyButton.vue'

const props = withDefaults(
  defineProps<{ value: unknown; title?: string; collapsedLines?: number }>(),
  { collapsedLines: 14 },
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
const shown = computed(() => {
  if (!collapsible.value || expanded.value) return text.value
  return text.value.split('\n').slice(0, props.collapsedLines).join('\n')
})
</script>

<template>
  <div class="rounded-md border border-line-soft bg-canvas/60">
    <div
      v-if="title || collapsible"
      class="flex items-center justify-between gap-2 border-b border-line-soft/70 px-2 py-1"
    >
      <span class="font-mono text-[11px] text-ink-faint">{{ title ?? `${lineCount} 行` }}</span>
      <div class="flex items-center gap-1">
        <button
          v-if="collapsible"
          class="btn btn-ghost px-1.5 py-0.5 text-[11px]"
          :aria-expanded="expanded"
          @click="expanded = !expanded"
        >
          <AppIcon :name="expanded ? 'chevronDown' : 'chevronRight'" :size="12" />
          {{ expanded ? '收起' : `展开全部（${lineCount} 行）` }}
        </button>
        <CopyButton :text="text" />
      </div>
    </div>
    <pre
      class="num overflow-x-auto px-2 py-2 text-[12px] leading-relaxed whitespace-pre-wrap text-ink"
      >{{ shown }}</pre
    >
  </div>
</template>
