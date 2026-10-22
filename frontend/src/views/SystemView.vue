<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import JsonBlock from '@/components/JsonBlock.vue'
import MetricCard from '@/components/MetricCard.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { fetchConfig } from '@/api/admin'
import { API_BASE, errorText } from '@/api/client'
import type { ConfigSnapshot } from '@/api/types'
import { useHealth } from '@/composables/useHealth'
import { useToast } from '@/composables/useToast'
import { formatDuration, formatNumber } from '@/utils/format'

const toast = useToast()
const { health, healthError, refresh } = useHealth()
const config = ref<ConfigSnapshot | null>(null)
const loading = ref(false)

const docsUrl = computed(() => `${API_BASE || ''}/docs`)
const healthUrl = computed(() => `${API_BASE || ''}/api/admin/health`)

async function loadConfig(): Promise<void> {
  loading.value = true
  try {
    config.value = await fetchConfig()
  } catch (error) {
    toast.error(errorText(error))
  } finally {
    loading.value = false
  }
}

onMounted(loadConfig)
</script>

<template>
  <div class="flex flex-col gap-3">
    <!-- 健康检查 -->
    <section class="card p-3">
      <header class="mb-2 flex flex-wrap items-center gap-2">
        <h2 class="font-mono text-xs font-semibold text-ink-muted">服务健康</h2>
        <StatusBadge
          :label="healthError ? '不可达' : health?.status === 'ok' ? '正常' : '降级'"
          :tone="healthError ? 'danger' : health?.status === 'ok' ? 'accent' : 'warn'"
          :pulse="!healthError"
        />
        <div class="ml-auto flex items-center gap-2">
          <a class="btn px-2 py-1 text-xs" :href="docsUrl" target="_blank" rel="noreferrer">
            <AppIcon name="external" :size="13" /> Swagger 接口文档
          </a>
          <a class="btn px-2 py-1 text-xs" :href="healthUrl" target="_blank" rel="noreferrer">
            <AppIcon name="external" :size="13" /> 健康检查 JSON
          </a>
          <button class="btn px-2 py-1 text-xs" @click="refresh">
            <AppIcon name="refresh" :size="13" /> 刷新
          </button>
        </div>
      </header>
      <p v-if="healthError" class="text-xs text-danger">{{ healthError }}</p>
      <div v-else class="grid grid-cols-2 gap-2 lg:grid-cols-4">
        <MetricCard label="运行时长" :value="formatDuration(Date.now() - (health?.uptime_s ?? 0) * 1000)" sub="自服务启动" icon="clock" tone="info" />
        <MetricCard
          label="数据库"
          :value="health?.db.ok ? '正常' : '异常'"
          :sub="health?.db.error ?? 'SQLite WAL'"
          icon="database"
          :tone="health?.db.ok ? 'accent' : 'danger'"
        />
        <MetricCard
          label="知识库"
          :value="health?.rag.mode === 'hybrid' ? '混合检索' : (health?.rag.mode ?? '—')"
          :sub="health?.rag.kb_version ?? '未初始化'"
          icon="knowledge"
          tone="teal"
        />
        <MetricCard
          label="SSE 连接"
          :value="formatNumber(health?.sse_connections ?? 0)"
          :sub="`LLM 模式 ${health?.llm_mode ?? '—'}`"
          icon="zap"
          tone="violet"
        />
      </div>
    </section>

    <!-- 配置快照 -->
    <section v-if="config" class="grid gap-3 xl:grid-cols-2">
      <div class="card p-3">
        <h2 class="mb-2 font-mono text-xs font-semibold text-ink-muted">模型网关（密钥已脱敏）</h2>
        <dl class="space-y-1.5 text-xs">
          <div class="flex gap-2">
            <dt class="w-24 shrink-0 text-ink-muted">主模型</dt>
            <dd class="num min-w-0 flex-1 break-all">
              {{ config.llm_main.model }} · {{ config.llm_main.base_url || '（未配置）' }} · {{ config.llm_main.api_key || '—' }}
            </dd>
          </div>
          <div class="flex gap-2">
            <dt class="w-24 shrink-0 text-ink-muted">识图模型</dt>
            <dd class="num min-w-0 flex-1 break-all">
              {{ config.llm_vision.model }} · {{ config.llm_vision.base_url || '（未配置）' }} · {{ config.llm_vision.api_key || '—' }}
            </dd>
          </div>
          <div class="flex gap-2">
            <dt class="w-24 shrink-0 text-ink-muted">联网搜索</dt>
            <dd class="num min-w-0 flex-1">{{ config.tavily_api_key || '（未配置）' }}</dd>
          </div>
          <div class="flex gap-2">
            <dt class="w-24 shrink-0 text-ink-muted">运行模式</dt>
            <dd class="num">{{ config.llm_mode }}（fake 为无 key 演示模式）</dd>
          </div>
        </dl>

        <h2 class="mt-4 mb-2 font-mono text-xs font-semibold text-ink-muted">RAG</h2>
        <dl class="space-y-1.5 text-xs">
          <div class="flex gap-2">
            <dt class="w-24 shrink-0 text-ink-muted">向量模型</dt>
            <dd class="num">{{ config.rag.embedding_model }}</dd>
          </div>
          <div class="flex gap-2">
            <dt class="w-24 shrink-0 text-ink-muted">检索模式</dt>
            <dd>{{ config.rag.mode }} · Top K {{ config.rag.top_k }}</dd>
          </div>
        </dl>
      </div>

      <div class="card p-3">
        <h2 class="mb-2 font-mono text-xs font-semibold text-ink-muted">预算闸门（单次运行上限）</h2>
        <div class="grid grid-cols-2 gap-2">
          <MetricCard label="LLM 调用" :value="config.budget.max_llm_calls ?? '—'" icon="zap" tone="violet" />
          <MetricCard label="工具调用" :value="config.budget.max_tool_calls ?? '—'" icon="tool" tone="teal" />
          <MetricCard label="识图调用" :value="config.budget.max_vision_calls ?? '—'" icon="brain" tone="info" />
          <MetricCard label="联网搜索" :value="config.budget.max_tavily_calls ?? '—'" icon="search" tone="warn" />
          <MetricCard label="估算成本" :value="config.budget.max_run_cost ?? '—'" icon="scale" tone="danger" />
          <MetricCard
            label="调查轮数"
            :value="config.budget.max_investigate_loops ?? '—'"
            icon="runs"
            tone="slate"
          />
        </div>

        <h2 class="mt-4 mb-2 font-mono text-xs font-semibold text-ink-muted">数据目录</h2>
        <JsonBlock :value="config.paths" :collapsed-lines="8" />
      </div>
    </section>

    <section v-else class="card p-4 text-sm text-ink-muted">
      {{ loading ? '配置加载中…' : '配置不可用' }}
    </section>
  </div>
</template>
