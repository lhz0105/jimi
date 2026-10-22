<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'
import { useToast } from '@/composables/useToast'
import { TONE, type ToneKey } from '@/utils/meta'

const { toasts, dismiss } = useToast()
const kindTone: Record<string, ToneKey> = { success: 'success', error: 'danger', info: 'primary' }
const kindIcon = { success: 'check', error: 'alert', info: 'info' } as const
</script>

<template>
  <div
    class="pointer-events-none fixed right-5 bottom-5 z-[100] flex w-80 flex-col gap-2"
    aria-live="polite"
  >
    <div
      v-for="toast in toasts"
      :key="toast.id"
      class="pointer-events-auto flex items-start gap-2 rounded-xl border bg-surface px-3 py-2.5 text-sm shadow-lg"
      :class="[TONE[kindTone[toast.kind]].border, TONE[kindTone[toast.kind]].text]"
    >
      <AppIcon :name="kindIcon[toast.kind]" :size="15" class="mt-0.5" />
      <span class="min-w-0 flex-1 text-ink">{{ toast.message }}</span>
      <button class="text-ink-faint hover:text-ink" aria-label="关闭通知" @click="dismiss(toast.id)">
        <AppIcon name="close" :size="14" />
      </button>
    </div>
  </div>
</template>
