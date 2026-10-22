<script setup lang="ts">
import { ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'

const props = defineProps<{ text: string; label?: string }>()
const copied = ref(false)

async function copy(): Promise<void> {
  try {
    await navigator.clipboard.writeText(props.text)
    copied.value = true
    window.setTimeout(() => (copied.value = false), 1500)
  } catch {
    copied.value = false
  }
}
</script>

<template>
  <button
    class="btn btn-ghost px-1.5 py-1 text-xs"
    :aria-label="copied ? '已复制' : (label ?? '复制')"
    @click.stop="copy"
  >
    <AppIcon :name="copied ? 'check' : 'copy'" :size="13" />
    <span v-if="label" class="hidden sm:inline">{{ copied ? '已复制' : label }}</span>
  </button>
</template>
