<template>
  <ToolCallWrapper :tool-name="toolName" :status="status" :meta="meta">
    <div class="space-y-2">
      <div class="text-xs text-[var(--color-blue)]">{{ query }}</div>
      <div v-if="results.length" class="space-y-1.5">
        <div v-for="(r, i) in results" :key="i" class="text-[11px]">
          <a v-if="r.url" :href="r.url" target="_blank" class="text-[var(--color-blue)] hover:underline font-medium">{{ r.title || r.url }}</a>
          <span v-else class="text-[var(--color-text)] font-medium">{{ r.title }}</span>
          <div v-if="r.description" class="text-[var(--color-muted)] mt-0.5 line-clamp-2">{{ r.description }}</div>
        </div>
      </div>
      <div class="text-[10px] text-[var(--color-muted)]">
        {{ results.length }} result{{ results.length !== 1 ? 's' : '' }}
        <span v-if="freshness" class="ml-2">· {{ freshness }}</span>
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
  args?: { query?: string; count?: number; freshness?: string }
  result?: unknown
}>()

const query = computed(() => props.args?.query ?? '—')
const freshness = computed(() => props.args?.freshness)

interface WebResult { title?: string; url?: string; description?: string }

function parseWebResults(r: unknown): WebResult[] {
  if (!r || typeof r !== 'object') return []
  const d = r as Record<string, unknown>
  const results = d.results ?? d
  if (Array.isArray(results)) {
    return results.slice(0, 10).map((item: Record<string, unknown>) => ({
      title: typeof item.title === 'string' ? item.title : undefined,
      url: typeof item.url === 'string' ? item.url : undefined,
      description: typeof item.description === 'string' ? item.description : typeof item.snippet === 'string' ? item.snippet : undefined,
    }))
  }
  return []
}

const results = computed(() => parseWebResults(props.result))
</script>
