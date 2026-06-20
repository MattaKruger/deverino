<template>
  <ToolCallWrapper :tool-name="toolName" :status="status" :meta="meta">
    <div class="space-y-2 text-xs">
      <div v-if="skillName" class="flex items-center gap-2">
        <span class="px-1.5 py-0.5 rounded bg-[var(--color-blue)]/20 text-[var(--color-blue)] font-mono">{{ skillName }}</span>
        <span v-if="action" class="text-[var(--color-muted)]">{{ action }}</span>
      </div>
      <div v-if="category" class="text-[var(--color-muted)]">category: {{ category }}</div>
      <div v-if="resultText" class="text-[var(--color-text)]">{{ resultText }}</div>
    </div>
  </ToolCallWrapper>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ToolCallWrapper from './ToolCallWrapper.vue'

const props = defineProps<{
  toolName: string
  status: 'idle' | 'executing' | 'complete' | 'error'
  args?: { name?: string; action?: string; category?: string; file_path?: string }
  result?: unknown
}>()

const skillName = computed(() => props.args?.name)
const action = computed(() => props.args?.action)
const category = computed(() => props.args?.category)
const meta = computed(() => props.args?.name ?? props.args?.file_path ?? '')

const resultText = computed(() => {
  const r = props.result
  if (typeof r === 'string') return r.slice(0, 500)
  if (r && typeof r === 'object') {
    const d = r as Record<string, unknown>
    return (d.message as string) ?? (d.content as string)?.slice(0, 500) ?? ''
  }
  return ''
})
</script>
