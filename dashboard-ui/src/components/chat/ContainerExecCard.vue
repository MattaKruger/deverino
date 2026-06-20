<template>
  <ToolCallWrapper :tool-name="toolName" :status="status" :meta="meta">
    <div class="space-y-2">
      <div class="text-xs font-mono text-[var(--color-cyan)]">{{ args?.command ?? args?.code ?? '—' }}</div>
      <div v-if="container" class="text-[10px] text-[var(--color-muted)]">container: {{ container }}</div>
      <pre
        v-if="output"
        class="p-2 rounded bg-[var(--color-bg)] font-mono text-[11px] overflow-auto max-h-48"
        :class="exitOk ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'"
      >{{ output }}</pre>
      <div v-if="footer" class="flex items-center gap-3 text-[10px]" :class="exitOk ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'">
        <span>{{ footer }}</span>
        <span v-if="duration" class="text-[var(--color-muted)]">{{ duration }}</span>
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
  args?: { command?: string; code?: string; container?: string }
  result?: unknown
}>()

const container = computed(() => props.args?.container)
const meta = computed(() => props.args?.container ? `on ${props.args.container}` : '')

function parseExecResult(r: unknown) {
  if (!r || typeof r !== 'object') return { output: '', exitOk: false, footer: '', duration: '' }
  const d = r as Record<string, unknown>
  const stdout = typeof d.stdout === 'string' ? d.stdout : ''
  const stderr = typeof d.stderr === 'string' ? d.stderr : ''
  const exitCode = d.exit_code ?? 0
  const content = typeof d.content === 'string' ? d.content : ''
  const combined = content || [stdout, stderr].filter(Boolean).join('\n')
  return {
    output: combined.slice(0, 4000),
    exitOk: exitCode === 0,
    footer: `exit ${exitCode}${d.timed_out ? ' · timed out' : ''}`,
    duration: typeof d.duration_s === 'number' ? `${d.duration_s.toFixed(1)}s` : '',
  }
}

const { output, exitOk, footer, duration } = computed(() => parseExecResult(props.result)).value
</script>
