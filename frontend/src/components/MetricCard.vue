<script setup lang="ts">
import { computed } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import type { IconName } from '@/components/icons'
import { TONE, type ToneKey } from '@/utils/meta'

const props = withDefaults(
  defineProps<{
    label: string
    value: string | number
    sub?: string
    tone?: ToneKey
    icon?: IconName
  }>(),
  { tone: 'slate' },
)

const cls = computed(() => TONE[props.tone])
</script>

<template>
  <div class="card flex items-start justify-between gap-3 p-3">
    <div class="min-w-0">
      <div class="text-xs text-ink-muted">{{ label }}</div>
      <div class="num mt-1 truncate text-xl font-semibold text-ink">{{ value }}</div>
      <div v-if="sub" class="mt-0.5 truncate text-xs text-ink-faint">{{ sub }}</div>
    </div>
    <div v-if="icon" class="rounded-md border p-1.5" :class="[cls.bg, cls.border, cls.text]">
      <AppIcon :name="icon" :size="16" />
    </div>
  </div>
</template>
