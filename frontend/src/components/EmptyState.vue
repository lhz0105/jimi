<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'
import type { IconName } from '@/components/icons'

withDefaults(defineProps<{ title: string; hint?: string; icon?: IconName }>(), { icon: 'info' })
</script>

<template>
  <div class="flex flex-col items-center justify-center gap-2 px-6 py-10 text-center">
    <div class="rounded-full border border-line-soft bg-surface-2/60 p-3 text-ink-faint">
      <AppIcon :name="icon" :size="20" />
    </div>
    <p class="text-sm font-medium text-ink">{{ title }}</p>
    <p v-if="hint" class="max-w-md text-xs text-ink-muted">{{ hint }}</p>
    <slot />
  </div>
</template>
