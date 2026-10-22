<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

import AppIcon from '@/components/AppIcon.vue'

const props = withDefaults(
  defineProps<{ open: boolean; title: string; width?: string }>(),
  { width: 'max-w-xl' },
)
const emit = defineEmits<{ close: [] }>()

const panel = ref<HTMLElement | null>(null)

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') emit('close')
}

watch(
  () => props.open,
  async (open) => {
    if (open) {
      document.addEventListener('keydown', onKeydown)
      document.body.style.overflow = 'hidden'
      await nextTick()
      // 打开后聚焦面板，供键盘用户 Tab 进入（焦点不被遮罩遮挡）
      panel.value?.focus()
    } else {
      document.removeEventListener('keydown', onKeydown)
      document.body.style.overflow = ''
    }
  },
)

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-canvas/75 p-4 pt-[8vh]"
      role="presentation"
      @click.self="emit('close')"
    >
      <div
        ref="panel"
        class="card w-full shadow-2xl"
        :class="width"
        role="dialog"
        aria-modal="true"
        :aria-label="title"
        tabindex="-1"
      >
        <header class="flex items-center justify-between gap-4 border-b border-line-soft px-4 py-3">
          <h2 class="font-mono text-sm font-semibold text-ink">{{ title }}</h2>
          <button class="btn btn-ghost px-1.5 py-1" aria-label="关闭对话框" @click="emit('close')">
            <AppIcon name="close" :size="16" />
          </button>
        </header>
        <div class="max-h-[70vh] overflow-y-auto px-4 py-3">
          <slot />
        </div>
        <footer v-if="$slots.footer" class="flex justify-end gap-2 border-t border-line-soft px-4 py-3">
          <slot name="footer" />
        </footer>
      </div>
    </div>
  </Teleport>
</template>
