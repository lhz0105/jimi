<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import type { Attachment, Conversation, Message } from '@/api/types'
import { formatTime } from '@/utils/format'
import { RISK_META, SCENARIO_LABEL, semanticHitText } from '@/utils/meta'

const props = defineProps<{
  conversation: Conversation | null
  messages: Message[]
  attachments: Attachment[]
  sending: boolean
  starting: boolean
}>()

const emit = defineEmits<{
  send: [payload: { text: string; attachmentIds: string[] }]
  upload: [file: File]
  analyze: [message: Message]
  delete: []
}>()

const draft = ref('')
const pending = ref<Attachment[]>([])
const uploading = ref(false)
const scroller = ref<HTMLElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

const attachmentsByMessage = computed(() => {
  const map = new Map<string, Attachment[]>()
  for (const att of props.attachments) {
    if (!att.message_id) continue
    const list = map.get(att.message_id) ?? []
    list.push(att)
    map.set(att.message_id, list)
  }
  return map
})

function scrollToBottom(): void {
  const el = scroller.value
  if (el) el.scrollTop = el.scrollHeight
}

watch(
  () => props.messages.length,
  async () => {
    await nextTick()
    scrollToBottom()
  },
  { immediate: true },
)

watch(
  () => props.conversation?.id,
  async () => {
    pending.value = []
    draft.value = ''
    await nextTick()
    scrollToBottom()
  },
)

function pickFile(): void {
  fileInput.value?.click()
}

async function onFileChange(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  uploading.value = true
  emit('upload', file)
}

function removePending(id: string): void {
  pending.value = pending.value.filter((a) => a.id !== id)
}

function send(): void {
  const text = draft.value.trim()
  if ((!text && !pending.value.length) || props.sending) return
  emit('send', { text, attachmentIds: pending.value.map((a) => a.id) })
  draft.value = ''
  pending.value = []
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    send()
  }
}

defineExpose({
  addPending(attachment: Attachment) {
    pending.value = [...pending.value, attachment]
  },
  setUploading(value: boolean) {
    uploading.value = value
  },
})
</script>

<template>
  <section class="panel flex min-h-0 flex-col overflow-hidden" aria-label="聊天窗口">
    <header class="flex items-center gap-2 border-b border-line px-4 py-3">
      <span class="flex size-8 items-center justify-center rounded-full bg-primary-weak text-sm font-semibold text-primary">
        {{ (conversation?.customer_name || '客').slice(0, 1) }}
      </span>
      <div class="min-w-0">
        <h2 class="truncate text-sm font-semibold">
          {{ conversation?.customer_name || '未选择会话' }}
        </h2>
        <p class="text-[11px] text-ink-faint">
          {{ conversation?.channel === 'seed_post' ? '种草内容渠道' : '在线客服' }}
        </p>
      </div>
      <div class="ml-auto flex items-center gap-1">
        <StatusBadge label="Agent 在线" tone="success" :dot="true" :pulse="true" />
        <button
          class="btn btn-ghost px-2 py-1"
          title="删除该会话"
          aria-label="删除该会话"
          @click="emit('delete')"
        >
          <AppIcon name="trash" :size="14" />
        </button>
      </div>
    </header>

    <div ref="scroller" class="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4" aria-live="polite">
      <p v-if="!conversation" class="py-16 text-center text-sm text-ink-faint">
        选择左侧会话，或新建一个会话开始演示
      </p>
      <template v-else>
        <p v-if="!messages.length" class="py-16 text-center text-sm text-ink-faint">
          暂无消息。发送一条客户消息试试（例如："收到的杯子碎了，必须退款"）。
        </p>
        <div
          v-for="message in messages"
          :key="message.id"
          class="group flex flex-col"
          :class="message.role === 'agent' ? 'items-end' : 'items-start'"
        >
          <div class="mb-1 flex items-center gap-1.5 text-[10px] text-ink-faint">
            <span>{{ message.role === 'customer' ? conversation.customer_name : '客服 · 你' }}</span>
            <span>{{ formatTime(message.created_at) }}</span>
            <button
              v-if="message.role === 'customer'"
              class="flex items-center gap-0.5 rounded px-1 py-0.5 text-[10px] text-primary opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 disabled:opacity-40"
              :disabled="starting"
              title="强制分析该会话"
              @click="emit('analyze', message)"
            >
              <AppIcon name="play" :size="10" /> 分析
            </button>
          </div>
          <div
            class="max-w-[82%] rounded-2xl px-3.5 py-2 text-[13px] leading-relaxed shadow-sm"
            :class="
              message.role === 'agent'
                ? 'rounded-br-md bg-primary-weak text-ink'
                : 'rounded-bl-md border border-line bg-surface text-ink'
            "
          >
            <p v-if="message.content" class="whitespace-pre-wrap">{{ message.content }}</p>
            <div
              v-if="attachmentsByMessage.get(message.id)?.length"
              class="mt-1.5 flex flex-wrap gap-1.5"
            >
              <a
                v-for="att in attachmentsByMessage.get(message.id)"
                :key="att.id"
                :href="att.url"
                target="_blank"
                rel="noreferrer"
                class="block overflow-hidden rounded-lg border border-line"
              >
                <img :src="att.url" alt="客户上传的图片" class="h-24 w-24 object-cover" />
              </a>
            </div>
          </div>

          <!-- 触发提示（内联、克制）：命中规则时才出现 -->
          <div
            v-if="message.check_result?.need_analysis"
            class="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] text-ink-faint"
          >
            <AppIcon name="shield" :size="11" class="text-primary" />
            <span>规则命中：{{ SCENARIO_LABEL[message.check_result.scenario ?? ''] ?? message.check_result.scenario }}</span>
            <StatusBadge
              v-if="message.check_result.risk_hint"
              :label="`规则风险 ${RISK_META[message.check_result.risk_hint as 'high']?.label ?? message.check_result.risk_hint}`"
              :tone="RISK_META[message.check_result.risk_hint as 'high']?.tone ?? 'slate'"
              :dot="false"
            />
            <span v-if="message.check_result.semantic_status === 'matched' && Object.keys(message.check_result.semantic_hits ?? {}).length">
              · 语义命中 {{ semanticHitText(message.check_result.semantic_hits, message.check_result.semantic_levels) }}
            </span>
          </div>
        </div>
      </template>
    </div>

    <footer v-if="conversation" class="border-t border-line px-3 py-2.5">
      <div v-if="pending.length" class="mb-2 flex flex-wrap gap-2">
        <div v-for="att in pending" :key="att.id" class="relative">
          <img :src="att.url" alt="待发送图片" class="h-14 w-14 rounded-lg border border-line object-cover" />
          <button
            class="absolute -top-1.5 -right-1.5 flex size-5 items-center justify-center rounded-full border border-line bg-surface text-ink-muted shadow"
            aria-label="移除图片"
            @click="removePending(att.id)"
          >
            <AppIcon name="close" :size="11" />
          </button>
        </div>
      </div>
      <div class="flex items-end gap-2">
        <button
          class="btn px-2.5 py-2"
          :disabled="uploading"
          title="上传图片"
          aria-label="上传图片"
          @click="pickFile"
        >
          <AppIcon name="image" :size="16" />
        </button>
        <input ref="fileInput" type="file" accept="image/*" class="hidden" @change="onFileChange" />
        <textarea
          v-model="draft"
          class="input max-h-28 min-h-[42px] flex-1 resize-none py-2.5"
          rows="1"
          placeholder="输入客户消息，Enter 发送，Shift+Enter 换行"
          aria-label="消息输入框"
          @keydown="onKeydown"
        />
        <button
          class="btn btn-primary px-3.5 py-2.5"
          :disabled="sending || (!draft.trim() && !pending.length)"
          @click="send"
        >
          <AppIcon name="send" :size="15" />
          {{ sending ? '发送中…' : '发送' }}
        </button>
      </div>
    </footer>
  </section>
</template>
