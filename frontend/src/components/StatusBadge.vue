<script setup lang="ts">
import { computed } from 'vue'

import { TONE, type ToneKey } from '@/utils/meta'

const props = withDefaults(
  defineProps<{ label: string; tone?: ToneKey; dot?: boolean; pulse?: boolean }>(),
  { tone: 'slate', dot: true, pulse: false },
)

const cls = computed(() => TONE[props.tone])
</script>

<template>
  <span
    class="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium"
    :class="[cls.text, cls.bg, cls.border]"
  >
    <span v-if="dot" class="size-1.5 shrink-0 rounded-full" :class="[cls.dot, pulse && 'animate-pulse']" />
    {{ label }}
  </span>
</template>
