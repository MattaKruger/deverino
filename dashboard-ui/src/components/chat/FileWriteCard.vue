<template>
  <ToolCallWrapper :tool-name="toolName" :status="status" :meta="meta">
    <div class="space-y-2">
      <div class="text-xs font-mono text-[var(--color-muted)]">{{ pathDisplay }}</div>
      <pre
        v-if="diffPreview"
        class="p-2 rounded bg-[var(--color-bg)] font-mono text-[11px] overflow-auto max-h-48 whitespace-pre-wrap"
      >{{ diffPreview }}</pre>
      <pre
        v-else-if="contentPreview"
        class="p-2 rounded bg-[var(--color-bg)] font-mono text-[11px] overflow-auto max-h-32 whitespace-pre-wrap text-[var(--color-muted)]"
      >{{ contentPreview }}</pre>
      <div v-if="writeResult" class="flex items-center gap-3 text-[10px]" :class="writeResult.ok ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'">
        <span>{{ writeResult.label }}</span>
        <span v-if="writeResult.size" class="text-[var(--color-muted)]">{{ writeResult.size }}</span>
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
  args?: { path?: string; content?: string; diff?: string; old_string?: string; new_string?: string }
  result?: unknown
}>()

const pathDisplay = computed(() => props.args?.path ?? '—')
const meta = computed(() => {
  const fn = String(props.args?.path ?? '').split('/').pop()
  return fn || undefined
})

const diffPreview = computed(() => {
  const d = props.args?.diff
  if (typeof d === 'string' && d.length > 0) return d.slice(0, 2000)
  if (props.args?.old_string && props.args?.new_string) {
    return `- ${props.args.old_string.slice(0, 500)}\n+ ${props.args.new_string.slice(0, 500)}`
  }
  return ''
})

const contentPreview = computed(() => {
  const c = props.args?.content
  return typeof c === 'string' ? c.slice(0, 1000) : ''
})

function parseWriteResult(r: unknown) {
  if (!r || typeof r !== 'object') return { ok: false, label: 'Unknown', size: '' }
  const d = r as Record<string, unknown>
  const error = d.error as string | undefined
  if (error) return { ok: false, label: error.slice(0, 80), size: '' }
  return {
    ok: true,
    label: d.message as string ?? 'Written',
    size: typeof d.file_size === 'number' ? `${(d.file_size / 1024).toFixed(1)}KB` : typeof d.file_size === 'string' ? d.file_size : '',
  }
}

const writeResult = computed(() => parseWriteResult(props.result))
</script>
