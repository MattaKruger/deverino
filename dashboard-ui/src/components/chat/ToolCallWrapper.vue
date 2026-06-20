<template>
  <div
    class="my-2 rounded-lg border overflow-hidden"
    :class="borderClass"
    role="region"
    :aria-label="`Tool: ${toolName}`"
  >
    <!-- Header -->
    <div class="flex items-center gap-2 px-3 py-2 text-xs font-mono" :class="headerClass">
      <span class="shrink-0">{{ statusIcon }}</span>
      <span class="font-semibold truncate">{{ toolName }}</span>
      <span v-if="meta" class="text-[var(--color-muted)] truncate">{{ meta }}</span>
      <span class="ml-auto shrink-0">
        <StatusBadge :status="statusLabel" />
      </span>
    </div>

    <!-- Body (slot) -->
    <div v-if="status === 'complete' || status === 'error'" class="px-3 pb-3">
      <slot />
    </div>

    <!-- Loading -->
    <div v-else class="px-3 py-2 text-xs text-[var(--color-muted)] animate-pulse">
      Executing...
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import StatusBadge from '@/components/shared/StatusBadge.vue'

const props = defineProps<{
  toolName: string
  status: 'idle' | 'executing' | 'complete' | 'error'
  meta?: string
}>()

const statusIcon = computed(() => {
  switch (props.status) {
    case 'idle': return '○'
    case 'executing': return '◌'
    case 'complete': return '✓'
    case 'error': return '✗'
  }
})

const statusLabel = computed(() => {
  switch (props.status) {
    case 'idle': return 'pending'
    case 'executing': return 'running'
    case 'complete': return 'success'
    case 'error': return 'error'
  }
})

const borderClass = computed(() => {
  switch (props.status) {
    case 'error': return 'border-[var(--color-red)]'
    case 'complete': return 'border-[var(--color-border)]'
    case 'executing': return 'border-[var(--color-yellow)]'
    default: return 'border-[var(--color-border)]'
  }
})

const headerClass = computed(() => {
  switch (props.status) {
    case 'error': return 'bg-[var(--color-red)]/10 text-[var(--color-red)]'
    case 'complete': return 'bg-[var(--color-green)]/10 text-[var(--color-green)]'
    case 'executing': return 'bg-[var(--color-yellow)]/10 text-[var(--color-yellow)]'
    default: return 'bg-[var(--color-cbg)] text-[var(--color-muted)]'
  }
})
</script>
