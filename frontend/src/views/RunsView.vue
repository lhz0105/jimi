<script setup lang="ts">
import { computed, onMounted, onScopeDispose, reactive, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { fetchRuns } from '@/api/admin'
import { errorText } from '@/api/client'
import type { RunBrief } from '@/api/types'
import {
  formatCost,
  formatDateTime,
  formatDuration,
  formatTokens,
} from '@/utils/format'
import {
  ACTIVE_STATUSES,
  REVIEW_STATUS_META,
  RISK_META,
  SCENARIO_LABEL,
  STATUS_META,
} from '@/utils/meta'

const route = useRoute()
const router = useRouter()

const filters = reactive({
  status: String(route.query.status ?? ''),
  scenario: String(route.query.scenario ?? ''),
  review: String(route.query.review ?? ''),
  q: String(route.query.q ?? ''),
  page: Number(route.query.page ?? 1),
  page_size: Number(route.query.page_size ?? 20),
})

const items = ref<RunBrief[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref<string | null>(null)
const autoRefresh = ref(true)

let timer: number | null = null
let debounce: number | null = null

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / filters.page_size)))
const hasActive = computed(() =>
  items.value.some((item) => ACTIVE_STATUSES.includes(item.status)),
)
const activeFilterLabels = computed(() => {
  const labels: string[] = []
  if (filters.status) {
    labels.push(`状态：${STATUS_META[filters.status as keyof typeof STATUS_META]?.label ?? filters.status}`)
  }
  if (filters.scenario) {
    labels.push(`场景：${SCENARIO_LABEL[filters.scenario] ?? filters.scenario}`)
  }
  if (filters.review) {
    labels.push(`人工复核：${filters.review === 'needed' ? '待复核' : '已复核'}`)
  }
  if (filters.q) labels.push(`关键词：${filters.q}`)
  return labels
})

async function load(): Promise<void> {
  loading.value = true
  try {
    const data = await fetchRuns({ ...filters })
    items.value = data.items
    total.value = data.meta.total
    error.value = null
    // 过滤条件同步到 URL（可分享/可回退）
    void router.replace({
      query: Object.fromEntries(
        Object.entries(filters).filter(([, v]) => v !== '' && v !== 1 && v !== 20),
      ),
    })
  } catch (err) {
    error.value = errorText(err)
  } finally {
    loading.value = false
  }
}

watch(
  () => [filters.status, filters.scenario, filters.review, filters.page, filters.page_size],
  () => void load(),
)

watch(
  () => filters.q,
  () => {
    if (debounce !== null) window.clearTimeout(debounce)
    debounce = window.setTimeout(() => {
      filters.page = 1
      void load()
    }, 350)
  },
)

function resetFilters(): void {
  filters.status = ''
  filters.scenario = ''
  filters.review = ''
  filters.q = ''
  filters.page = 1
}

function refreshOnFocus(): void {
  // 后台标签页的定时器会被浏览器节流；切回页面时立即补一次，避免"看起来没同步"
  if (document.visibilityState === 'visible') void load()
}

onMounted(() => {
  void load()
  timer = window.setInterval(() => {
    if (autoRefresh.value) void load()
  }, 6000)
  document.addEventListener('visibilitychange', refreshOnFocus)
  window.addEventListener('focus', refreshOnFocus)
})
onScopeDispose(() => {
  if (timer !== null) window.clearInterval(timer)
  if (debounce !== null) window.clearTimeout(debounce)
  document.removeEventListener('visibilitychange', refreshOnFocus)
  window.removeEventListener('focus', refreshOnFocus)
})
</script>

<template>
  <div class="flex flex-col gap-3">
    <!-- 过滤栏 -->
    <section class="card flex flex-wrap items-end gap-3 p-3">
      <div>
        <label class="mb-1 block text-[11px] text-ink-muted" for="filter-status">状态</label>
        <select id="filter-status" v-model="filters.status" class="input min-w-32">
          <option value="">全部</option>
          <option v-for="(meta, key) in STATUS_META" :key="key" :value="key">{{ meta.label }}</option>
        </select>
      </div>
      <div>
        <label class="mb-1 block text-[11px] text-ink-muted" for="filter-scenario">场景</label>
        <select id="filter-scenario" v-model="filters.scenario" class="input min-w-36">
          <option value="">全部</option>
          <option v-for="(label, key) in SCENARIO_LABEL" :key="key" :value="key">{{ label }}</option>
        </select>
      </div>
      <div>
        <label class="mb-1 block text-[11px] text-ink-muted" for="filter-review">人工复核</label>
        <select id="filter-review" v-model="filters.review" class="input min-w-28">
          <option value="">全部</option>
          <option value="needed">待复核</option>
          <option value="reviewed">已复核</option>
        </select>
      </div>
      <div class="min-w-52 flex-1">
        <label class="mb-1 block text-[11px] text-ink-muted" for="filter-q">关键词（运行 ID / 错误）</label>
        <div class="relative">
          <AppIcon
            name="search"
            :size="14"
            class="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-ink-faint"
          />
          <input id="filter-q" v-model="filters.q" class="input w-full pl-8" placeholder="run_xxx / 错误信息" />
        </div>
      </div>
      <div>
        <label class="mb-1 block text-[11px] text-ink-muted" for="filter-size">每页</label>
        <select id="filter-size" v-model.number="filters.page_size" class="input">
          <option :value="20">20</option>
          <option :value="50">50</option>
          <option :value="100">100</option>
        </select>
      </div>
      <div class="flex items-center gap-2">
        <button class="btn" @click="resetFilters">重置</button>
        <button class="btn" :disabled="loading" @click="load">
          <AppIcon name="refresh" :size="14" /> 刷新
        </button>
        <label class="flex cursor-pointer items-center gap-1.5 text-xs text-ink-muted">
          <input v-model="autoRefresh" type="checkbox" class="accent-[var(--color-info)]" />
          自动刷新
          <span v-if="!autoRefresh" class="text-warn">（已暂停，点刷新同步）</span>
          <span v-else-if="hasActive" class="text-info">（有活动运行）</span>
        </label>
      </div>
    </section>

    <!-- 当前筛选：避免误以为运行记录缺失 -->
    <section
      v-if="activeFilterLabels.length"
      class="card flex flex-wrap items-center gap-2 px-3 py-2 text-xs text-ink-muted"
    >
      <AppIcon name="info" :size="14" class="text-info" />
      <span>当前筛选：</span>
      <StatusBadge
        v-for="label in activeFilterLabels"
        :key="label"
        :label="label"
        tone="info"
        :dot="false"
      />
      <span class="ml-auto num">共 {{ total }} 条</span>
      <button class="btn px-2 py-1 text-xs" @click="resetFilters">清空筛选</button>
    </section>

    <!-- 列表 -->
    <section class="card overflow-hidden">
      <div v-if="error" class="p-4">
        <EmptyState icon="alert" title="加载失败" :hint="error">
          <button class="btn mt-2" @click="load">重试</button>
        </EmptyState>
      </div>

      <EmptyState
        v-else-if="!items.length && !loading"
        icon="runs"
        title="没有匹配的运行"
        hint="调整过滤条件，或先触发一次分析"
      >
        <button class="btn mt-2" @click="resetFilters">清空过滤</button>
      </EmptyState>

      <table v-else class="table">
        <thead>
          <tr>
            <th>运行 ID</th>
            <th>场景</th>
            <th>状态</th>
            <th>风险</th>
            <th>置信度</th>
            <th>Tokens</th>
            <th>成本</th>
            <th>耗时</th>
            <th>创建时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.run_id" class="clickable">
            <td>
              <RouterLink class="num text-info hover:underline" :to="`/runs/${item.run_id}`">
                {{ item.run_id }}
              </RouterLink>
              <div
                v-if="item.external_ref || item.customer_name"
                class="text-[11px] text-ink-faint"
              >
                <span v-if="item.external_ref?.source === 'demo_platform'" class="text-info">演示台</span>
                <span v-else-if="item.external_ref?.source">{{ item.external_ref.source }}</span>
                <span v-if="item.external_ref?.customer_name || item.customer_name">
                  · {{ item.external_ref?.customer_name || item.customer_name }}
                </span>
                <span v-if="item.external_ref?.conversation_id" class="num">
                  · {{ item.external_ref.conversation_id }}
                </span>
              </div>
              <div
                v-if="item.input_summary"
                class="max-w-[220px] truncate text-[11px] text-ink-faint"
                :title="item.input_summary"
              >
                {{ item.input_summary }}
              </div>
              <div
                v-if="item.review_status && item.review_status !== 'none'"
                class="mt-0.5"
              >
                <StatusBadge
                  :label="REVIEW_STATUS_META[item.review_status]?.label ?? item.review_status"
                  :tone="REVIEW_STATUS_META[item.review_status]?.tone ?? 'slate'"
                  :dot="false"
                />
              </div>
            </td>
            <td class="whitespace-nowrap">{{ SCENARIO_LABEL[item.scenario] ?? item.scenario }}</td>
            <td>
              <StatusBadge
                :label="STATUS_META[item.status].label"
                :tone="STATUS_META[item.status].tone"
                :pulse="ACTIVE_STATUSES.includes(item.status)"
              />
            </td>
            <td>
              <StatusBadge
                v-if="item.risk_level"
                :label="RISK_META[item.risk_level].label"
                :tone="RISK_META[item.risk_level].tone"
              />
              <span v-else class="text-ink-faint">—</span>
            </td>
            <td class="num">
              {{ item.confidence !== null ? item.confidence.toFixed(2) : '—' }}
            </td>
            <td class="num">
              {{ formatTokens((item.cost?.prompt_tokens ?? 0) + (item.cost?.completion_tokens ?? 0)) }}
            </td>
            <td class="num">{{ formatCost(item.cost?.est_cost) }}</td>
            <td class="num">{{ formatDuration(item.started_at, item.finished_at) }}</td>
            <td class="num text-ink-muted">{{ formatDateTime(item.created_at) }}</td>
          </tr>
        </tbody>
      </table>

      <!-- 分页 -->
      <footer
        v-if="total > 0"
        class="flex flex-wrap items-center justify-between gap-2 border-t border-line-soft px-3 py-2"
      >
        <span class="num text-xs text-ink-muted">
          共 {{ total }} 条 · 第 {{ filters.page }} / {{ totalPages }} 页
        </span>
        <div class="flex items-center gap-2">
          <button
            class="btn px-2 py-1 text-xs"
            :disabled="filters.page <= 1"
            @click="filters.page -= 1"
          >
            上一页
          </button>
          <button
            class="btn px-2 py-1 text-xs"
            :disabled="filters.page >= totalPages"
            @click="filters.page += 1"
          >
            下一页
          </button>
        </div>
      </footer>
    </section>
  </div>
</template>
