<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import CopyButton from '@/components/CopyButton.vue'
import EmptyState from '@/components/EmptyState.vue'
import EventStreamPanel from '@/components/EventStreamPanel.vue'
import JsonBlock from '@/components/JsonBlock.vue'
import MarkdownView from '@/components/MarkdownView.vue'
import MetricCard from '@/components/MetricCard.vue'
import Modal from '@/components/Modal.vue'
import ReviewPanel from '@/components/ReviewPanel.vue'
import RuleDecisionView from '@/components/RuleDecisionView.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import {
  cancelRun,
  fetchReportJson,
  fetchReportMarkdown,
  fetchRunConversation,
  fetchRunDetail,
  fetchRunEvents,
} from '@/api/admin'
import { errorText } from '@/api/client'
import type { ReportJson, RunConversation, RunDetail, RunEvent } from '@/api/types'
import { useEventStream } from '@/composables/useEventStream'
import { useToast } from '@/composables/useToast'
import {
  downloadText,
  formatCost,
  formatDateTime,
  formatDuration,
  formatLatency,
  formatTokens,
} from '@/utils/format'
import {
  ACTIVE_STATUSES,
  CONCLUSION_META,
  DIRECTION_META,
  EVIDENCE_CATEGORY_LABEL,
  NODE_LABEL,
  RISK_META,
  SCENARIO_LABEL,
  STATUS_META,
  TOOL_LABEL,
} from '@/utils/meta'

const route = useRoute()
const router = useRouter()
const toast = useToast()

const runId = computed(() => String(route.params.id ?? ''))
const detail = ref<RunDetail | null>(null)
const loadError = ref<string | null>(null)
const loading = ref(false)

type DetailTab = 'stream' | 'report' | 'tools' | 'review' | 'raw'
const activeTab = ref<DetailTab>('stream')
const conversation = ref<RunConversation | null>(null)
const conversationLoading = ref(false)
const conversationError = ref<string | null>(null)
const reportJson = ref<ReportJson | null>(null)
const reportMarkdown = ref('')
const reportLoading = ref(false)
const reportError = ref<string | null>(null)
const reportView = ref<'md' | 'json'>('md')
const rawEvents = ref<RunEvent[]>([])
const rawLoading = ref(false)
const cancelOpen = ref(false)
const cancelling = ref(false)

const stream = useEventStream({
  runId: () => runId.value,
  checkDone: async () => {
    const run = await fetchRunDetail(runId.value).catch(() => null)
    return run ? !ACTIVE_STATUSES.includes(run.run.status) : false
  },
})

const run = computed(() => detail.value?.run ?? null)
const isActive = computed(() => (run.value ? ACTIVE_STATUSES.includes(run.value.status) : false))
const reviewEligible = computed(() => {
  const record = run.value
  if (!record) return false
  if (record.review_required) return true
  const verdict = record.verdict
  if (!verdict) return false
  if (verdict.conclusion === 'suspicious' || verdict.conclusion === 'fake_claim') return true
  return (verdict.recommended_actions ?? []).some((action) => action.action === 'manual_review')
})
const tabs = computed<Array<{ id: DetailTab; label: string; icon: string }>>(() => [
  { id: 'stream', label: '事件流', icon: 'zap' },
  { id: 'report', label: '报告', icon: 'fileText' },
  { id: 'tools', label: '工具调用', icon: 'tool' },
  ...(reviewEligible.value
    ? [{ id: 'review' as DetailTab, label: '人工判决', icon: 'scale' }]
    : []),
  { id: 'raw', label: '原始事件', icon: 'database' },
])
const progress = computed(() => {
  const p = run.value?.progress_json
  if (!p || p.percent === undefined) return null
  return { node: p.node ? (NODE_LABEL[p.node] ?? p.node) : '', percent: p.percent }
})
const verdict = computed(() => reportJson.value?.summary ?? run.value?.verdict ?? null)
const conclusionKey = computed<string | null>(() => {
  const v = verdict.value as { conclusion?: string } | null
  return v?.conclusion ?? null
})
const conclusionMeta = computed(() =>
  conclusionKey.value ? (CONCLUSION_META[conclusionKey.value] ?? null) : null,
)

async function loadDetail(): Promise<void> {
  loading.value = true
  try {
    detail.value = await fetchRunDetail(runId.value)
    loadError.value = null
  } catch (error) {
    loadError.value = errorText(error)
  } finally {
    loading.value = false
  }
}

async function loadReport(force = false): Promise<void> {
  if (reportLoading.value) return
  if (!force && (reportJson.value || reportMarkdown.value)) return
  reportLoading.value = true
  reportError.value = null
  try {
    const [json, markdown] = await Promise.all([
      fetchReportJson(runId.value),
      fetchReportMarkdown(runId.value),
    ])
    reportJson.value = json
    reportMarkdown.value = markdown
  } catch (error) {
    reportError.value = errorText(error)
  } finally {
    reportLoading.value = false
  }
}

async function loadConversation(force = false): Promise<void> {
  if (conversationLoading.value) return
  if (!force && conversation.value) return
  conversationLoading.value = true
  conversationError.value = null
  try {
    conversation.value = await fetchRunConversation(runId.value)
  } catch (error) {
    conversationError.value = errorText(error)
  } finally {
    conversationLoading.value = false
  }
}

async function loadRawEvents(): Promise<void> {
  if (rawLoading.value) return
  rawLoading.value = true
  try {
    const page = await fetchRunEvents(runId.value, 0, 1000)
    rawEvents.value = page.items
  } catch (error) {
    toast.error(errorText(error))
  } finally {
    rawLoading.value = false
  }
}

watch(activeTab, (tab) => {
  if (tab === 'report') void loadReport()
  if (tab === 'raw') void loadRawEvents()
})

watch(runId, () => {
  detail.value = null
  conversation.value = null
  conversationError.value = null
  reportJson.value = null
  reportMarkdown.value = ''
  rawEvents.value = []
  void loadDetail()
  void loadConversation()
  void stream.restart()
})

onMounted(async () => {
  await loadDetail()
  void loadConversation()
  stream.start()
  if (run.value && !isActive.value) void loadReport()
})

// 运行结束：刷新详情并加载报告
watch(
  () => stream.events.value.at(-1)?.type,
  (type) => {
    if (type === 'run_end') {
      void loadDetail()
      void loadReport(true)
    }
  },
)

async function doCancel(): Promise<void> {
  cancelling.value = true
  try {
    const result = await cancelRun(runId.value)
    toast.success(`已请求取消（${result.status}）`)
    cancelOpen.value = false
    await loadDetail()
  } catch (error) {
    toast.error(errorText(error))
  } finally {
    cancelling.value = false
  }
}

function exportReport(): void {
  if (reportMarkdown.value) {
    downloadText(`report-${runId.value}.md`, reportMarkdown.value)
  }
}

function exportEvents(): void {
  const text = JSON.stringify(stream.events.value, null, 2)
  downloadText(`events-${runId.value}.json`, text, 'application/json')
}

const costByNode = computed(() => {
  const cost = reportJson.value?.cost?.by_node ?? run.value?.cost_json?.by_node ?? {}
  return Object.entries(cost).sort((a, b) => b[1].cost - a[1].cost)
})
</script>

<template>
  <div v-if="loadError" class="card p-6">
    <EmptyState icon="alert" title="运行加载失败" :hint="loadError">
      <RouterLink class="btn mt-2" to="/runs">返回运行列表</RouterLink>
    </EmptyState>
  </div>

  <div v-else-if="!run" class="card p-6">
    <EmptyState icon="clock" title="加载中…" hint="正在获取运行详情" />
  </div>

  <div v-else class="flex flex-col gap-3">
    <!-- 运行头：状态 / 结论 / 动作 -->
    <section class="card p-3">
      <div class="flex flex-wrap items-center gap-2">
        <button class="btn btn-ghost px-1.5 py-1" title="返回运行列表" @click="router.push('/runs')">
          <AppIcon name="arrowLeft" :size="15" />
        </button>
        <span class="num text-sm font-semibold">{{ run.id }}</span>
        <CopyButton :text="run.id" label="复制 ID" />
        <StatusBadge
          :label="STATUS_META[run.status].label"
          :tone="STATUS_META[run.status].tone"
          :pulse="isActive"
        />
        <StatusBadge
          :label="SCENARIO_LABEL[run.scenario] ?? run.scenario"
          tone="info"
          :dot="false"
        />
        <StatusBadge
          v-if="run.risk_level"
          :label="`风险 ${RISK_META[run.risk_level].label}`"
          :tone="RISK_META[run.risk_level].tone"
        />
        <span v-if="conclusionKey" class="text-xs">
          <StatusBadge
            :label="conclusionMeta?.label ?? conclusionKey"
            :tone="conclusionMeta?.tone ?? 'slate'"
          />
        </span>

        <div class="ml-auto flex items-center gap-2">
          <button class="btn px-2 py-1 text-xs" :disabled="loading" @click="loadDetail">
            <AppIcon name="refresh" :size="13" /> 刷新
          </button>
          <button
            v-if="reportMarkdown"
            class="btn px-2 py-1 text-xs"
            @click="exportReport"
          >
            <AppIcon name="fileText" :size="13" /> 导出报告
          </button>
          <button
            v-if="isActive"
            class="btn btn-danger px-2 py-1 text-xs"
            @click="cancelOpen = true"
          >
            <AppIcon name="stop" :size="13" /> 取消运行
          </button>
        </div>
      </div>

      <div class="num mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-muted">
        <span>触发：{{ run.trigger_mode === 'auto' ? '自动链' : '手动链' }}</span>
        <span>创建：{{ formatDateTime(run.created_at) }}</span>
        <span>耗时：{{ formatDuration(run.started_at, run.finished_at) }}</span>
        <span v-if="run.conversation_id">会话：{{ run.conversation_id }}</span>
        <span v-if="run.external_ref">
          来源：{{ run.external_ref.source === 'demo_platform' ? '演示台' : (run.external_ref.source || '外部') }}
          <template v-if="run.external_ref.customer_name"> · {{ run.external_ref.customer_name }}</template>
          <template v-if="run.external_ref.conversation_id"> · {{ run.external_ref.conversation_id }}</template>
        </span>
        <span>成本：{{ formatCost(run.cost_json.est_cost) }} · {{ run.cost_json.llm_calls ?? 0 }} 次调用</span>
      </div>

      <div v-if="isActive && progress" class="mt-2">
        <div class="flex items-center justify-between text-[11px] text-ink-muted">
          <span>当前节点：{{ progress.node || '—' }}</span>
          <span class="num">{{ progress.percent }}%</span>
        </div>
        <div class="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-2">
          <div
            class="h-full rounded-full bg-info transition-[width] duration-500"
            :style="{ width: `${progress.percent}%` }"
          />
        </div>
      </div>

      <p
        v-if="run.error"
        class="mt-2 rounded border border-danger/40 bg-danger/10 px-2 py-1.5 text-xs text-danger"
      >
        运行错误：{{ run.error }}
      </p>
    </section>

    <div class="grid gap-3 xl:grid-cols-[minmax(0,1fr)_340px]">
      <!-- 主列：常驻对话记录 + 页签 -->
      <div class="flex min-h-[62vh] flex-col gap-2">
        <!-- 对话记录：常驻，不随页签切换而改变 -->
        <section class="card flex max-h-[32vh] min-h-[150px] flex-col overflow-hidden">
          <header class="flex flex-wrap items-center gap-2 border-b border-line-soft px-3 py-2">
            <AppIcon name="chat" :size="14" class="text-teal" />
            <h2 class="font-mono text-xs font-semibold text-ink-muted">对话记录</h2>
            <span class="num text-[11px] text-ink-faint">
              共 {{ conversation?.message_count ?? 0 }} 条 · 图片 {{ conversation?.image_count ?? 0 }} 张
            </span>
            <span v-if="conversation" class="text-[11px] text-ink-faint">
              {{ conversation.note }}
            </span>
            <button
              class="btn btn-ghost ml-auto px-2 py-1 text-xs"
              :disabled="conversationLoading"
              @click="loadConversation(true)"
            >
              <AppIcon name="refresh" :size="13" /> 刷新
            </button>
          </header>
          <div class="min-h-0 flex-1 overflow-y-auto p-3">
            <p v-if="conversationLoading" class="text-xs text-ink-muted">加载中…</p>
            <p v-else-if="conversationError" class="py-2 text-xs text-danger">
              {{ conversationError }}
            </p>
            <p
              v-else-if="!conversation?.messages.length"
              class="py-4 text-center text-xs text-ink-faint"
            >
              暂无对话记录
            </p>
            <div v-else class="space-y-2.5">
              <div
                v-for="message in conversation.messages"
                :key="`${message.seq}-${message.ts ?? 0}`"
                class="flex flex-col"
                :class="
                  message.role === 'agent'
                    ? 'items-end'
                    : message.role === 'system'
                      ? 'items-center'
                      : 'items-start'
                "
              >
                <div class="mb-0.5 text-[10px] text-ink-faint">
                  {{ message.role === 'customer' ? '客户' : message.role === 'agent' ? '客服' : '系统' }}
                  <span v-if="message.ts" class="num"> · {{ formatDateTime(message.ts) }}</span>
                </div>
                <div
                  class="max-w-[82%] rounded-2xl px-3 py-1.5 text-[12.5px] whitespace-pre-wrap"
                  :class="
                    message.role === 'agent'
                      ? 'bg-accent/10 text-ink'
                      : message.role === 'system'
                        ? 'bg-surface-2/60 text-ink-muted'
                        : 'border border-line-soft bg-surface-2/60 text-ink'
                  "
                >
                  {{ message.content }}
                </div>
              </div>
            </div>
          </div>
        </section>

        <div class="flex flex-wrap items-center gap-1" role="tablist" aria-label="运行详情视图">
          <button
            v-for="tab in tabs"
            :key="tab.id"
            role="tab"
            :aria-selected="activeTab === tab.id"
            class="btn px-2.5 py-1 text-xs"
            :class="activeTab === tab.id ? 'btn-primary' : 'btn-ghost'"
            @click="activeTab = tab.id"
          >
            <AppIcon :name="tab.icon as never" :size="13" /> {{ tab.label }}
            <span v-if="tab.id === 'tools'" class="num text-[11px] opacity-70">
              {{ detail?.tool_calls.length ?? 0 }}
            </span>
          </button>
          <button class="btn btn-ghost ml-auto px-2 py-1 text-xs" @click="exportEvents">
            <AppIcon name="copy" :size="13" /> 导出事件流 JSON
          </button>
        </div>

        <!-- 事件流 -->
        <EventStreamPanel
          v-if="activeTab === 'stream'"
          :events="stream.events.value"
          :state="stream.state.value"
          :error="stream.error.value"
          class="min-h-[56vh]"
          @pause="stream.stop()"
          @resume="stream.start()"
          @restart="stream.restart()"
        />

        <!-- 报告 -->
        <section v-else-if="activeTab === 'report'" class="card flex min-h-[56vh] flex-col">
          <header class="flex items-center gap-2 border-b border-line-soft px-3 py-2">
            <div class="flex items-center gap-1">
              <button
                class="btn px-2 py-1 text-xs"
                :class="reportView === 'md' ? 'btn-primary' : 'btn-ghost'"
                @click="reportView = 'md'"
              >
                Markdown
              </button>
              <button
                class="btn px-2 py-1 text-xs"
                :class="reportView === 'json' ? 'btn-primary' : 'btn-ghost'"
                @click="reportView = 'json'"
              >
                JSON
              </button>
            </div>
            <button class="btn btn-ghost ml-auto px-2 py-1 text-xs" @click="loadReport(true)">
              <AppIcon name="refresh" :size="13" /> 重新获取
            </button>
          </header>
          <div class="min-h-0 flex-1 overflow-y-auto p-4">
            <p v-if="reportLoading" class="text-sm text-ink-muted">报告加载中…</p>
            <EmptyState
              v-else-if="reportError"
              icon="alert"
              title="报告暂不可用"
              :hint="reportError"
            />
            <MarkdownView v-else-if="reportMarkdown && reportView === 'md'" :source="reportMarkdown" />
            <JsonBlock v-else-if="reportJson && reportView === 'json'" :value="reportJson" title="报告 JSON" />
            <EmptyState v-else icon="fileText" title="暂无报告" hint="运行完成后自动生成" />
          </div>
        </section>

        <!-- 工具调用 -->
        <section v-else-if="activeTab === 'tools'" class="card min-h-[56vh] overflow-hidden">
          <EmptyState
            v-if="!detail?.tool_calls.length"
            icon="tool"
            title="本次运行未调用工具"
            hint="investigate 节点会按需调用识图/知识库/联网等工具"
          />
          <div v-else class="max-h-[60vh] overflow-y-auto">
            <table class="table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>工具</th>
                  <th>状态</th>
                  <th>耗时</th>
                  <th>参数 / 结果</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="call in detail.tool_calls" :key="call.id">
                  <td class="num text-ink-faint">{{ call.seq }}</td>
                  <td>{{ TOOL_LABEL[call.tool] ?? call.tool }}</td>
                  <td>
                    <StatusBadge
                      :label="call.status === 'ok' ? '成功' : '失败'"
                      :tone="call.status === 'ok' ? 'accent' : 'danger'"
                    />
                  </td>
                  <td class="num">{{ formatLatency(call.latency_ms) }}</td>
                  <td class="w-full">
                    <JsonBlock :value="{ args: call.args, result: call.result }" :collapsed-lines="6" />
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <!-- 人工判决 -->
        <ReviewPanel
          v-else-if="activeTab === 'review'"
          :run-id="runId"
          :eligible="reviewEligible"
          class="min-h-[56vh]"
        />

        <!-- 原始事件 -->
        <section v-else-if="activeTab === 'raw'" class="card min-h-[56vh]">
          <header class="flex items-center gap-2 border-b border-line-soft px-3 py-2">
            <span class="num text-xs text-ink-muted">共 {{ rawEvents.length }} 条（最多 1000）</span>
            <button class="btn btn-ghost ml-auto px-2 py-1 text-xs" @click="loadRawEvents">
              <AppIcon name="refresh" :size="13" /> 刷新
            </button>
          </header>
          <div class="max-h-[60vh] overflow-y-auto p-3">
            <p v-if="rawLoading" class="text-sm text-ink-muted">加载中…</p>
            <div v-else class="space-y-2">
              <JsonBlock
                v-for="event in rawEvents"
                :key="event.seq"
                :value="event"
                :title="`#${event.seq} · ${event.type}`"
                :collapsed-lines="8"
              />
            </div>
          </div>
        </section>
      </div>

      <!-- 右列：结论 / 成本 / 规则 / 输入 -->
      <div class="flex flex-col gap-3">
        <section class="card p-3">
          <h2 class="mb-2 font-mono text-xs font-semibold text-ink-muted">结论</h2>
          <div v-if="verdict" class="space-y-2">
            <div class="flex flex-wrap items-center gap-2">
              <StatusBadge
                :label="CONCLUSION_META[verdict.conclusion ?? '']?.label ?? String(verdict.conclusion ?? '—')"
                :tone="CONCLUSION_META[verdict.conclusion ?? '']?.tone ?? 'slate'"
              />
              <span class="num text-xs text-ink-muted">
                置信度 {{ Number(verdict.confidence ?? 0).toFixed(2) }}
              </span>
            </div>
            <p class="text-[13px] leading-relaxed text-ink">
              {{ ('one_line' in verdict ? verdict.one_line : verdict.summary) || '（无摘要）' }}
            </p>
            <ul
              v-if="reportJson?.recommended_actions?.length"
              class="space-y-1 text-xs text-ink-muted"
            >
              <li
                v-for="action in reportJson.recommended_actions"
                :key="action.action"
                class="flex items-start gap-1.5"
              >
                <AppIcon name="chevronRight" :size="12" class="mt-0.5 text-ink-faint" />
                <span>
                  <span class="text-ink">{{ action.action }}</span>
                  <span v-if="action.note"> — {{ action.note }}</span>
                </span>
              </li>
            </ul>
            <ul
              v-if="reportJson?.key_counterpoints?.length"
              class="space-y-1 text-xs text-ink-faint"
            >
              <li v-for="point in reportJson.key_counterpoints" :key="point">对立证据：{{ point }}</li>
            </ul>
          </div>
          <p v-else class="text-xs text-ink-faint">尚无结论（运行未完成或报告未生成）</p>
        </section>

        <section class="grid grid-cols-2 gap-2">
          <MetricCard
            label="LLM 调用"
            :value="run.cost_json.llm_calls ?? 0"
            :sub="`识图 ${run.cost_json.vision_calls ?? 0} 次`"
            icon="zap"
            tone="violet"
          />
          <MetricCard
            label="Tokens"
            :value="formatTokens((run.cost_json.prompt_tokens ?? 0) + (run.cost_json.completion_tokens ?? 0))"
            :sub="`入 ${formatTokens(run.cost_json.prompt_tokens)} / 出 ${formatTokens(run.cost_json.completion_tokens)}`"
            icon="database"
            tone="info"
          />
          <MetricCard
            label="工具调用"
            :value="run.cost_json.tool_calls ?? 0"
            :sub="`联网 ${run.cost_json.tavily_calls ?? 0} 次`"
            icon="tool"
            tone="teal"
          />
          <MetricCard
            label="估算成本"
            :value="formatCost(run.cost_json.est_cost)"
            sub="按价格表折算"
            icon="scale"
            tone="warn"
          />
        </section>

        <section v-if="costByNode.length" class="card p-3">
          <h2 class="mb-2 font-mono text-xs font-semibold text-ink-muted">按节点成本</h2>
          <ul class="space-y-1.5 text-xs">
            <li v-for="[node, value] in costByNode" :key="node" class="flex items-center gap-2">
              <span class="w-24 shrink-0 truncate text-ink-muted">{{ NODE_LABEL[node] ?? node }}</span>
              <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2">
                <div
                  class="h-full rounded-full bg-violet/70"
                  :style="{
                    width: `${Math.max(3, Math.round((value.cost / Math.max(0.000001, costByNode[0][1].cost)) * 100))}%`,
                  }"
                />
              </div>
              <span class="num w-24 shrink-0 text-right text-ink-faint">
                {{ formatTokens(value.prompt_tokens + value.completion_tokens) }} tok · {{ formatCost(value.cost) }}
              </span>
            </li>
          </ul>
        </section>

        <section class="card p-3">
          <h2 class="mb-2 font-mono text-xs font-semibold text-ink-muted">规则决策</h2>
          <RuleDecisionView
            v-if="detail?.rules_decision"
            :decision="detail.rules_decision"
            class="mt-0"
          />
          <h2 class="mt-3 mb-2 font-mono text-xs font-semibold text-ink-muted">输入摘要</h2>
          <JsonBlock :value="detail?.input_snapshot ?? {}" :collapsed-lines="8" />
          <h2 v-if="detail?.confirmations.length" class="mt-3 mb-2 font-mono text-xs font-semibold text-ink-muted">
            确认记录
          </h2>
          <ul v-if="detail?.confirmations.length" class="space-y-1 text-xs text-ink-muted">
            <li v-for="conf in detail.confirmations" :key="conf.id" class="num">
              {{ conf.decision === 'confirm' ? '已确认' : '已取消' }} · {{ conf.decided_by }} ·
              {{ formatDateTime(conf.created_at) }}
            </li>
          </ul>
        </section>

        <section v-if="reportJson?.evidence_chain?.length" class="card p-3">
          <h2 class="mb-2 font-mono text-xs font-semibold text-ink-muted">
            证据链（{{ reportJson.evidence_chain.length }}）
          </h2>
          <ul class="space-y-2">
            <li
              v-for="item in reportJson.evidence_chain"
              :key="item.evidence_id"
              class="rounded border border-line-soft p-2"
              :class="DIRECTION_META[item.direction]?.tone === 'danger' ? 'bg-danger/5' : 'bg-canvas/40'"
            >
              <div class="flex flex-wrap items-center gap-2">
                <span class="num text-[11px] text-ink-faint">{{ item.evidence_id }}</span>
                <span class="text-[11px] text-ink-muted">
                  {{ EVIDENCE_CATEGORY_LABEL[item.category] ?? item.category }}
                </span>
                <StatusBadge
                  :label="DIRECTION_META[item.direction]?.label ?? item.direction"
                  :tone="DIRECTION_META[item.direction]?.tone ?? 'slate'"
                />
              </div>
              <p class="mt-1 text-[12px] text-ink">{{ item.finding }}</p>
            </li>
          </ul>
        </section>
      </div>
    </div>

    <Modal :open="cancelOpen" title="取消运行" @close="cancelOpen = false">
      <p class="text-sm text-ink">
        确认取消运行 <span class="num">{{ run.id }}</span>？
      </p>
      <p class="mt-1 text-xs text-ink-muted">
        运行中的任务会在下一个节点边界停止，已产生的证据与事件会保留。
      </p>
      <template #footer>
        <button class="btn" @click="cancelOpen = false">返回</button>
        <button class="btn btn-danger" :disabled="cancelling" @click="doCancel">
          {{ cancelling ? '取消中…' : '确认取消' }}
        </button>
      </template>
    </Modal>
  </div>
</template>
