<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, onScopeDispose, ref } from 'vue'
import { RouterLink } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import MetricCard from '@/components/MetricCard.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { fetchRuns, fetchStats } from '@/api/admin'
import { errorText } from '@/api/client'
import type { RunBrief, StatsResponse } from '@/api/types'
import { useHealth } from '@/composables/useHealth'
import {
  formatCost,
  formatNumber,
  formatRelative,
  formatTokens,
} from '@/utils/format'
import { RISK_META, SCENARIO_LABEL, STATUS_META } from '@/utils/meta'

const { health } = useHealth()

// 图表库按需加载：首屏指标不受 echarts 体积影响
const EChart = defineAsyncComponent(() => import('@/components/EChart.vue'))

const stats = ref<StatsResponse | null>(null)
const recent = ref<RunBrief[]>([])
const error = ref<string | null>(null)
const loading = ref(true)

async function load(): Promise<void> {
  loading.value = true
  try {
    const [statsData, runsData] = await Promise.all([
      fetchStats(7),
      fetchRuns({ page: 1, page_size: 8 }),
    ])
    stats.value = statsData
    recent.value = runsData.items
    error.value = null
  } catch (err) {
    error.value = errorText(err)
  } finally {
    loading.value = false
  }
}

let timer: number | null = null
function refreshOnFocus(): void {
  if (document.visibilityState === 'visible') void load()
}
onMounted(() => {
  void load()
  timer = window.setInterval(() => void load(), 20000)
  document.addEventListener('visibilitychange', refreshOnFocus)
  window.addEventListener('focus', refreshOnFocus)
})
onScopeDispose(() => {
  if (timer !== null) window.clearInterval(timer)
  document.removeEventListener('visibilitychange', refreshOnFocus)
  window.removeEventListener('focus', refreshOnFocus)
})

const successRate = computed(() => {
  const t = stats.value?.totals
  if (!t || !t.runs) return 0
  return t.succeeded / t.runs
})

const axisColor = '#94a3b8'
const gridColor = '#2e3a52'

const trendOption = computed(() => {
  const byDay = stats.value?.by_day ?? {}
  const days = Object.keys(byDay)
  return {
    grid: { left: 8, right: 8, top: 28, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1b2336',
      borderColor: '#475569',
      textStyle: { color: '#f8fafc', fontSize: 12 },
    },
    legend: { textStyle: { color: axisColor, fontSize: 11 }, top: 0, left: 0 },
    xAxis: {
      type: 'category',
      data: days,
      axisLine: { lineStyle: { color: gridColor } },
      axisLabel: { color: axisColor, fontSize: 11 },
    },
    yAxis: [
      {
        type: 'value',
        splitLine: { lineStyle: { color: gridColor, type: 'dashed' } },
        axisLabel: { color: axisColor, fontSize: 11 },
      },
      {
        type: 'value',
        splitLine: { show: false },
        axisLabel: { color: axisColor, fontSize: 11 },
      },
    ],
    series: [
      {
        name: '运行数',
        type: 'bar',
        data: days.map((d) => byDay[d].runs),
        itemStyle: { color: '#38bdf8', borderRadius: [3, 3, 0, 0] },
        barMaxWidth: 28,
      },
      {
        name: '估算成本',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        symbolSize: 6,
        data: days.map((d) => Number(byDay[d].est_cost.toFixed(4))),
        itemStyle: { color: '#22c55e' },
        lineStyle: { color: '#22c55e' },
      },
    ],
  }
})

const scenarioOption = computed(() => {
  const byScenario = stats.value?.by_scenario ?? {}
  const entries = Object.entries(byScenario).sort((a, b) => a[1] - b[1])
  return {
    grid: { left: 8, right: 24, top: 8, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1b2336',
      borderColor: '#475569',
      textStyle: { color: '#f8fafc', fontSize: 12 },
    },
    xAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: gridColor, type: 'dashed' } },
      axisLabel: { color: axisColor, fontSize: 11 },
    },
    yAxis: {
      type: 'category',
      data: entries.map(([key]) => SCENARIO_LABEL[key] ?? key),
      axisLine: { lineStyle: { color: gridColor } },
      axisLabel: { color: axisColor, fontSize: 11 },
    },
    series: [
      {
        type: 'bar',
        data: entries.map(([, value]) => value),
        itemStyle: { color: '#a78bfa', borderRadius: [0, 3, 3, 0] },
        barMaxWidth: 18,
        label: { show: true, position: 'right', color: axisColor, fontSize: 11 },
      },
    ],
  }
})
</script>

<template>
  <div class="flex flex-col gap-3">
    <div v-if="error" class="card p-4">
      <EmptyState icon="alert" title="数据加载失败" :hint="error">
        <button class="btn mt-2" @click="load">重试</button>
      </EmptyState>
    </div>

    <template v-else>
      <!-- 服务状态 -->
      <section class="card flex flex-wrap items-center gap-x-5 gap-y-2 p-3">
        <div class="flex items-center gap-2">
          <StatusBadge
            :label="health?.status === 'ok' ? '服务正常' : '服务降级'"
            :tone="health?.status === 'ok' ? 'accent' : 'warn'"
            :pulse="health?.status === 'ok'"
          />
          <span class="text-xs text-ink-muted">运行 {{ health?.uptime_s ?? 0 }} 秒</span>
        </div>
        <div class="num flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-muted">
          <span>数据库 {{ health?.db.ok ? '正常' : '异常' }}</span>
          <span>RAG {{ health?.rag.mode ?? '—' }}（{{ health?.rag.kb_version ?? '—' }}）</span>
          <span>规则 {{ health?.rules.version ?? '—' }}</span>
          <span>LLM {{ health?.llm_mode ?? '—' }}</span>
          <span>SSE 连接 {{ health?.sse_connections ?? 0 }}</span>
        </div>
      </section>

      <!-- 指标卡 -->
      <section class="grid grid-cols-2 gap-2 lg:grid-cols-4">
        <MetricCard
          label="近 7 天运行"
          :value="formatNumber(stats?.totals.runs ?? 0)"
          :sub="`进行中 ${stats?.totals.active ?? 0} · 失败 ${stats?.totals.failed ?? 0}`"
          icon="runs"
          tone="info"
        />
        <MetricCard
          label="成功率"
          :value="`${(successRate * 100).toFixed(0)}%`"
          :sub="`完成 ${stats?.totals.succeeded ?? 0} / 共 ${stats?.totals.runs ?? 0}`"
          icon="check"
          :tone="successRate >= 0.9 ? 'accent' : successRate >= 0.7 ? 'warn' : 'danger'"
        />
        <MetricCard
          label="Token 消耗"
          :value="formatTokens((stats?.totals.prompt_tokens ?? 0) + (stats?.totals.completion_tokens ?? 0))"
          :sub="`入 ${formatTokens(stats?.totals.prompt_tokens)} / 出 ${formatTokens(stats?.totals.completion_tokens)}`"
          icon="database"
          tone="violet"
        />
        <MetricCard
          label="估算成本"
          :value="formatCost(stats?.totals.est_cost)"
          :sub="`${formatNumber(stats?.totals.llm_calls ?? 0)} 次模型调用`"
          icon="scale"
          tone="warn"
        />
      </section>

      <!-- 图表 -->
      <section class="grid gap-3 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div class="card p-3">
          <h2 class="mb-1 font-mono text-xs font-semibold text-ink-muted">近 7 天运行量与成本</h2>
          <EChart v-if="Object.keys(stats?.by_day ?? {}).length" :option="trendOption" height="240px" />
          <EmptyState v-else icon="database" title="暂无运行数据" hint="触发一次分析后即可看到趋势" />
        </div>
        <div class="card p-3">
          <h2 class="mb-1 font-mono text-xs font-semibold text-ink-muted">场景分布</h2>
          <EChart v-if="Object.keys(stats?.by_scenario ?? {}).length" :option="scenarioOption" height="240px" />
          <EmptyState v-else icon="database" title="暂无场景数据" />
        </div>
      </section>

      <!-- 最近运行 -->
      <section class="card overflow-hidden">
        <header class="flex items-center justify-between border-b border-line-soft px-3 py-2">
          <h2 class="font-mono text-xs font-semibold text-ink-muted">最近运行</h2>
          <RouterLink class="btn btn-ghost px-2 py-1 text-xs" to="/runs">
            全部运行 <AppIcon name="chevronRight" :size="12" />
          </RouterLink>
        </header>
        <EmptyState
          v-if="!recent.length && !loading"
          icon="runs"
          title="还没有运行记录"
          hint="在演示客服平台发消息或调用 /api/v1/analyze/runs 触发分析"
        />
        <table v-else class="table">
          <thead>
            <tr>
              <th>运行 ID</th>
              <th>场景</th>
              <th>状态</th>
              <th>风险</th>
              <th>成本</th>
              <th>创建时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in recent" :key="item.run_id" class="clickable">
              <td>
                <RouterLink class="num text-info hover:underline" :to="`/runs/${item.run_id}`">
                  {{ item.run_id }}
                </RouterLink>
                <div v-if="item.external_ref" class="text-[11px] text-ink-faint">
                  <span v-if="item.external_ref.source === 'demo_platform'" class="text-info">演示台</span>
                  <span v-else-if="item.external_ref.source">{{ item.external_ref.source }}</span>
                  <span v-if="item.external_ref.customer_name"> · {{ item.external_ref.customer_name }}</span>
                </div>
              </td>
              <td>{{ SCENARIO_LABEL[item.scenario] ?? item.scenario }}</td>
              <td>
                <StatusBadge
                  :label="STATUS_META[item.status].label"
                  :tone="STATUS_META[item.status].tone"
                  :pulse="['queued', 'awaiting_confirm', 'running'].includes(item.status)"
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
              <td class="num">{{ formatCost(item.cost?.est_cost) }}</td>
              <td class="num text-ink-muted">{{ formatRelative(item.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>
  </div>
</template>
