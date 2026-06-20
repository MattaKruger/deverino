<template>
  <ToolCallWrapper :tool-name="toolName" :status="status" :meta="meta">
    <div class="space-y-1 text-xs">
      <div v-if="args?.image" class="flex items-center gap-2">
        <span class="text-[var(--color-muted)]">image:</span>
        <span class="font-mono text-[var(--color-text)]">{{ args.image }}</span>
      </div>
      <div v-if="args?.container_name ?? args?.container" class="flex items-center gap-2">
        <span class="text-[var(--color-muted)]">container:</span>
        <span class="font-mono text-[var(--color-text)]">{{ args.container_name ?? args.container }}</span>
      </div>
      <div v-if="spawnResult" class="flex items-center gap-2 text-[10px]" :class="spawnResult.ok ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'">
        <StatusBadge :status="spawnResult.ok ? 'success' : 'error'" />
        <span>{{ spawnResult.label }}</span>
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
  args?: { image?: string; container_name?: string; container?: string }
  result?: unknown
}>()

const meta = computed(() => props.args?.image ?? props.args?.container_name ?? props.args?.container ?? '')

function parseSpawnResult(r: unknown) {
  if (!r || typeof r !== 'object') return { ok: false, label: 'Unknown' }
  const d = r as Record<string, unknown>
  const error = d.error as string | undefined
  if (error) return { ok: false, label: error.slice(0, 80) }
  return { ok: true, label: (d.status as string) ?? (d.message as string) ?? 'Created' }
}

const spawnResult = computed(() => parseSpawnResult(props.result))
</script>
