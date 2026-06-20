<template>
  <ToolCallWrapper :tool-name="toolName" :status="status" :meta="meta">
    <div class="space-y-2 text-xs">
      <div v-if="args?.memory_key" class="flex items-center gap-2">
        <span class="text-[var(--color-muted)]">key:</span>
        <span class="font-mono text-[var(--color-cyan)]">{{ args.memory_key }}</span>
      </div>
      <pre
        v-if="resultPreview"
        class="p-2 rounded bg-[var(--color-bg)] text-[var(--color-muted)] font-mono text-[11px] overflow-auto max-h-40 whitespace-pre-wrap"
      >{{ resultPreview }}</pre>
      <div v-if="corporaList.length" class="space-y-0.5">
        <div v-for="c in corporaList" :key="c" class="font-mono text-[11px] text-[var(--color-text)]">{{ c }}</div>
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
  args?: { memory_key?: string }
  result?: unknown
}>()

const meta = computed(() => props.args?.memory_key ?? '')

const corporaList = computed(() => {
  const r = props.result
  if (Array.isArray(r)) return r.map(String)
  return []
})

const resultPreview = computed(() => {
  if (corporaList.value.length) return ''
  const r = props.result
  if (r === null || r === undefined) return ''
  if (typeof r === 'string') return r.slice(0, 2000)
  try { return JSON.stringify(r, null, 2).slice(0, 2000) } catch { return '' }
})
</script>
