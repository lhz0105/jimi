<script setup lang="ts">
import { computed, nextTick, onScopeDispose, ref, watch } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import EventItem from '@/components/EventItem.vue'
import JsonBlock from '@/components/JsonBlock.vue'
import MarkdownView from '@/components/MarkdownView.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { cancelAnalysis, confirmAnalysis, getAnalysis, getReportJson, getReportMarkdown } from '@/api'
import { errorText } from '@/api/client'
import type { Analysis, CheckResult, ReportJson } from '@/api/types'
import { useEventStream } from '@/composables/useEventStream'
import { useToast } from '@/composables/useToast'
import { downloadText, formatCost } from '@/utils/format'
import {
  ACTIVE_STATUSES,
  CONCLUSION_META,
  EVIDENCE_CATEGORY_LABEL,
  NODE_LABEL,
  RISK_META,
  SCENARIO_LABEL,
  semanticHitText,
  STATUS_META,
  TOOL_LABEL,
} from '@/utils/meta'

const props = defineProps<{
  analysis: Analysis | null
  hint: CheckResult | null
  starting: boolean
}>()

const emit = defineEmits<{
  start: [payload: { decisionId: string; scenario: string | null }]
  updated: [analysis: Analysis]
  changed: []
}>()

const toast = useToast()

const current = ref<Analysis | null>(null)
const reportJson = ref<ReportJson | null>(null)
const reportMarkdown = ref('')
const reportLoading = ref(false)
const reportError = ref<string | null>(null)
const reportView = ref<'md' | 'json'>('md')
const contentTab = ref<'timeline' | 'report' | 'evidence'>('timeline')
const timelineEl = ref<HTMLElement | null>(null)
const autoScroll = ref(true)

const stream = useEventStream({
  analysisId: () => current.value?.id ?? '',
  checkDone: async () => {
    if (!current.value) return true
    try {
      const latest = await getAnalysis(current.value.id)
      sync(latest)
      return !ACTIVE_STATUSES.includes(latest.status)
    } catch {
      return false
    }
  },
})

const isActive = computed(() =>
  current.value ? ACTIVE_STATUSES.includes(current.value.status) : false,
)
const scenarioLabel = computed(
  () => SCENARIO_LABEL[current.value?.scenario ?? ''] ?? current.value?.scenario ?? '分析',
)
const verdict = computed(() => current.value?.verdict ?? null)
const conclusionMeta = computed(() => CONCLUSION_META[verdict.value?.conclusion ?? ''] ?? null)
const riskMeta = computed(() => (current.value?.risk_level ? RISK_META[current.value.risk_level] : null))
const progress = computed(
  () =>
    current.value?.progress ??
    (current.value?.status === 'running' ? { node: '', percent: 0 } : null),
)

function sync(analysis: Analysis): void {
  current.value = analysis
  emit('updated', analysis)
}

watch(
  () => props.analysis?.id,
  (id, oldId) => {
    if (!id) {
      current.value = null
      return
    }
    if (id === oldId) return
    current.value = props.analysis
    reportJson.value = null
    reportMarkdown.value = ''
    reportError.value = null
    contentTab.value = 'timeline'
    void stream.restart()
    if (props.analysis && !ACTIVE_STATUSES.includes(props.analysis.status)) {
      void loadReport()
    }
  },
  { immediate: true },
)

// 轮询状态（SSE 给实时事件，轮询给权威状态）
let pollTimer: number | null = null
function ensurePolling(): void {
  if (pollTimer !== null) return
  pollTimer = window.setInterval(async () => {
    if (!current.value || !ACTIVE_STATUSES.includes(current.value.status)) {
      stopPolling()
      return
    }
    try {
      const latest = await getAnalysis(current.value.id)
      const wasActive = ACTIVE_STATUSES.includes(current.value.status)
      sync(latest)
      if (wasActive && !ACTIVE_STATUSES.includes(latest.status)) {
        emit('changed')
        void loadReport()
      }
    } catch {
      // 轮询失败不打断
    }
  }, 2500)
}
function stopPolling(): void {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}
watch(isActive, (active) => (active ? ensurePolling() : stopPolling()), { immediate: true })
onScopeDispose(stopPolling)

// 时间线自动滚动
watch(
  () => stream.events.value.length,
  async () => {
    if (!autoScroll.value) return
    await nextTick()
    const el = timelineEl.value
    if (el) el.scrollTop = el.scrollHeight
  },
)

async function loadReport(): Promise<void> {
  if (!current.value || reportLoading.value) return
  if (reportJson.value || reportMarkdown.value) return
  reportLoading.value = true
  reportError.value = null
  try {
    const [json, markdown] = await Promise.all([
      getReportJson(current.value.id),
      getReportMarkdown(current.value.id),
    ])
    reportJson.value = json
    reportMarkdown.value = markdown
  } catch (error) {
    reportError.value = errorText(error)
  } finally {
    reportLoading.value = false
  }
}

async function doConfirm(): Promise<void> {
  if (!current.value) return
  try {
    const latest = await confirmAnalysis(current.value.id)
    sync(latest)
    void stream.start()
    toast.success('已确认，开始分析')
  } catch (error) {
    toast.error(errorText(error))
  }
}

async function doCancel(): Promise<void> {
  if (!current.value) return
  try {
    sync(await cancelAnalysis(current.value.id))
    toast.info('已取消分析')
  } catch (error) {
    toast.error(errorText(error))
  }
}

function exportReport(): void {
  if (!reportMarkdown.value || !current.value) return
  downloadText(`report-${current.value.run_id}.md`, reportMarkdown.value)
}

function selectTab(tab: 'timeline' | 'report' | 'evidence'): void {
  contentTab.value = tab
  if (tab === 'report') void loadReport()
}

function onTimelineScroll(): void {
  const el = timelineEl.value
  if (!el) return
  autoScroll.value = el.scrollHeight - el.scrollTop - el.clientHeight < 40
}
</script>

<template>
  <section class="panel flex min-h-0 flex-col overflow-hidden" aria-label="智能分析">
    <header class="flex items-center gap-2 border-b border-line px-3.5 py-3">
      <span class="flex size-7 items-center justify-center rounded-lg bg-primary text-white">
        <AppIcon name="brain" :size="15" />
      </span>
      <div>
        <h2 class="text-sm font-semibold">智能分析</h2>
        <p class="text-[10.5px] text-ink-faint">迹觅·Evidence · 防 AIGC 欺诈</p>
      </div>
      <div class="ml-auto flex items-center gap-1">
        <StatusBadge
          v-if="current"
          :label="STATUS_META[current.status].label"
          :tone="STATUS_META[current.status].tone"
          :pulse="isActive"
        />
        <button
          v-if="current && isActive"
          class="btn btn-ghost px-2 py-1 text-xs"
          title="取消分析"
          @click="doCancel"
        >
          <AppIcon name="stop" :size="13" />
        </button>
      </div>
    </header>

    <div class="min-h-0 flex-1 overflow-y-auto">
      <!-- 触发提示：规则命中，等待人工确认（始终置顶：即使已有历史分析，新诉求也要能立刻看到） -->
      <div v-if="hint?.need_analysis" class="p-4" :class="current ? 'pb-2' : ''">
        <div class="rounded-xl border border-primary/30 bg-primary-weak/60 p-4">
          <div class="flex items-start gap-2.5">
            <span class="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-white">
              <AppIcon name="shield" :size="15" />
            </span>
            <div class="min-w-0 flex-1">
              <p class="text-sm font-semibold text-ink">
                检测到疑似欺诈场景<template v-if="current" class="text-ink-faint"> · 新触发</template>
              </p>
              <p class="mt-0.5 text-xs text-ink-muted">
                {{ SCENARIO_LABEL[hint.scenario ?? ''] ?? hint.scenario }} ·
                {{ hint.reason }}
              </p>
              <div class="mt-2 flex flex-wrap items-center gap-1.5">
                <StatusBadge
                  v-if="hint.risk_hint"
                  :label="`规则风险 ${RISK_META[hint.risk_hint as 'high']?.label ?? hint.risk_hint}`"
                  :tone="RISK_META[hint.risk_hint as 'high']?.tone ?? 'slate'"
                  :dot="false"
                />
                <StatusBadge
                  v-for="rule in hint.matched_rules.slice(0, 3)"
                  :key="rule.id"
                  :label="rule.id"
                  tone="slate"
                  :dot="false"
                />
                <span class="text-[10px] text-ink-faint">
                  窗口 {{ hint.window_size }} 条 · 图片 {{ hint.image_count }} 张
                  <template v-if="hint.semantic_status === 'matched'">
                    · 语义 {{ semanticHitText(hint.semantic_hits, hint.semantic_levels) }}
                  </template>
                </span>
              </div>
              <button
                class="btn btn-primary mt-3 w-full"
                :disabled="starting"
                @click="emit('start', { decisionId: hint.decision_id, scenario: hint.scenario })"
              >
                <AppIcon name="play" :size="14" />
                {{ starting ? '启动中…' : '开始分析' }}
              </button>
            </div>
          </div>
        </div>
        <p class="mt-3 text-center text-[11px] text-ink-faint">
          分析将实时展示 Agent 的思考过程、工具调用与知识库命中
        </p>
      </div>

      <!-- 空状态 -->
      <div v-else-if="!current" class="flex h-full flex-col items-center justify-center gap-2 p-6 text-center">
        <span class="flex size-12 items-center justify-center rounded-2xl bg-primary-weak text-primary">
          <AppIcon name="sparkle" :size="22" />
        </span>
        <p class="text-sm font-medium">等待触发</p>
        <p class="max-w-56 text-[11.5px] leading-relaxed text-ink-faint">
          客户消息命中退款/破损/医疗等诉求后，会在这里提示开始分析；分析过程与报告将实时展示。
        </p>
      </div>

      <!-- 分析详情（与触发卡片可同时存在：新诉求提示 + 历史结果） -->
      <div v-if="current" class="flex flex-col">
        <!-- 概要 -->
        <div class="border-b border-line px-4 py-3">
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-sm font-semibold">{{ scenarioLabel }}</span>
            <StatusBadge
              v-if="riskMeta"
              :label="riskMeta.label"
              :tone="riskMeta.tone"
            />
            <span v-if="current.confidence !== null" class="num text-[11px] text-ink-muted">
              置信度 {{ current.confidence?.toFixed(2) }}
            </span>
            <button
              v-if="current.status === 'succeeded'"
              class="btn btn-ghost ml-auto px-2 py-1 text-[11px]"
              @click="exportReport"
            >
              <AppIcon name="fileText" :size="12" /> 导出报告
            </button>
          </div>
          <p v-if="current.status === 'awaiting_confirm'" class="mt-2 text-xs text-ink-muted">
            分析已就绪，等待确认后开始。
            <button class="btn btn-primary ml-2 px-2.5 py-1 text-xs" @click="doConfirm">
              确认开始
            </button>
          </p>
          <div v-if="isActive && progress" class="mt-2">
            <div class="flex items-center justify-between text-[10.5px] text-ink-muted">
              <span>{{ NODE_LABEL[progress.node ?? ''] ?? progress.node ?? '准备中' }}</span>
              <span class="num">{{ progress.percent ?? 0 }}%</span>
            </div>
            <div class="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-2">
              <div
                class="h-full rounded-full bg-primary transition-[width] duration-500"
                :style="{ width: `${progress.percent ?? 0}%` }"
              />
            </div>
          </div>
          <p
            v-if="current.last_error"
            class="mt-2 rounded-lg border border-red-200 bg-red-50 px-2 py-1 text-[11px] text-danger"
          >
            {{ current.last_error }}
          </p>
        </div>

        <!-- 页签 -->
        <div class="flex gap-1 border-b border-line px-3 py-1.5">
          <button
            v-for="tab in [
              { id: 'timeline', label: `过程 ${stream.events.value.length || ''}`, icon: 'zap' },
              { id: 'report', label: '报告', icon: 'fileText' },
              { id: 'evidence', label: '证据链', icon: 'scale' },
            ]"
            :key="tab.id"
            class="btn px-2 py-1 text-[11px]"
            :class="contentTab === tab.id ? 'btn-primary' : 'btn-ghost'"
            @click="selectTab(tab.id as 'timeline' | 'report' | 'evidence')"
          >
            <AppIcon :name="tab.icon as never" :size="12" />
            {{ tab.label }}
          </button>
          <span v-if="stream.error.value" class="ml-auto self-center text-[10px] text-danger">
            {{ stream.error.value }}
          </span>
        </div>

        <!-- 过程 -->
        <div
          v-if="contentTab === 'timeline'"
          ref="timelineEl"
          class="max-h-[46vh] min-h-40 overflow-y-auto"
          @scroll.passive="onTimelineScroll"
        >
          <p v-if="!stream.events.value.length" class="p-4 text-center text-xs text-ink-faint">
            {{ isActive ? '等待 Agent 输出…' : '暂无过程事件' }}
          </p>
          <ul v-else class="divide-y divide-line/60">
            <EventItem v-for="event in stream.events.value.slice(-200)" :key="event.seq" :event="event" />
          </ul>
        </div>

        <!-- 报告 -->
        <div v-else-if="contentTab === 'report'" class="p-3">
          <div class="mb-2 flex items-center gap-1">
            <button
              class="btn px-2 py-1 text-[11px]"
              :class="reportView === 'md' ? 'btn-primary' : 'btn-ghost'"
              @click="reportView = 'md'"
            >
              Markdown
            </button>
            <button
              class="btn px-2 py-1 text-[11px]"
              :class="reportView === 'json' ? 'btn-primary' : 'btn-ghost'"
              @click="reportView = 'json'"
            >
              JSON
            </button>
            <button class="btn btn-ghost ml-auto px-2 py-1 text-[11px]" @click="loadReport">
              <AppIcon name="refresh" :size="12" /> 获取
            </button>
          </div>
          <p v-if="reportLoading" class="py-6 text-center text-xs text-ink-faint">报告加载中…</p>
          <p v-else-if="reportError" class="py-6 text-center text-xs text-ink-faint">{{ reportError }}</p>
          <MarkdownView v-else-if="reportMarkdown && reportView === 'md'" :source="reportMarkdown" />
          <JsonBlock v-else-if="reportJson && reportView === 'json'" :value="reportJson" title="报告 JSON" />
          <p v-else class="py-6 text-center text-xs text-ink-faint">
            {{ isActive ? '分析完成后生成报告' : '暂无报告' }}
          </p>
        </div>

        <!-- 证据链 -->
        <div v-else class="p-3">
          <p v-if="!reportJson?.evidence_chain?.length" class="py-6 text-center text-xs text-ink-faint">
            报告生成后可在此查看证据链
          </p>
          <ul v-else class="space-y-2">
            <li
              v-for="item in reportJson.evidence_chain"
              :key="item.evidence_id"
              class="rounded-xl border border-line p-2.5"
              :class="item.direction === 'supports_fake' ? 'border-red-200 bg-red-50/50' : 'bg-canvas/60'"
            >
              <div class="flex flex-wrap items-center gap-2 text-[11px]">
                <span class="num text-ink-faint">{{ item.evidence_id }}</span>
                <span class="text-ink-muted">{{ EVIDENCE_CATEGORY_LABEL[item.category] ?? item.category }}</span>
                <span class="num text-ink-muted">权重 {{ item.weight }}</span>
                <span class="text-ink-faint">via {{ TOOL_LABEL[item.tool] ?? item.tool }}</span>
              </div>
              <p class="mt-1 text-[12.5px] leading-relaxed">{{ item.finding }}</p>
            </li>
          </ul>
        </div>

        <!-- 结论摘要 -->
        <div v-if="verdict || conclusionMeta" class="border-t border-line px-4 py-3">
          <div class="flex flex-wrap items-center gap-2">
            <StatusBadge
              v-if="conclusionMeta"
              :label="conclusionMeta.label"
              :tone="conclusionMeta.tone"
            />
            <span v-if="current.cost" class="num ml-auto text-[10px] text-ink-faint">
              {{ current.cost.llm_calls ?? 0 }} 次调用 · {{ formatCost(current.cost.est_cost) }}
            </span>
          </div>
          <p v-if="verdict?.summary" class="mt-1.5 text-[12.5px] leading-relaxed text-ink">
            {{ verdict.summary }}
          </p>
          <ul
            v-if="verdict?.recommended_actions?.length"
            class="mt-1.5 space-y-0.5 text-[11.5px] text-ink-muted"
          >
            <li
              v-for="action in verdict.recommended_actions"
              :key="action.action"
              class="flex items-start gap-1"
            >
              <AppIcon name="chevronRight" :size="11" class="mt-0.5 shrink-0 text-primary" />
              <span>{{ action.action }}<template v-if="action.note"> — {{ action.note }}</template></span>
            </li>
          </ul>
        </div>
      </div>
    </div>
  </section>
</template>
