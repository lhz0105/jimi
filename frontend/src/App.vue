<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import Modal from '@/components/Modal.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import ToastHost from '@/components/ToastHost.vue'
import { errorText } from '@/api/client'
import { apiKey, setApiKey } from '@/api/client'
import { useHealth } from '@/composables/useHealth'
import { useToast } from '@/composables/useToast'
import type { IconName } from '@/components/icons'

const route = useRoute()
const { health, healthError, refresh } = useHealth()
const toast = useToast()

const navItems: Array<{ to: string; label: string; icon: IconName }> = [
  { to: '/', label: '总览', icon: 'overview' },
  { to: '/runs', label: '运行记录', icon: 'runs' },
  { to: '/knowledge', label: '知识库', icon: 'knowledge' },
  { to: '/rules', label: '规则', icon: 'rules' },
  { to: '/system', label: '系统', icon: 'system' },
]

const pageTitle = computed(() => (route.meta.title as string | undefined) ?? '')

/* ------------------------------ 健康状态灯 ------------------------------ */

const healthTone = computed(() => {
  if (healthError.value) return 'danger' as const
  if (!health.value) return 'slate' as const
  return health.value.status === 'ok' ? 'accent' as const : 'warn' as const
})

const healthText = computed(() => {
  if (healthError.value) return '后端不可达'
  if (!health.value) return '检测中…'
  return health.value.status === 'ok' ? '服务正常' : '服务降级'
})

/* ------------------------------- API Key ------------------------------- */

const keyDialogOpen = ref(false)
const keyDraft = ref('')

function openKeyDialog(): void {
  keyDraft.value = apiKey.value
  keyDialogOpen.value = true
}

function saveKey(): void {
  setApiKey(keyDraft.value)
  keyDialogOpen.value = false
  toast.success(keyDraft.value ? '已保存访问密钥' : '已清除访问密钥')
  void refresh()
}

const healthDetail = computed(() => {
  const h = health.value
  if (!h) return ''
  return `RAG ${h.rag.mode} · 规则 ${h.rules.version ?? '—'} · LLM ${h.llm_mode} · SSE ${h.sse_connections}`
})

function onRefreshHealth(): void {
  void refresh()
  if (healthError.value) toast.error(errorText(healthError.value))
}
</script>

<template>
  <div class="flex min-h-dvh flex-col lg:flex-row">
    <!-- 侧边导航（≥1024px） -->
    <aside
      class="hidden w-56 shrink-0 flex-col border-r border-line-soft bg-surface/60 lg:flex"
      aria-label="主导航"
    >
      <div class="flex items-center gap-2 px-4 py-4">
        <div class="rounded-md border border-accent/40 bg-accent/10 p-1.5 text-accent">
          <AppIcon name="brain" :size="16" />
        </div>
        <div class="leading-tight">
          <div class="text-sm font-semibold">迹觅·Evidence</div>
          <div class="text-[11px] text-ink-faint">防 AIGC 欺诈观测台</div>
        </div>
      </div>
      <nav class="flex flex-col gap-0.5 px-2">
        <RouterLink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="flex items-center gap-2.5 rounded-md px-3 py-2 text-sm text-ink-muted transition-colors hover:bg-surface-2 hover:text-ink"
          active-class="!bg-surface-2 !text-ink border border-line-soft"
          :exact-active-class="item.to === '/' ? '!bg-surface-2 !text-ink border border-line-soft' : undefined"
        >
          <AppIcon :name="item.icon" :size="15" />
          {{ item.label }}
        </RouterLink>
      </nav>
      <div class="mt-auto px-4 py-4 text-[11px] text-ink-faint">
        <p>单 worker · SSE 观测</p>
        <p class="num mt-0.5">/docs 查看接口</p>
      </div>
    </aside>

    <div class="flex min-w-0 flex-1 flex-col">
      <!-- 顶栏 -->
      <header
        class="sticky top-0 z-30 border-b border-line-soft bg-canvas/90 backdrop-blur"
      >
        <div class="flex items-center gap-3 px-4 py-2.5">
          <h1 class="font-mono text-sm font-semibold">{{ pageTitle }}</h1>

          <button
            class="ml-auto flex items-center gap-2 rounded-full border border-line-soft bg-surface px-3 py-1 text-xs transition-colors hover:border-line"
            :title="healthError ?? healthDetail"
            @click="onRefreshHealth"
          >
            <StatusBadge :label="healthText" :tone="healthTone" :pulse="!health && !healthError" />
            <span class="hidden text-ink-muted sm:inline">{{ healthDetail }}</span>
            <AppIcon name="refresh" :size="12" class="text-ink-faint" />
          </button>

          <button class="btn btn-ghost px-2 py-1" title="访问密钥" @click="openKeyDialog">
            <AppIcon name="key" :size="15" />
          </button>
        </div>

        <!-- 窄屏导航 -->
        <nav class="flex gap-1 overflow-x-auto px-3 pb-2 lg:hidden" aria-label="主导航">
          <RouterLink
            v-for="item in navItems"
            :key="item.to"
            :to="item.to"
            class="flex items-center gap-1.5 rounded-md border border-transparent px-2.5 py-1 text-xs whitespace-nowrap text-ink-muted hover:bg-surface-2 hover:text-ink"
            active-class="!border-line-soft !bg-surface-2 !text-ink"
          >
            <AppIcon :name="item.icon" :size="13" />
            {{ item.label }}
          </RouterLink>
        </nav>
      </header>

      <main class="min-w-0 flex-1 p-4">
        <RouterView />
      </main>
    </div>

    <Modal :open="keyDialogOpen" title="访问密钥（X-API-Key）" @close="keyDialogOpen = false">
      <p class="text-xs text-ink-muted">
        后端配置了 <code class="num">ADMIN_API_KEY</code> 时需要填写；未配置（默认值）时本机访问可留空。
        密钥仅保存在浏览器 localStorage，随请求头发送。
      </p>
      <label class="mt-3 block text-xs text-ink-muted" for="api-key-input">密钥</label>
      <input
        id="api-key-input"
        v-model="keyDraft"
        class="input mt-1 w-full"
        type="password"
        autocomplete="off"
        placeholder="留空表示不发送密钥"
        @keyup.enter="saveKey"
      />
      <template #footer>
        <button class="btn" @click="keyDialogOpen = false">取消</button>
        <button class="btn btn-primary" @click="saveKey">保存</button>
      </template>
    </Modal>

    <ToastHost />
  </div>
</template>
