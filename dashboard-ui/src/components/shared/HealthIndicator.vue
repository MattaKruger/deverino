<template>
  <!-- Compact inline mode: lastFetched/error provided -->
  <div v-if="lastFetched !== undefined || error !== undefined" class="inline-flex items-center gap-1.5">
    <span class="w-2 h-2 rounded-full shrink-0" :class="dotClass" />
    <span class="text-xs whitespace-nowrap" :class="dotLabelClass">{{ dotLabel }}</span>
  </div>

  <!-- Banner mode: status provided -->
  <div
    v-else-if="status"
    class="flex items-center justify-between px-6 py-4 rounded-lg border text-sm"
    :class="bannerClass"
  >
    <div class="flex items-center gap-3">
      <svg class="w-5 h-5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path v-if="status === 'good'" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
          d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
        <path v-else-if="status === 'degraded'" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
          d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        <path v-else stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
          d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
      <span class="font-semibold">{{ label }}</span>
    </div>
    <div v-if="metrics && metrics.length" class="flex items-center gap-6 text-xs">
      <span v-for="m in metrics" :key="m.label" class="flex items-center gap-1">
        <span class="uppercase tracking-wider opacity-70">{{ m.label }}:</span>
        <span class="font-mono font-semibold">{{ m.value }}</span>
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';

const props = defineProps<{
  // Compact inline mode
  lastFetched?: Date | null;
  error?: string | null;
  // Banner mode
  status?: 'good' | 'degraded' | 'bad';
  metrics?: Array<{ label: string; value: string }>;
}>();

// ── Compact mode computed ──────────────────────────────────────────────────

const freshnessSeconds = computed(() => {
  if (!props.lastFetched) return Infinity;
  return (Date.now() - props.lastFetched.getTime()) / 1000;
});

const dotClass = computed(() => {
  if (props.error) return 'bg-[var(--color-red)]';
  if (props.lastFetched === null || props.lastFetched === undefined) return 'bg-[var(--color-yellow)]';
  const s = freshnessSeconds.value;
  if (s < 15) return 'bg-[var(--color-green)]';
  if (s < 60) return 'bg-[var(--color-yellow)]';
  return 'bg-[var(--color-red)]';
});

const dotLabelClass = computed(() => {
  if (props.error) return 'text-[var(--color-red)]';
  if (props.lastFetched === null || props.lastFetched === undefined) return 'text-[var(--color-yellow)]';
  const s = freshnessSeconds.value;
  if (s < 15) return 'text-[var(--color-green)]';
  if (s < 60) return 'text-[var(--color-yellow)]';
  return 'text-[var(--color-red)]';
});

const dotLabel = computed(() => {
  if (props.error) return 'Error';
  if (props.lastFetched === null || props.lastFetched === undefined) return 'No data';
  const s = freshnessSeconds.value;
  if (s < 15) return 'Live';
  if (s < 60) return 'Stale';
  return 'Disconnected';
});

// ── Banner mode computed ───────────────────────────────────────────────────

const label = computed(() => {
  switch (props.status) {
    case 'good': return 'All systems operational';
    case 'degraded': return 'Degraded performance';
    case 'bad': return 'System issues detected';
    default: return '';
  }
});

const bannerClass = computed(() => {
  switch (props.status) {
    case 'good': return 'bg-[var(--color-green)]/15 border-[var(--color-green)]/30 text-[var(--color-green)]';
    case 'degraded': return 'bg-[var(--color-yellow)]/15 border-[var(--color-yellow)]/30 text-[var(--color-yellow)]';
    case 'bad': return 'bg-[var(--color-red)]/15 border-[var(--color-red)]/30 text-[var(--color-red)]';
    default: return '';
  }
});
</script>
