<template>
  <div v-if="sessionId" class="card">
    <div class="panel-header">Sub-Agents</div>
    <div v-if="!store.data" class="text-xs text-[var(--color-muted)]">Loading...</div>
    <div v-else-if="!filtered.length" class="text-xs text-[var(--color-muted)]">No sub-agents</div>
    <div v-else class="space-y-2">
      <div
        v-for="node in filtered.slice(0, 10)"
        :key="node.sub_session_id"
        class="text-xs"
      >
        <div class="flex items-center gap-1.5">
          <span
            class="w-1.5 h-1.5 rounded-full shrink-0"
            :class="statusDot(node.status)"
          />
          <span class="font-mono text-[var(--color-purple)] truncate">{{ node.persona }}</span>
        </div>
        <div class="text-[var(--color-muted)] truncate mt-0.5 ml-3">{{ node.objective }}</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useSubAgentsStore } from '@/stores/subagents'

const props = defineProps<{ sessionId: string | null }>()

const store = useSubAgentsStore()

const filtered = computed(() =>
  (store.data ?? []).filter(n => n.parent_session_id === props.sessionId),
)

function statusDot(status: string): string {
  switch (status) {
    case 'running': case 'active': return 'bg-[var(--color-green)]'
    case 'failed': case 'error': return 'bg-[var(--color-red)]'
    case 'completed': return 'bg-[var(--color-blue)]'
    default: return 'bg-[var(--color-muted)]'
  }
}
</script>
