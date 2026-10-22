<script setup lang="ts">
import { computed } from 'vue'

import type { ToneKey } from '@/utils/meta'
import { TONE } from '@/utils/meta'

const props = withDefaults(
  defineProps<{ label: string; tone?: ToneKey; pulse?: boolean; dot?: boolean }>(),
  { tone: 'slate', pulse: false, dot: true },
)

const cls = computed(() => TONE[props.tone])
</script>

<template>
  <span
    class="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap"
    :class="[cls.text, cls.bg, cls.border]"
  >
    <span v-if="dot" class="relative flex size-1.5">
      <span
        v-if="pulse"
        class="absolute inline-flex size-full animate-ping rounded-full opacity-60"
        :class="cls.dot"
      />
      <span class="relative inline-flex size-1.5 rounded-full" :class="cls.dot" />
    </span>
    {{ label }}
  </span>
</template>
