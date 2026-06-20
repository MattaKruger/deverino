<template>
  <ToolCallWrapper :tool-name="toolName" :status="status" :meta="meta">
    <div class="space-y-2">
      <details class="text-xs" open>
        <summary class="cursor-pointer text-[var(--color-muted)] hover:text-[var(--color-text)]">Arguments</summary>
        <pre class="mt-1 p-2 rounded bg-[var(--color-bg)] text-[var(--color-muted)] font-mono text-[11px] overflow-auto max-h-32">{{ argsStr }}</pre>
      </details>
      <details class="text-xs" open>
        <summary class="cursor-pointer text-[var(--color-muted)] hover:text-[var(--color-text)]">Result</summary>
        <pre class="mt-1 p-2 rounded bg-[var(--color-bg)] text-[var(--color-muted)] font-mono text-[11px] overflow-auto max-h-48">{{ resultStr }}</pre>
      </details>
    </div>
  </ToolCallWrapper>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ToolCallWrapper from './ToolCallWrapper.vue'

const props = defineProps<{
  toolName: string
  status: 'idle' | 'executing' | 'complete' | 'error'
  args?: Record<string, unknown>
  result?: unknown
}>()

const argsStr = computed(() => formatJSON(props.args))
const meta = computed(() => props.args && Object.keys(props.args).length ? `${Object.keys(props.args).length} args` : '')

function formatJSON(v: unknown): string {
  if (v === undefined || v === null) return '—'
  try { return JSON.stringify(v, null, 2) } catch { return String(v) }
}
</script>
