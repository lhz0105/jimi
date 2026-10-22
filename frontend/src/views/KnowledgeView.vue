<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import MarkdownView from '@/components/MarkdownView.vue'
import Modal from '@/components/Modal.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import {
  addKbDocument,
  deleteKbDocument,
  deletePriorCase,
  fetchKbDocuments,
  fetchPriorCaseFeedback,
  fetchPriorCases,
  reindexKb,
  reindexPriorCases,
  searchKb,
} from '@/api/admin'
import { errorText } from '@/api/client'
import type {
  KbDocumentsResponse,
  KbSearchHit,
  PriorCase,
  PriorCaseFeedback,
} from '@/api/types'
import { useToast } from '@/composables/useToast'
import { formatDateTime } from '@/utils/format'
import { HUMAN_VERDICT_META, PRIOR_FEEDBACK_META, SCENARIO_LABEL } from '@/utils/meta'

const toast = useToast()

const data = ref<KbDocumentsResponse | null>(null)
const loading = ref(false)
const busy = ref(false)

const uploadOpen = ref(false)
const uploadPath = ref('')
const uploadContent = ref('')
const deleteTarget = ref<{ id: string; path: string } | null>(null)

const section = ref<'docs' | 'prior'>('docs')
const priorCases = ref<PriorCase[]>([])
const priorLoading = ref(false)
const priorBusy = ref(false)
const priorScenario = ref('')
const selectedCase = ref<PriorCase | null>(null)
const selectedFeedback = ref<PriorCaseFeedback[]>([])
const feedbackLoading = ref(false)
const priorDeleteTarget = ref<PriorCase | null>(null)

const query = ref('')
const scenario = ref('')
const topK = ref(5)
const hits = ref<KbSearchHit[]>([])
const searching = ref(false)
const searched = ref(false)

const stats = computed(() => data.value?.stats)

async function load(): Promise<void> {
  loading.value = true
  try {
    data.value = await fetchKbDocuments()
  } catch (error) {
    toast.error(errorText(error))
  } finally {
    loading.value = false
  }
}

async function doReindex(rebuild: boolean): Promise<void> {
  busy.value = true
  try {
    const result = await reindexKb(rebuild)
    toast.success(`索引已更新（${rebuild ? '全量' : '增量'}）：${JSON.stringify(result.stats).slice(0, 80)}`)
    await load()
  } catch (error) {
    toast.error(errorText(error))
  } finally {
    busy.value = false
  }
}

function onFilePicked(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  if (!/\.(md|txt)$/i.test(file.name)) {
    toast.error('仅支持 .md / .txt 文件')
    return
  }
  const reader = new FileReader()
  reader.onload = () => {
    uploadContent.value = String(reader.result ?? '')
    if (!uploadPath.value) uploadPath.value = `uploads/${file.name}`
  }
  reader.readAsText(file, 'utf-8')
  input.value = ''
}

async function doUpload(): Promise<void> {
  if (!uploadPath.value.trim() || !uploadContent.value.trim()) {
    toast.error('请填写文档路径与内容')
    return
  }
  busy.value = true
  try {
    await addKbDocument(uploadPath.value.trim(), uploadContent.value)
    toast.success('文档已保存并重建索引')
    uploadOpen.value = false
    uploadPath.value = ''
    uploadContent.value = ''
    await load()
  } catch (error) {
    toast.error(errorText(error))
  } finally {
    busy.value = false
  }
}

async function doDelete(): Promise<void> {
  if (!deleteTarget.value) return
  busy.value = true
  try {
    await deleteKbDocument(deleteTarget.value.id)
    toast.success(`已删除 ${deleteTarget.value.path}`)
    deleteTarget.value = null
    await load()
  } catch (error) {
    toast.error(errorText(error))
  } finally {
    busy.value = false
  }
}

/** 命中卡片上的小节标签：取 heading 末级，避免与文档标题重复。 */
function headingTail(hit: KbSearchHit): string | null {
  const tail = hit.heading_path?.split(' > ').at(-1)?.replace(/^#+\s*/, '').trim()
  if (!tail || tail === hit.doc_title) return null
  return tail
}

async function doSearch(): Promise<void> {
  if (!query.value.trim()) return
  searching.value = true
  try {
    const result = await searchKb(query.value.trim(), scenario.value || undefined, topK.value)
    hits.value = result.items
    searched.value = true
  } catch (error) {
    toast.error(errorText(error))
  } finally {
    searching.value = false
  }
}

async function loadPriorCases(): Promise<void> {
  priorLoading.value = true
  try {
    const result = await fetchPriorCases({
      scenario: priorScenario.value || undefined,
      page_size: 100,
    })
    priorCases.value = result.items
  } catch (error) {
    toast.error(errorText(error))
  } finally {
    priorLoading.value = false
  }
}

async function doReindexPrior(): Promise<void> {
  priorBusy.value = true
  try {
    const result = await reindexPriorCases()
    toast.success(`先前案例索引已重建：${JSON.stringify(result.stats).slice(0, 80)}`)
    await loadPriorCases()
  } catch (error) {
    toast.error(errorText(error))
  } finally {
    priorBusy.value = false
  }
}

async function openPriorCase(item: PriorCase): Promise<void> {
  selectedCase.value = item
  selectedFeedback.value = []
  feedbackLoading.value = true
  try {
    const result = await fetchPriorCaseFeedback(item.id)
    selectedCase.value = result.case
    selectedFeedback.value = result.feedback
  } catch (error) {
    toast.error(errorText(error))
  } finally {
    feedbackLoading.value = false
  }
}

function closePriorCase(): void {
  selectedCase.value = null
  selectedFeedback.value = []
}

function requestPriorDelete(item: PriorCase): void {
  priorDeleteTarget.value = item
  if (selectedCase.value?.id === item.id) closePriorCase()
}

function deleteSelectedCase(): void {
  if (selectedCase.value) requestPriorDelete(selectedCase.value)
}

async function doDeletePriorCase(): Promise<void> {
  const target = priorDeleteTarget.value
  if (!target) return
  priorBusy.value = true
  try {
    const result = await deletePriorCase(target.id)
    const suffix = result.review_reset ? '；人工复核已回到可重新生成状态' : ''
    toast.success(`已删除先前案例「${target.title}」${suffix}`)
    priorDeleteTarget.value = null
    await loadPriorCases()
  } catch (error) {
    toast.error(errorText(error))
  } finally {
    priorBusy.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="flex flex-col gap-3">
    <div class="flex flex-wrap items-center gap-1">
      <button
        class="btn px-2.5 py-1 text-xs"
        :class="section === 'docs' ? 'btn-primary' : 'btn-ghost'"
        @click="section = 'docs'"
      >
        知识文档
      </button>
      <button
        class="btn px-2.5 py-1 text-xs"
        :class="section === 'prior' ? 'btn-primary' : 'btn-ghost'"
        @click="section = 'prior'; loadPriorCases()"
      >
        先前案例
      </button>
    </div>

    <template v-if="section === 'docs'">
    <!-- 知识库状态 -->
    <section class="card flex flex-wrap items-center gap-x-5 gap-y-2 p-3">
      <StatusBadge
        :label="data?.rag_mode === 'hybrid' ? '混合检索' : data?.rag_mode === 'bm25_only' ? '仅关键词（降级）' : '未初始化'"
        :tone="data?.rag_mode === 'hybrid' ? 'accent' : 'warn'"
      />
      <span class="num text-xs text-ink-muted">{{ data?.kb_version ?? '—' }}</span>
      <span class="num text-xs text-ink-muted">
        分块 {{ stats?.chunks ?? '—' }}（向量 {{ stats?.dense_chunks ?? '—' }} / BM25 {{ stats?.bm25_chunks ?? '—' }}）
      </span>
      <div class="ml-auto flex flex-wrap items-center gap-2">
        <button class="btn px-2 py-1 text-xs" :disabled="busy" @click="doReindex(false)">
          <AppIcon name="refresh" :size="13" /> 增量重建
        </button>
        <button class="btn px-2 py-1 text-xs" :disabled="busy" @click="doReindex(true)">
          <AppIcon name="database" :size="13" /> 全量重建
        </button>
        <button class="btn btn-primary px-2 py-1 text-xs" @click="uploadOpen = true">
          <AppIcon name="upload" :size="13" /> 新增文档
        </button>
      </div>
    </section>

    <!-- 文档表 -->
    <section class="card overflow-hidden">
      <header class="border-b border-line-soft px-3 py-2">
        <h2 class="font-mono text-xs font-semibold text-ink-muted">
          知识库文档（{{ data?.items.length ?? 0 }}）
        </h2>
      </header>
      <EmptyState
        v-if="!data?.items.length && !loading"
        icon="knowledge"
        title="知识库为空"
        hint="点击「新增文档」上传鉴别方法/案例/特征清单（.md / .txt）"
      />
      <table v-else class="table">
        <thead>
          <tr>
            <th>路径</th>
            <th>标题</th>
            <th>场景</th>
            <th>分块</th>
            <th>更新时间</th>
            <th class="w-16">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="doc in data?.items ?? []" :key="doc.id">
            <td class="num text-[12px]">{{ doc.path }}</td>
            <td>{{ doc.title }}</td>
            <td>
              <StatusBadge
                :label="SCENARIO_LABEL[doc.scenario] ?? doc.scenario"
                tone="slate"
                :dot="false"
              />
            </td>
            <td class="num">{{ doc.chunk_count }}</td>
            <td class="num text-ink-muted">{{ formatDateTime(doc.updated_at) }}</td>
            <td>
              <button
                class="btn btn-ghost px-1.5 py-1 text-danger"
                :aria-label="`删除 ${doc.path}`"
                @click="deleteTarget = { id: doc.id, path: doc.path }"
              >
                <AppIcon name="trash" :size="14" />
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 检索调试 -->
    <section class="card p-3">
      <h2 class="mb-2 font-mono text-xs font-semibold text-ink-muted">
        检索调试（双路分数 + RRF 融合分）
      </h2>
      <form class="flex flex-wrap items-end gap-2" @submit.prevent="doSearch">
        <div class="min-w-64 flex-1">
          <label class="mb-1 block text-[11px] text-ink-muted" for="kb-query">查询文本</label>
          <input
            id="kb-query"
            v-model="query"
            class="input w-full"
            placeholder="例如：产品破损 索赔 判定标准"
          />
        </div>
        <div>
          <label class="mb-1 block text-[11px] text-ink-muted" for="kb-scenario">场景过滤</label>
          <select id="kb-scenario" v-model="scenario" class="input min-w-32">
            <option value="">不限</option>
            <option v-for="(label, key) in SCENARIO_LABEL" :key="key" :value="key">{{ label }}</option>
          </select>
        </div>
        <div>
          <label class="mb-1 block text-[11px] text-ink-muted" for="kb-topk">Top K</label>
          <input id="kb-topk" v-model.number="topK" class="input w-20" type="number" min="1" max="20" />
        </div>
        <button class="btn btn-primary" type="submit" :disabled="searching">
          <AppIcon name="search" :size="14" /> {{ searching ? '检索中…' : '检索' }}
        </button>
      </form>

      <div v-if="searched" class="mt-3">
        <EmptyState
          v-if="!hits.length"
          icon="search"
          title="无命中"
          hint="尝试更短的关键词，或确认知识库已导入"
        />
        <ul v-else class="space-y-2">
          <li
            v-for="hit in hits"
            :key="hit.chunk_id"
            class="rounded border border-line-soft bg-canvas/40 p-2"
          >
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-[13px] font-medium">{{ hit.doc_title }}</span>
              <StatusBadge
                v-if="headingTail(hit)"
                :label="headingTail(hit)!"
                tone="slate"
                :dot="false"
              />
              <span class="num ml-auto text-[11px] text-ink-muted">
                dense {{ hit.score_dense ?? '—' }} · bm25 {{ hit.score_bm25 ?? '—' }} · rrf {{ hit.score_rrf }}
              </span>
            </div>
            <p class="mt-1 text-[12px] whitespace-pre-wrap text-ink-muted">{{ hit.text }}</p>
          </li>
        </ul>
      </div>
    </section>

    </template>

    <!-- 先前案例 -->
    <template v-else>
      <section class="card flex flex-wrap items-center gap-x-5 gap-y-2 p-3">
        <StatusBadge label="人工判决沉淀" tone="violet" />
        <span class="num text-xs text-ink-muted">共 {{ priorCases.length }} 条</span>
        <span class="text-xs text-ink-faint">独立 Chroma 集合 + BM25，与 doctrine 知识库隔离</span>
        <div class="ml-auto flex flex-wrap items-center gap-2">
          <select v-model="priorScenario" class="input min-w-32" @change="loadPriorCases">
            <option value="">全部场景</option>
            <option v-for="(label, key) in SCENARIO_LABEL" :key="key" :value="key">{{ label }}</option>
          </select>
          <button class="btn px-2 py-1 text-xs" :disabled="priorLoading" @click="loadPriorCases">
            <AppIcon name="refresh" :size="13" /> 刷新
          </button>
          <button class="btn px-2 py-1 text-xs" :disabled="priorBusy" @click="doReindexPrior">
            <AppIcon name="database" :size="13" /> {{ priorBusy ? '重建中…' : '重建索引' }}
          </button>
        </div>
      </section>

      <section class="card overflow-hidden">
        <header class="border-b border-line-soft px-3 py-2">
          <h2 class="font-mono text-xs font-semibold text-ink-muted">
            先前案例（{{ priorCases.length }}）
          </h2>
        </header>
        <EmptyState
          v-if="!priorCases.length && !priorLoading"
          icon="scale"
          title="暂无先前案例"
          hint="在运行详情的「人工判决」中提交判决并生成案例后，会出现在这里。"
        />
        <table v-else class="table">
          <thead>
            <tr>
              <th>标题</th>
              <th>场景</th>
              <th>人工判决</th>
              <th>可靠性</th>
              <th>反馈</th>
              <th>索引</th>
              <th>生成时间</th>
              <th class="w-24">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in priorCases" :key="item.id">
              <td class="max-w-72 truncate" :title="item.title">{{ item.title }}</td>
              <td>
                <StatusBadge
                  :label="SCENARIO_LABEL[item.scenario] ?? item.scenario"
                  tone="slate"
                  :dot="false"
                />
              </td>
              <td>
                <StatusBadge
                  :label="HUMAN_VERDICT_META[item.human_verdict]?.label ?? item.human_verdict"
                  :tone="HUMAN_VERDICT_META[item.human_verdict]?.tone ?? 'slate'"
                />
              </td>
              <td class="num">{{ Number(item.reliability ?? 0.5).toFixed(2) }}</td>
              <td class="num text-[11px] text-ink-faint">
                采纳 {{ item.adopted_count }} · 推翻 {{ item.overturned_count }}
              </td>
              <td>
                <StatusBadge
                  :label="item.index_error ? '索引失败' : item.indexed_at ? '已索引' : '未索引'"
                  :tone="item.index_error ? 'danger' : item.indexed_at ? 'accent' : 'warn'"
                  :dot="false"
                />
              </td>
              <td class="num text-ink-muted">{{ formatDateTime(item.created_at) }}</td>
              <td>
                <div class="flex items-center gap-1">
                  <button class="btn btn-ghost px-2 py-1 text-xs" @click="openPriorCase(item)">
                    查看
                  </button>
                  <button
                    class="btn btn-ghost px-1.5 py-1 text-danger"
                    :aria-label="`删除 ${item.title}`"
                    :disabled="priorBusy"
                    @click="requestPriorDelete(item)"
                  >
                    <AppIcon name="trash" :size="14" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>

    <!-- 新增文档 -->
    <Modal :open="uploadOpen" title="新增 / 更新知识库文档" width="max-w-3xl" @close="uploadOpen = false">
      <div class="flex flex-wrap items-end gap-2">
        <div class="min-w-64 flex-1">
          <label class="mb-1 block text-[11px] text-ink-muted" for="kb-path">相对路径</label>
          <input
            id="kb-path"
            v-model="uploadPath"
            class="input w-full"
            placeholder="如：新增案例/xx案例.md"
          />
        </div>
        <label class="btn cursor-pointer">
          <AppIcon name="upload" :size="13" /> 选择本地文件
          <input
            class="hidden"
            type="file"
            accept=".md,.txt,text/markdown,text/plain"
            @change="onFilePicked"
          />
        </label>
      </div>
      <label class="mt-3 mb-1 block text-[11px] text-ink-muted" for="kb-content">
        文档内容（Markdown / 纯文本，支持 YAML front-matter：title/scenario/doc_type/tags）
      </label>
      <textarea
        id="kb-content"
        v-model="uploadContent"
        class="input num h-72 w-full resize-y"
        placeholder="---&#10;title: 案例标题&#10;scenario: product_damage_claim&#10;---&#10;&#10;# 正文…"
      />
      <template #footer>
        <button class="btn" @click="uploadOpen = false">取消</button>
        <button class="btn btn-primary" :disabled="busy" @click="doUpload">
          {{ busy ? '保存中…' : '保存并重建索引' }}
        </button>
      </template>
    </Modal>

    <!-- 删除确认 -->
    <Modal :open="!!deleteTarget" title="删除知识库文档" @close="deleteTarget = null">
      <p class="text-sm">
        确认删除 <span class="num">{{ deleteTarget?.path }}</span>？文件与索引将一并移除。
      </p>
      <template #footer>
        <button class="btn" @click="deleteTarget = null">返回</button>
        <button class="btn btn-danger" :disabled="busy" @click="doDelete">确认删除</button>
      </template>
    </Modal>

    <!-- 先前案例预览 -->
    <Modal
      :open="!!selectedCase"
      :title="selectedCase?.title || '先前案例'"
      width="max-w-3xl"
      @close="closePriorCase"
    >
      <div v-if="selectedCase" class="space-y-2">
        <div class="flex flex-wrap items-center gap-2">
          <StatusBadge
            :label="SCENARIO_LABEL[selectedCase.scenario] ?? selectedCase.scenario"
            tone="slate"
            :dot="false"
          />
          <StatusBadge
            :label="HUMAN_VERDICT_META[selectedCase.human_verdict]?.label ?? selectedCase.human_verdict"
            :tone="HUMAN_VERDICT_META[selectedCase.human_verdict]?.tone ?? 'slate'"
          />
          <StatusBadge
            :label="`可靠性 ${Number(selectedCase.reliability).toFixed(2)}`"
            tone="violet"
            :dot="false"
          />
          <span class="text-[11px] text-ink-faint">
            {{ selectedCase.index_error || (selectedCase.indexed_at ? '已入索引' : '未索引') }}
          </span>
        </div>
        <MarkdownView :source="selectedCase.markdown" />

        <div class="mt-3 space-y-2 border-t border-line-soft pt-3">
          <div class="flex flex-wrap items-center gap-2">
            <h3 class="font-mono text-xs font-semibold text-ink-muted">权重发展</h3>
            <span class="text-[11px] text-ink-faint">
              初始 0.50；采纳 +1α、推翻 +1β；当前 {{ Number(selectedCase.reliability).toFixed(2) }}
              （采纳 {{ selectedCase.adopted_count }} · 推翻 {{ selectedCase.overturned_count }}）
            </span>
          </div>
          <p v-if="feedbackLoading" class="text-xs text-ink-muted">加载中…</p>
          <p v-else-if="!selectedFeedback.length" class="text-xs text-ink-faint">
            暂无反馈记录；先例被引用且经人工复核后会自动出现。
          </p>
          <ol v-else class="space-y-2">
            <li
              v-for="fb in selectedFeedback"
              :key="fb.id"
              class="rounded-xl border border-line-soft bg-canvas/40 p-2.5 text-[12px]"
            >
              <div class="flex flex-wrap items-center gap-2">
                <StatusBadge
                  :label="PRIOR_FEEDBACK_META[fb.signal]?.label ?? fb.signal"
                  :tone="PRIOR_FEEDBACK_META[fb.signal]?.tone ?? 'slate'"
                  :dot="false"
                />
                <span class="num text-[11px] text-ink-muted">{{ formatDateTime(fb.created_at) }}</span>
                <span class="num text-[11px] text-ink-faint">
                  {{ fb.weight_before.toFixed(2) }} → {{ fb.weight_after.toFixed(2) }}
                </span>
                <span class="text-[11px] text-ink-faint">
                  置信度 {{ fb.confidence !== null ? fb.confidence.toFixed(2) : '—' }}
                </span>
              </div>
              <p class="mt-1 leading-relaxed text-ink-muted">{{ fb.rationale }}</p>
              <p class="num mt-0.5 text-[10px] text-ink-faint">run {{ fb.run_id || '—' }}</p>
            </li>
          </ol>
        </div>
      </div>
      <template #footer>
        <button
          class="btn btn-ghost mr-auto text-danger"
          :disabled="priorBusy"
          @click="deleteSelectedCase"
        >
          <AppIcon name="trash" :size="13" /> 删除该案例
        </button>
        <button class="btn" @click="closePriorCase">关闭</button>
      </template>
    </Modal>

    <!-- 删除先前案例确认 -->
    <Modal
      :open="!!priorDeleteTarget"
      title="删除先前案例"
      @close="priorDeleteTarget = null"
    >
      <p class="text-sm">
        确认删除 <span class="font-medium">{{ priorDeleteTarget?.title }}</span>？
      </p>
      <p class="mt-1 text-xs text-ink-muted">
        该案例将从先前案例库与检索索引中移除；人工复核记录保留，来源复核会回到可重新生成状态。
      </p>
      <template #footer>
        <button class="btn" @click="priorDeleteTarget = null">返回</button>
        <button class="btn btn-danger" :disabled="priorBusy" @click="doDeletePriorCase">
          {{ priorBusy ? '删除中…' : '确认删除' }}
        </button>
      </template>
    </Modal>
  </div>
</template>
