<template>
  <ToolCallWrapper :tool-name="toolName" :status="status" :meta="meta">
    <div class="space-y-2">
      <div class="flex items-center gap-2">
        <span class="text-xs px-1.5 py-0.5 rounded bg-[var(--color-purple)]/20 text-[var(--color-purple)] font-mono">{{ args?.persona ?? 'sub-agent' }}</span>
        <span class="text-xs text-[var(--color-muted)] truncate">{{ args?.objective ?? '' }}</span>
      </div>
      <div v-if="summary" class="text-xs text-[var(--color-text)]">{{ summary }}</div>
      <div v-if="resultStatus" class="flex items-center gap-3 text-[10px]">
        <StatusBadge :status="resultStatus" />
        <span v-if="duration" class="text-[var(--color-muted)]">{{ duration }}</span>
      </div>
    </div>
  </ToolCallWrapper>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ToolCallWrapper from './ToolCallWrapper.vue'
import StatusBadge from '@/components/shared/StatusBadge.vue'

const props = defineProps<{
  toolName: string
  status: 'idle' | 'executing' | 'complete' | 'error'
  args?: { persona?: string; objective?: string }
  result?: unknown
}>()

const meta = computed(() => props.args?.persona ?? '')

function parseDelegateResult(r: unknown) {
  if (!r || typeof r !== 'object') return { summary: '', resultStatus: '', duration: '' }
  const d = r as Record<string, unknown>
  const st = typeof d.status === 'string' ? d.status : ''
  return {
    summary: typeof d.summary === 'string' ? d.summary : typeof d.content === 'string' ? d.content.slice(0, 200) : '',
    resultStatus: st === 'success' ? 'success' : st === 'failed' ? 'error' : st === 'cancelled' ? 'warning' : st,
    duration: typeof d.duration_s === 'number' ? `${d.duration_s.toFixed(1)}s` : '',
  }
}

const { summary, resultStatus, duration } = computed(() => parseDelegateResult(props.result)).value
</script>
