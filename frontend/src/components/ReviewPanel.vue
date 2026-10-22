<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import MarkdownView from '@/components/MarkdownView.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { fetchRunReview, streamRunReview } from '@/api/admin'
import { errorText } from '@/api/client'
import type { HumanVerdict, ReviewState } from '@/api/types'
import { useToast } from '@/composables/useToast'
import { downloadText, formatDateTime } from '@/utils/format'
import {
  HUMAN_VERDICT_META,
  PRIOR_FEEDBACK_META,
  REVIEW_STATUS_META,
} from '@/utils/meta'

const props = defineProps<{ runId: string; eligible: boolean }>()
const toast = useToast()

const state = ref<ReviewState | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const submitting = ref(false)
const verdict = ref<HumanVerdict>('fraud')
const reason = ref('')
const reviewer = ref('人工复核员')
const draft = ref('')
const scroller = ref<HTMLElement | null>(null)

const streaming = ref(false)
const streamText = ref('')
const streamKind = ref<'interview' | 'case'>('interview')
const streamStatus = ref('')

const review = computed(() => state.value?.review ?? null)
const caseDoc = computed(() => state.value?.case ?? null)
const messages = computed(() => state.value?.messages ?? [])
const roleLabel: Record<string, string> = {
  human: '你（人工复核）',
  agent: '案例整理官',
  system: '系统',
}

let scrollFrame: number | null = null
function scrollToBottom(): void {
  const el = scroller.value
  if (el) el.scrollTop = el.scrollHeight
}
function scheduleScroll(): void {
  if (scrollFrame !== null) return
  scrollFrame = window.requestAnimationFrame(() => {
    scrollFrame = null
    void nextTick(scrollToBottom)
  })
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    state.value = await fetchRunReview(props.runId)
  } catch (err) {
    error.value = errorText(err)
  } finally {
    loading.value = false
  }
}

async function runStream(
  payload: Record<string, unknown>,
  initialKind: 'interview' | 'case',
): Promise<void> {
  streaming.value = true
  streamText.value = ''
  streamKind.value = initialKind
  streamStatus.value = initialKind === 'case' ? '正在生成案例…' : '正在思考…'
  try {
    await streamRunReview(props.runId, payload, {
      onStatus: (text) => {
        streamStatus.value = text
        if (text.includes('生成案例')) streamKind.value = 'case'
        scheduleScroll()
      },
      onToken: (text, kind) => {
        streamKind.value = kind
        streamText.value += text
        scheduleScroll()
      },
      onState: (next) => {
        state.value = next
        if (next.case) {
          // 最终案例已到达，避免与流式预览重复
          streamText.value = ''
        } else if (streamKind.value === 'interview' && next.review) {
          // 追问正文已落库，避免与流式预览重复
          streamText.value = ''
        }
        scheduleScroll()
      },
      onError: (message) => toast.error(message),
    })
    if (state.value?.review?.status === 'generated') {
      toast.success('案例已生成并写入先前案例库')
    }
  } catch (err) {
    toast.error(errorText(err))
    await load()
  } finally {
    streaming.value = false
    streamText.value = ''
    streamStatus.value = ''
  }
}

async function submit(): Promise<void> {
  if (!reason.value.trim() || streaming.value) {
    if (!reason.value.trim()) toast.error('请填写判决原因')
    return
  }
  submitting.value = true
  try {
    await runStream(
      {
        action: 'start',
        verdict: verdict.value,
        reason: reason.value.trim(),
        reviewer: reviewer.value.trim() || '人工复核员',
      },
      'interview',
    )
  } finally {
    submitting.value = false
  }
}

async function send(): Promise<void> {
  const content = draft.value.trim()
  if (!content || streaming.value) return
  draft.value = ''
  await runStream({ action: 'answer', content }, 'interview')
}

async function forceGenerate(): Promise<void> {
  if (streaming.value) return
  await runStream({ action: 'generate' }, 'case')
}

function downloadCase(): void {
  if (!caseDoc.value) return
  downloadText(`prior-case-${caseDoc.value.id}.md`, caseDoc.value.markdown)
}

watch(
  () => [messages.value.length, Boolean(caseDoc.value)],
  async () => {
    await nextTick()
    scrollToBottom()
  },
)

onMounted(load)
</script>

<template>
  <section class="card flex min-h-[56vh] flex-col overflow-hidden">
    <header class="flex flex-wrap items-center gap-2 border-b border-line-soft px-3 py-2">
      <AppIcon name="scale" :size="14" class="text-violet" />
      <h2 class="font-mono text-xs font-semibold text-ink-muted">人工判决</h2>
      <StatusBadge
        v-if="review"
        :label="REVIEW_STATUS_META[review.status]?.label ?? review.status"
        :tone="REVIEW_STATUS_META[review.status]?.tone ?? 'slate'"
      />
      <span v-if="review" class="text-[11px] text-ink-faint">
        复核人 {{ review.reviewer || '人工复核员' }} · {{ review.agent_turns }}/{{ state?.max_turns ?? 4 }} 轮
      </span>
      <span
        v-if="review?.llm_usage?.est_cost"
        class="num text-[11px] text-ink-faint"
      >
        · 复核消耗 ¥{{ Number(review.llm_usage.est_cost).toFixed(6) }}
      </span>
      <span v-if="streaming" class="text-[11px] text-info">{{ streamStatus || '正在输出…' }}</span>
      <button
        class="btn btn-ghost ml-auto px-2 py-1 text-xs"
        :disabled="loading || streaming"
        @click="load"
      >
        <AppIcon name="refresh" :size="13" /> 刷新
      </button>
    </header>

    <p v-if="loading" class="p-4 text-sm text-ink-muted">加载中…</p>
    <EmptyState
      v-else-if="error"
      icon="alert"
      title="人工判决加载失败"
      :hint="error"
    >
      <button class="btn mt-2" @click="load">重试</button>
    </EmptyState>

    <!-- 首次判决 / 启动流式追问 -->
    <div v-else-if="!review" class="min-h-0 flex-1 overflow-y-auto p-4">
      <div v-if="streaming" class="space-y-2">
        <p class="text-xs text-ink-faint">{{ streamStatus || '正在思考…' }}</p>
        <div
          v-if="streamText"
          class="rounded-xl border border-line-soft bg-surface-2/60 px-3 py-2 text-[13px] whitespace-pre-wrap text-ink"
        >
          {{ streamText }}
        </div>
      </div>
      <EmptyState
        v-else-if="!eligible"
        icon="scale"
        title="该运行未达到人工复核条件"
        hint="只有系统结论为可疑/欺诈，或建议人工复核的运行才开放人工判决。"
      />
      <form v-else class="mx-auto max-w-xl space-y-3" @submit.prevent="submit">
        <div>
          <p class="mb-1.5 text-[11px] text-ink-muted">人工判决</p>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="(meta, key) in HUMAN_VERDICT_META"
              :key="key"
              type="button"
              class="btn px-3 py-1.5 text-xs"
              :class="verdict === key ? 'btn-primary' : ''"
              :disabled="streaming"
              @click="verdict = key as HumanVerdict"
            >
              {{ meta.label }}
            </button>
          </div>
        </div>
        <div>
          <label class="mb-1 block text-[11px] text-ink-muted" for="review-reason">
            判决原因（必填）
          </label>
          <textarea
            id="review-reason"
            v-model="reason"
            class="input h-32 w-full resize-y"
            placeholder="写明哪条证据起决定作用、为何排除其他可能，以及系统未捕获的细节…"
            :disabled="streaming"
          />
        </div>
        <div>
          <label class="mb-1 block text-[11px] text-ink-muted" for="review-reviewer">复核人</label>
          <input
            id="review-reviewer"
            v-model="reviewer"
            class="input w-full"
            maxlength="80"
            :disabled="streaming"
          />
        </div>
        <button
          class="btn btn-primary"
          type="submit"
          :disabled="submitting || streaming || !reason.trim()"
        >
          <AppIcon name="play" :size="14" />
          {{ submitting ? '提交中…' : '提交判决并开始对话' }}
        </button>
        <p class="text-[11px] leading-relaxed text-ink-faint">
          提交后 Agent 仅在需要时追问关键细节（最多 {{ state?.max_turns ?? 4 }} 轮）；若已理解判决依据会直接生成案例，你也可以随时手动生成。
        </p>
      </form>
    </div>

    <!-- 对话 + 案例 -->
    <template v-else>
      <div class="flex flex-wrap items-center gap-2 border-b border-line-soft px-3 py-2">
        <StatusBadge
          :label="HUMAN_VERDICT_META[review.verdict]?.label ?? review.verdict"
          :tone="HUMAN_VERDICT_META[review.verdict]?.tone ?? 'slate'"
        />
        <span class="text-[11px] text-ink-faint">
          系统判决中的疑点已由人工确认；剩余 {{ state?.turns_left ?? 0 }} 轮追问机会
        </span>
      </div>

      <div ref="scroller" class="min-h-0 flex-1 space-y-3 overflow-y-auto p-4" aria-live="polite">
        <div
          v-for="message in messages"
          :key="message.id"
          class="flex flex-col"
          :class="message.role === 'human' ? 'items-end' : 'items-start'"
        >
          <div class="mb-1 text-[10px] text-ink-faint">
            {{ roleLabel[message.role] ?? message.role }} · {{ formatDateTime(message.created_at) }}
          </div>
          <div
            class="max-w-[88%] rounded-2xl px-3 py-2 text-[13px] whitespace-pre-wrap"
            :class="
              message.role === 'human'
                ? 'bg-violet/15 text-ink'
                : message.role === 'system'
                  ? 'bg-warn/10 text-warn'
                  : 'border border-line-soft bg-surface-2/60 text-ink'
            "
          >
            {{ message.content }}
          </div>
        </div>

        <!-- 追问流式输出 -->
        <div
          v-if="streaming && streamKind === 'interview'"
          class="flex flex-col items-start"
        >
          <div class="mb-1 text-[10px] text-ink-faint">案例整理官 · 输出中…</div>
          <div
            class="max-w-[88%] rounded-2xl border border-line-soft bg-surface-2/60 px-3 py-2 text-[13px] whitespace-pre-wrap text-ink"
          >
            {{ streamText || streamStatus || '正在思考…' }}
          </div>
        </div>

        <!-- 案例文档流式输出 -->
        <div
          v-if="streaming && streamKind === 'case'"
          class="space-y-2 border-t border-line-soft pt-3"
        >
          <div class="flex items-center gap-2 text-xs text-ink-muted">
            <span class="size-2 animate-pulse rounded-full bg-violet" />
            正在生成案例…
          </div>
          <div
            class="max-h-64 overflow-y-auto rounded-xl border border-line-soft bg-canvas/50 p-3 text-[12.5px] whitespace-pre-wrap text-ink"
          >
            {{ streamText }}
          </div>
        </div>

        <div v-if="caseDoc" class="space-y-2 border-t border-line-soft pt-3">
          <div class="flex flex-wrap items-center gap-2">
            <StatusBadge label="已入先前案例库" tone="violet" />
            <StatusBadge
              v-if="caseDoc.index_error"
              label="索引异常"
              tone="danger"
              :dot="false"
            />
            <span class="text-[11px] text-ink-faint">
              {{ caseDoc.index_error || (caseDoc.indexed_at ? '索引正常' : '等待索引') }}
            </span>
            <button class="btn btn-ghost ml-auto px-2 py-1 text-xs" @click="downloadCase">
              <AppIcon name="fileText" :size="13" /> 导出案例
            </button>
          </div>
          <MarkdownView :source="caseDoc.markdown" />
        </div>

        <div
          v-else-if="review.status === 'generated' && !streaming"
          class="py-6 text-center text-xs text-ink-faint"
        >
          案例记录已生成，但文档为空。请点击“直接生成案例”重试。
        </div>

        <div
          v-if="state?.feedback?.length"
          class="space-y-2 border-t border-line-soft pt-3"
        >
          <div class="flex flex-wrap items-center gap-2">
            <h3 class="font-mono text-xs font-semibold text-ink-muted">先例反馈</h3>
            <span class="text-[11px] text-ink-faint">按人工复核意图自动推断，用于更新先例可靠性</span>
          </div>
          <div
            v-for="fb in state.feedback"
            :key="fb.id"
            class="rounded-xl border border-line-soft bg-canvas/40 p-2.5"
          >
            <div class="flex flex-wrap items-center gap-2">
              <StatusBadge
                :label="PRIOR_FEEDBACK_META[fb.signal]?.label ?? fb.signal"
                :tone="PRIOR_FEEDBACK_META[fb.signal]?.tone ?? 'slate'"
                :dot="false"
              />
              <span class="num text-[11px] text-ink-muted">
                置信度 {{ fb.confidence !== null ? fb.confidence.toFixed(2) : '—' }}
              </span>
              <span class="num text-[11px] text-ink-faint">
                可靠性 {{ fb.weight_before.toFixed(2) }} → {{ fb.weight_after.toFixed(2) }}
              </span>
            </div>
            <p class="mt-1 text-[12px] leading-relaxed text-ink-muted">{{ fb.rationale }}</p>
          </div>
        </div>
      </div>

      <div v-if="review.status !== 'generated'" class="border-t border-line-soft p-3">
        <div class="flex items-end gap-2">
          <textarea
            v-model="draft"
            class="input max-h-28 min-h-[44px] flex-1 resize-none py-2"
            rows="2"
            placeholder="回答 Agent 的追问，Enter 发送，Shift+Enter 换行"
            :disabled="streaming"
            @keydown.enter.exact.prevent="send"
          />
          <button
            class="btn btn-primary px-3 py-2"
            :disabled="streaming || !draft.trim()"
            @click="send"
          >
            {{ streaming ? '输出中…' : '回复' }}
          </button>
        </div>
        <div class="mt-2 flex flex-wrap items-center gap-2">
          <span class="text-[11px] text-ink-faint">
            {{ review.generation_error ? `上次生成失败：${review.generation_error}` : 'Agent 认为理解后会自行生成；也可随时强制生成。' }}
          </span>
          <button
            class="btn ml-auto px-2 py-1 text-xs"
            :disabled="streaming"
            @click="forceGenerate"
          >
            <AppIcon name="check" :size="13" />
            {{ streaming ? '生成中…' : '直接生成案例' }}
          </button>
        </div>
      </div>
    </template>
  </section>
</template>
