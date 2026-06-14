<template>
  <div class="flex flex-row gap-6">
    <div
      v-for="metric in metrics"
      :key="metric.label"
      class="flex flex-col items-start"
    >
      <span
        class="text-2xl font-bold font-mono"
        :style="{ color: metric.color || 'var(--accent-blue)' }"
      >
        {{ metric.value }}
      </span>
      <span class="text-xs text-[var(--text-muted)] uppercase tracking-wider">
        {{ metric.label }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  metrics: Array<{ label: string; value: string; color?: string }>;
}>();
</script>
