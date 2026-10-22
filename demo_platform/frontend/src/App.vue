<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import AnalysisPanel from '@/components/AnalysisPanel.vue'
import ChatPanel from '@/components/ChatPanel.vue'
import ConversationList from '@/components/ConversationList.vue'
import ToastHost from '@/components/ToastHost.vue'
import {
  createConversation,
  deleteConversation,
  fetchHealth,
  getConversation,
  listConversations,
  postMessage,
  recheckConversation,
  seedDemo,
  startAnalysis,
  uploadImage,
} from '@/api'
import { errorText } from '@/api/client'
import type { Analysis, Attachment, CheckResult, Conversation, Message } from '@/api/types'
import { useToast } from '@/composables/useToast'

const toast = useToast()

const conversations = ref<Conversation[]>([])
const listLoading = ref(false)
const activeId = ref<string | null>(null)
const conversation = ref<Conversation | null>(null)
const messages = ref<Message[]>([])
const attachments = ref<Attachment[]>([])
const analyses = ref<Analysis[]>([])
const activeAnalysis = ref<Analysis | null>(null)
const hint = ref<CheckResult | null>(null)
const sending = ref(false)
const starting = ref(false)
const deleteOpen = ref(false)
const deleting = ref(false)
const agentOnline = ref(false)
const chatRef = ref<InstanceType<typeof ChatPanel> | null>(null)

const lastCustomerMessage = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i -= 1) {
    if (messages.value[i].role === 'customer') return messages.value[i]
  }
  return null
})

function deriveHint(): void {
  const msg = lastCustomerMessage.value
  if (!msg?.check_result?.need_analysis) {
    hint.value = null
    return
  }
  const analysisSince = analyses.value.find((a) => a.created_at >= msg.created_at)
  hint.value = analysisSince ? null : msg.check_result
}

async function refreshList(): Promise<void> {
  try {
    conversations.value = await listConversations()
  } catch (error) {
    toast.error(errorText(error))
  }
}

async function loadConversation(id: string): Promise<void> {
  try {
    let detail = await getConversation(id)
    // 旧版本灌入的剧本消息没有触发判断结果：打开会话时自动补算（/check 零 LLM 成本）
    const missingChecks = detail.messages.some(
      (m) => m.role === 'customer' && !m.check_result,
    )
    if (missingChecks) {
      const result = await recheckConversation(id).catch(() => null)
      if (result && result.checked > 0) detail = await getConversation(id)
    }
    activeId.value = id
    conversation.value = detail.conversation
    messages.value = detail.messages
    attachments.value = detail.attachments
    analyses.value = detail.analyses
    activeAnalysis.value = detail.analyses[0] ?? null
    deriveHint()
  } catch (error) {
    toast.error(errorText(error))
  }
}

async function selectConversation(id: string): Promise<void> {
  if (id === activeId.value) return
  await loadConversation(id)
}

async function newConversation(): Promise<void> {
  try {
    const conv = await createConversation(`客户 ${conversations.value.length + 1}`)
    await refreshList()
    await loadConversation(conv.id)
  } catch (error) {
    toast.error(errorText(error))
  }
}

async function loadScenario(scenario: string): Promise<void> {
  try {
    const result = await seedDemo(scenario)
    await refreshList()
    await loadConversation(result.conversation.id)
    toast.success('演示剧本已载入：发送一条客户消息即可触发分析')
  } catch (error) {
    toast.error(errorText(error))
  }
}

async function sendMessage(payload: { text: string; attachmentIds: string[] }): Promise<void> {
  if (!activeId.value) return
  sending.value = true
  const convId = activeId.value
  try {
    const result = await postMessage(convId, {
      role: 'customer',
      text: payload.text,
      attachment_ids: payload.attachmentIds,
    })
    messages.value = [...messages.value, result.message]
    const atts = await getConversation(convId)
    attachments.value = atts.attachments

    if (result.analysis) {
      analyses.value = [result.analysis, ...analyses.value]
      activeAnalysis.value = result.analysis
      hint.value = null
    } else {
      deriveHint()
    }
    await refreshList()
  } catch (error) {
    toast.error(errorText(error))
  } finally {
    sending.value = false
  }
}

async function uploadAttachment(file: File): Promise<void> {
  if (!activeId.value) return
  try {
    const attachment = await uploadImage(activeId.value, file)
    chatRef.value?.setUploading(false)
    chatRef.value?.addPending(attachment as unknown as Attachment)
    attachments.value = [...attachments.value.filter((a) => a.id !== attachment.id), { ...(attachment as any), message_id: null }]
  } catch (error) {
    chatRef.value?.setUploading(false)
    toast.error(errorText(error))
  }
}

async function startAnalysisNow(payload: { decisionId: string; scenario: string | null }): Promise<void> {
  if (!activeId.value) return
  starting.value = true
  try {
    const result = await startAnalysis(activeId.value, {
      decision_id: payload.decisionId || undefined,
      scenario: payload.scenario || undefined,
      auto_confirm: true,
    })
    hint.value = null
    if (result.reused) {
      // agent 去重：同一诉求近期已分析过，直接展示既有结果
      toast.info('该诉求近期已分析过，已展示最近一次结果')
      if (!analyses.value.some((a) => a.id === result.analysis.id)) {
        analyses.value = [result.analysis, ...analyses.value]
      }
    } else {
      analyses.value = [result.analysis, ...analyses.value]
      toast.success(result.agent.message || '分析已启动')
    }
    activeAnalysis.value = result.analysis
    await refreshList()
  } catch (error) {
    toast.error(errorText(error))
  } finally {
    starting.value = false
  }
}

function latestScenario(): string {
  const fromAnalysis = analyses.value[0]?.scenario
  if (fromAnalysis) return fromAnalysis
  for (let i = messages.value.length - 1; i >= 0; i -= 1) {
    const scenario = messages.value[i].check_result?.scenario
    if (scenario) return scenario
  }
  return conversation.value?.channel === 'seed_post' ? 'seeding_post' : 'product_damage_claim'
}

async function forceAnalyze(message: Message): Promise<void> {
  if (!activeId.value || starting.value) return
  await startAnalysisNow({
    decisionId: message.check_result?.decision_id ?? '',
    scenario: message.check_result?.scenario ?? latestScenario(),
  })
}

function requestDelete(): void {
  if (conversation.value) deleteOpen.value = true
}

async function confirmDelete(): Promise<void> {
  const id = activeId.value
  if (!id) return
  deleting.value = true
  try {
    await deleteConversation(id)
    conversations.value = conversations.value.filter((c) => c.id !== id)
    activeId.value = null
    conversation.value = null
    messages.value = []
    attachments.value = []
    analyses.value = []
    activeAnalysis.value = null
    hint.value = null
    deleteOpen.value = false
    toast.success('会话已删除')
    if (conversations.value.length) await loadConversation(conversations.value[0].id)
  } catch (error) {
    toast.error(errorText(error))
  } finally {
    deleting.value = false
  }
}

function onAnalysisUpdated(analysis: Analysis): void {
  activeAnalysis.value = analysis
  const index = analyses.value.findIndex((a) => a.id === analysis.id)
  if (index >= 0) {
    const next = [...analyses.value]
    next[index] = analysis
    analyses.value = next
  }
}

let listTimer: number | null = null
function scheduleListRefresh(): void {
  if (listTimer !== null) return
  listTimer = window.setTimeout(() => {
    listTimer = null
    void refreshList()
  }, 800)
}

onMounted(async () => {
  listLoading.value = true
  await refreshList()
  listLoading.value = false
  if (conversations.value.length) {
    await loadConversation(conversations.value[0].id)
  }
  try {
    const health = await fetchHealth()
    agentOnline.value = health.agent.ok
    if (!health.agent.ok) toast.error(`Agent 服务不可达：${health.agent.error ?? health.agent.base_url}`)
  } catch {
    agentOnline.value = false
  }
})
</script>

<template>
  <div class="flex h-dvh flex-col overflow-hidden">
    <header class="border-b border-line bg-surface/90 backdrop-blur">
      <div class="mx-auto flex w-full max-w-[1600px] items-center gap-3 px-4 py-2.5">
        <span class="flex size-8 items-center justify-center rounded-xl bg-primary text-white shadow-sm">
          <AppIcon name="sparkle" :size="17" />
        </span>
        <div class="leading-tight">
          <h1 class="text-sm font-semibold">迹觅·Evidence 客服演示台</h1>
          <p class="text-[10.5px] text-ink-faint">智能欺诈识别 · 对接 迹觅·Evidence 分析服务</p>
        </div>
        <div class="ml-auto flex items-center gap-3 text-[11px] text-ink-muted">
          <span class="flex items-center gap-1.5">
            <span
              class="size-1.5 rounded-full"
              :class="agentOnline ? 'bg-success' : 'bg-danger'"
            />
            {{ agentOnline ? 'Agent 已连接' : 'Agent 未连接' }}
          </span>
          <span class="hidden text-ink-faint sm:inline">演示数据，仅用于功能展示</span>
        </div>
      </div>
    </header>

    <main
      class="mx-auto grid w-full max-w-[1600px] flex-1 min-h-0 gap-3 overflow-y-auto px-4 py-3 lg:grid-cols-[280px_minmax(0,1fr)_400px] lg:overflow-hidden"
    >
      <ConversationList
        class="h-[460px] min-h-0 lg:h-full"
        :conversations="conversations"
        :active-id="activeId"
        :loading="listLoading"
        @select="selectConversation"
        @create="newConversation"
        @seed="loadScenario"
      />
      <ChatPanel
        ref="chatRef"
        class="h-[560px] min-h-0 lg:h-full"
        :conversation="conversation"
        :messages="messages"
        :attachments="attachments"
        :sending="sending"
        :starting="starting"
        @send="sendMessage"
        @upload="uploadAttachment"
        @analyze="forceAnalyze"
        @delete="requestDelete"
      />
      <AnalysisPanel
        class="h-[620px] min-h-0 lg:h-full"
        :analysis="activeAnalysis"
        :hint="hint"
        :starting="starting"
        @start="startAnalysisNow"
        @updated="onAnalysisUpdated"
        @changed="scheduleListRefresh"
      />
    </main>

    <ToastHost />

    <div
      v-if="deleteOpen"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
      @click.self="deleteOpen = false"
    >
      <div class="w-full max-w-sm rounded-2xl border border-line bg-surface p-5 shadow-xl">
        <h3 class="text-sm font-semibold">删除会话</h3>
        <p class="mt-2 text-xs leading-relaxed text-ink-muted">
          确认删除「{{ conversation?.customer_name }}」？会话、消息、图片和分析记录将从演示平台中移除，且不可恢复。
        </p>
        <div class="mt-4 flex justify-end gap-2">
          <button class="btn" :disabled="deleting" @click="deleteOpen = false">取消</button>
          <button class="btn btn-danger" :disabled="deleting" @click="confirmDelete">
            {{ deleting ? '删除中…' : '确认删除' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
