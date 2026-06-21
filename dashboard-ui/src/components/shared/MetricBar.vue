<template>
  <div class="stat-grid">
    <div
      v-for="metric in metrics"
      :key="metric.label"
      class="stat-card"
    >
      <span
        class="metric-value mono"
        :style="{ color: metric.color || 'var(--color-blue)' }"
      >
        {{ metric.value }}
      </span>
      <span class="metric-label">
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
