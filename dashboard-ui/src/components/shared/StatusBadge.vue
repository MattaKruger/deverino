<template>
  <span
    class="status-badge"
    :class="badgeClass"
  >
    <span class="h-1.5 w-1.5 rounded-full bg-current" />
    {{ status }}
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue';

const props = defineProps<{
  status: string;
}>();

const badgeClass = computed(() => {
  const s = props.status.toLowerCase();
  if (s === 'success' || s === 'completed') {
    return 'text-[var(--color-green)] bg-[var(--color-green)]/10 border-[var(--color-green)]/35';
  }
  if (s === 'failed' || s === 'error') {
    return 'text-[var(--color-red)] bg-[var(--color-red)]/10 border-[var(--color-red)]/35';
  }
  if (s === 'cancelled' || s === 'timeout') {
    return 'text-[var(--color-yellow)] bg-[var(--color-yellow)]/10 border-[var(--color-yellow)]/35';
  }
  if (s === 'running' || s === 'active') {
    return 'text-[var(--color-blue)] bg-[var(--color-blue)]/10 border-[var(--color-blue)]/35';
  }
  // pending, queued, paused, or unknown
  return 'text-[var(--color-muted)] bg-[var(--color-grid)] border-[var(--color-border)]';
});
</script>
