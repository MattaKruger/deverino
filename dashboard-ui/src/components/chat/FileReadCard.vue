<template>
  <ToolCallWrapper :tool-name="toolName" :status="status" :meta="meta">
    <div class="space-y-2">
      <div class="text-xs text-[var(--color-muted)] font-mono">{{ args?.path ?? '—' }}</div>
      <pre
        v-if="previewText"
        class="p-2 rounded bg-[var(--color-bg)] text-[var(--color-text)] font-mono text-[11px] overflow-auto max-h-64 whitespace-pre-wrap"
      >{{ previewText }}</pre>
      <div v-if="fileStats" class="flex items-center gap-3 text-[10px] text-[var(--color-muted)]">
        <span v-if="fileStats.size">✓ {{ fileStats.size }}</span>
        <span v-if="fileStats.lines">lines {{ fileStats.lines }}</span>
        <span v-if="fileStats.truncated" class="text-[var(--color-yellow)]">truncated</span>
      </div>
    </div>
  </ToolCallWrapper>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ToolCallWrapper from './ToolCallWrapper.vue'

const props = defineProps<{
  toolName: string
  status: 'idle' | 'executing' | 'complete' | 'error'
  args?: { path?: string; offset?: number; limit?: number; start_line?: number; end_line?: number }
  result?: unknown
}>()

const meta = computed(() => {
  const p = props.args
  if (!p?.path) return ''
  const fn = String(p.path).split('/').pop()
  const range = p.start_line && p.end_line ? `:${p.start_line}-${p.end_line}` : ''
  return `${fn}${range}`
})

function parseResult(r: unknown): { text?: string; stats?: { size?: string; lines?: string; truncated?: boolean } } {
  if (!r || typeof r !== 'object') return {}
  const d = r as Record<string, unknown>
  return {
    text: typeof d.content === 'string' ? d.content : undefined,
    stats: {
      size: typeof d.file_size === 'string' ? d.file_size : typeof d.file_size === 'number' ? `${d.file_size}B` : undefined,
      lines: typeof d.total_lines === 'number' ? String(d.total_lines) : typeof d.lines_shown === 'string' ? d.lines_shown : undefined,
      truncated: !!d.truncated,
    },
  }
}

const parsed = computed(() => parseResult(props.result))
const previewText = computed(() => parsed.value.text)
const fileStats = computed(() => parsed.value.stats)
</script>
