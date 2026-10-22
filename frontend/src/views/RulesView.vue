<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import Modal from '@/components/Modal.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { fetchRules, reloadRules, saveRules } from '@/api/admin'
import { errorText } from '@/api/client'
import { useToast } from '@/composables/useToast'

const toast = useToast()

const version = ref('—')
const serverYaml = ref('')
const draft = ref('')
const loading = ref(false)
const saving = ref(false)
const reloadOpen = ref(false)

const dirty = computed(() => draft.value !== serverYaml.value)

async function load(): Promise<void> {
  loading.value = true
  try {
    const data = await fetchRules()
    version.value = data.version
    serverYaml.value = data.yaml
    draft.value = data.yaml
  } catch (error) {
    toast.error(errorText(error))
  } finally {
    loading.value = false
  }
}

async function doSave(): Promise<void> {
  saving.value = true
  try {
    const result = await saveRules(draft.value)
    toast.success(`规则已保存：版本 ${result.version}，共 ${result.rules} 条`)
    await load()
  } catch (error) {
    toast.error(`保存失败：${errorText(error)}`)
  } finally {
    saving.value = false
  }
}

async function doReload(): Promise<void> {
  try {
    const result = await reloadRules()
    toast.success(`已从磁盘重载：版本 ${result.version}`)
    reloadOpen.value = false
    await load()
  } catch (error) {
    toast.error(errorText(error))
  }
}

function revert(): void {
  draft.value = serverYaml.value
  toast.info('已恢复为当前生效版本')
}

onMounted(load)
</script>

<template>
  <div class="flex flex-col gap-3">
    <section class="card flex flex-wrap items-center gap-x-4 gap-y-2 p-3">
      <StatusBadge label="规则引擎" tone="info" :dot="false" />
      <span class="num text-xs text-ink-muted">当前版本 {{ version }}</span>
      <StatusBadge v-if="dirty" label="有未保存修改" tone="warn" />
      <div class="ml-auto flex flex-wrap items-center gap-2">
        <button class="btn px-2 py-1 text-xs" :disabled="loading" @click="load">
          <AppIcon name="refresh" :size="13" /> 重新读取
        </button>
        <button class="btn px-2 py-1 text-xs" :disabled="!dirty" @click="revert">撤销修改</button>
        <button class="btn px-2 py-1 text-xs" @click="reloadOpen = true">
          <AppIcon name="database" :size="13" /> 从磁盘重载
        </button>
        <button class="btn btn-primary px-2 py-1 text-xs" :disabled="!dirty || saving" @click="doSave">
          {{ saving ? '保存中…' : '保存规则' }}
        </button>
      </div>
    </section>

    <section class="card p-3">
      <div class="mb-2 flex flex-wrap items-center gap-2">
        <h2 class="font-mono text-xs font-semibold text-ink-muted">
          规则集 YAML（触发判断：优先级降序短路，命中即决策）
        </h2>
        <span class="text-[11px] text-ink-faint">
          保存时会做 schema 校验；校验失败返回 422 且保留旧版本
        </span>
      </div>
      <textarea
        v-model="draft"
        class="input num h-[62vh] w-full resize-y leading-relaxed"
        spellcheck="false"
        aria-label="规则 YAML 编辑器"
      />
    </section>

    <section class="card p-3">
      <h2 class="mb-2 font-mono text-xs font-semibold text-ink-muted">字段速查</h2>
      <div class="md">
        <ul>
          <li><code>when.any_keywords / all_keywords / none_keywords</code>：关键词命中（OR / AND / 排除）</li>
          <li><code>when.any_regex</code>：正则命中；<code>has_image / image_min</code>：附件条件</li>
          <li><code>when.channel_in</code>：渠道限定（如 seed_post）</li>
          <li><code>action.need_analysis / require_confirm / risk_hint</code>：决策动作；<code>scenario</code>：进入的分析场景</li>
          <li><code>synonyms</code>：把客户口语变体归一为规范词后再匹配（如「退我钱」→「退款」）</li>
        </ul>
      </div>
    </section>

    <Modal :open="reloadOpen" title="从磁盘重载规则" @close="reloadOpen = false">
      <p class="text-sm">将丢弃编辑器内未保存的修改，并重新读取 rules.yaml。</p>
      <template #footer>
        <button class="btn" @click="reloadOpen = false">返回</button>
        <button class="btn btn-danger" @click="doReload">确认重载</button>
      </template>
    </Modal>
  </div>
</template>
