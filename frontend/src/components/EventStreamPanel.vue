<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import EventItem from '@/components/EventItem.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import type { RunEvent } from '@/api/types'
import { QUIET_EVENT_TYPES, type ToneKey } from '@/utils/meta'

const props = defineProps<{
  events: RunEvent[]
  state: 'idle' | 'connecting' | 'live' | 'paused' | 'done' | 'error'
  error: string | null
}>()

const emit = defineEmits<{ pause: []; resume: []; restart: [] }>()

const MAX_RENDER = 500

const showQuiet = ref(false)
const autoScroll = ref(true)
const atBottom = ref(true)
const scroller = ref<HTMLElement | null>(null)

const stateMeta = computed<{ label: string; tone: ToneKey; pulse: boolean }>(() => {
  switch (props.state) {
    case 'live':
      return { label: '实时', tone: 'accent', pulse: true }
    case 'connecting':
      return { label: '连接中', tone: 'info', pulse: true }
    case 'paused':
      return { label: '已暂停', tone: 'warn', pulse: false }
    case 'done':
      return { label: '已结束', tone: 'slate', pulse: false }
    case 'error':
      return { label: '连接异常', tone: 'danger', pulse: false }
    default:
      return { label: '未开始', tone: 'slate', pulse: false }
  }
})

const visibleEvents = computed(() => {
  const list = showQuiet.value
    ? props.events
    : props.events.filter((e) => !QUIET_EVENT_TYPES.has(e.type))
  return list.slice(-MAX_RENDER)
})

const hiddenCount = computed(() => {
  const list = showQuiet.value
    ? props.events
    : props.events.filter((e) => !QUIET_EVENT_TYPES.has(e.type))
  return Math.max(0, list.length - MAX_RENDER)
})

function onScroll(): void {
  const el = scroller.value
  if (!el) return
  atBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 48
  autoScroll.value = atBottom.value
}

function scrollToBottom(): void {
  const el = scroller.value
  if (!el) return
  el.scrollTop = el.scrollHeight
  autoScroll.value = true
  atBottom.value = true
}

watch(
  () => visibleEvents.value.length,
  async () => {
    if (!autoScroll.value) return
    await nextTick()
    scrollToBottom()
  },
)
</script>

<template>
  <section class="card flex min-h-0 flex-1 flex-col" aria-label="运行事件流">
    <header
      class="flex flex-wrap items-center gap-2 border-b border-line-soft px-3 py-2"
    >
      <StatusBadge :label="stateMeta.label" :tone="stateMeta.tone" :pulse="stateMeta.pulse" />
      <span class="num text-xs text-ink-muted">事件 {{ events.length }}</span>
      <span v-if="hiddenCount > 0" class="text-[11px] text-ink-faint">
        （仅渲染最近 {{ MAX_RENDER }} 条，完整事件见「原始事件」页签）
      </span>
      <span v-if="error" class="text-[11px] text-danger">{{ error }}</span>

      <div class="ml-auto flex flex-wrap items-center gap-2">
        <label class="flex cursor-pointer items-center gap-1.5 text-xs text-ink-muted">
          <input v-model="showQuiet" type="checkbox" class="accent-[var(--color-info)]" />
          显示节点/模型事件
        </label>
        <button
          v-if="state === 'live' || state === 'connecting'"
          class="btn px-2 py-1 text-xs"
          @click="emit('pause')"
        >
          <AppIcon name="pause" :size="12" /> 暂停
        </button>
        <button v-else class="btn px-2 py-1 text-xs" @click="emit('resume')">
          <AppIcon name="play" :size="12" /> 继续
        </button>
        <button class="btn px-2 py-1 text-xs" title="从头重放（断线续传不受影响）" @click="emit('restart')">
          <AppIcon name="refresh" :size="12" /> 重放
        </button>
      </div>
    </header>

    <div ref="scroller" class="relative min-h-0 flex-1 overflow-y-auto" @scroll.passive="onScroll">
      <EmptyState
        v-if="visibleEvents.length === 0"
        icon="runs"
        title="暂无事件"
        :hint="
          state === 'done'
            ? '该运行没有产生事件记录'
            : state === 'error'
              ? '事件流连接异常，可点击「重放」重试'
              : '等待运行开始输出…'
        "
      />
      <ul v-else class="divide-y divide-line-soft/40">
        <EventItem v-for="event in visibleEvents" :key="event.seq" :event="event" />
      </ul>

      <button
        v-if="!atBottom && events.length > 0"
        class="btn btn-primary sticky bottom-3 left-1/2 -translate-x-1/2 shadow-lg"
        @click="scrollToBottom"
      >
        回到最新
      </button>
    </div>
  </section>
</template>
