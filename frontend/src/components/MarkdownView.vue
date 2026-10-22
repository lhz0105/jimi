<script setup lang="ts">
import { marked } from 'marked'
import { computed } from 'vue'

const props = defineProps<{ source: string }>()

// 报告模板使用 <details> 折叠块（思维链时间线）。为防注入，其余 '<' 一律转义，
// 只放行“裸的” details / summary 标签（带属性的 <details onmouseover=…> 会被转义）。
const ALLOWED_TAG_RE = /<\/?(?:details|summary)(?:\s+open)?\s*>/gi
const TOKEN_PREFIX = '@@ALLOWED_HTML_'
const TOKEN_RE = new RegExp(`${TOKEN_PREFIX}(\\d+)@@`, 'g')

function renderMarkdown(source: string): string {
  const allowed: string[] = []
  let text = source.replace(ALLOWED_TAG_RE, (tag) => {
    allowed.push(tag)
    return `${TOKEN_PREFIX}${allowed.length - 1}@@`
  })
  text = text.replace(/</g, '&lt;')
  text = text.replace(TOKEN_RE, (_, index: string) => allowed[Number(index)] ?? '')
  return marked.parse(text, { async: false, gfm: true }) as string
}

const html = computed(() => renderMarkdown(props.source))
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -- 已转义除 details/summary 外的所有标签 -->
  <article class="md" v-html="html" />
</template>
