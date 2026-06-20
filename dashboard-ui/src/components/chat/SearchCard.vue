<template>
  <ToolCallWrapper :tool-name="toolName" :status="status" :meta="meta">
    <div class="space-y-2">
      <div class="text-xs font-mono text-[var(--color-yellow)]">{{ queryDisplay }}</div>
      <div v-if="resultList.length" class="space-y-1">
        <div v-for="(item, i) in resultList" :key="i" class="text-[11px]">
          <span class="text-[var(--color-muted)] font-mono">{{ item.path ?? item.title }}</span>
          <span v-if="item.line" class="text-[var(--color-muted)] ml-1">:{{ item.line }}</span>
          <div v-if="item.preview" class="text-[var(--color-text)] mt-0.5 opacity-70">{{ item.preview }}</div>
        </div>
      </div>
      <div class="text-[10px] text-[var(--color-muted)]">{{ resultList.length }} result{{ resultList.length !== 1 ? 's' : '' }}</div>
    </div>
  </ToolCallWrapper>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ToolCallWrapper from './ToolCallWrapper.vue'

const props = defineProps<{
  toolName: string
  status: 'idle' | 'executing' | 'complete' | 'error'
  args?: { query?: string; pattern?: string; target?: string; path?: string }
  result?: unknown
}>()

const queryDisplay = computed(() => props.args?.query ?? props.args?.pattern ?? '—')
const meta = computed(() => {
  const a = props.args
  if (!a) return ''
  const parts = []
  if (a.path) parts.push(a.path as string)
  if (a.target) parts.push(a.target as string)
  return parts.join(' · ')
})

interface SearchItem { path?: string; title?: string; line?: number; preview?: string }

function parseSearchResult(r: unknown): SearchItem[] {
  if (!r || typeof r !== 'object') return []
  const d = r as Record<string, unknown>
  const results = d.results ?? d.matches ?? d
  if (Array.isArray(results)) {
    return results.slice(0, 20).map((item: Record<string, unknown>) => ({
      path: typeof item.file_path === 'string' ? item.file_path : typeof item.path === 'string' ? item.path : typeof item.url === 'string' ? item.url : undefined,
      title: typeof item.title === 'string' ? item.title : undefined,
      line: typeof item.line === 'number' ? item.line : typeof item.start_line === 'number' ? item.start_line : undefined,
      preview: typeof item.preview === 'string' ? item.preview?.slice(0, 120) : typeof item.snippet === 'string' ? item.snippet?.slice(0, 120) : undefined,
    }))
  }
  return []
}

const resultList = computed(() => parseSearchResult(props.result))
</script>
