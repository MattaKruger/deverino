<template>
  <div class="bg-[var(--card-bg)] border border-[var(--card-border)] rounded-lg">
    <!-- Title bar with accent stripe -->
    <div
      class="flex items-center gap-2 px-4 py-3 border-b border-[var(--card-border)]"
      :style="{ borderLeft: `3px solid var(--accent-blue)` }"
    >
      <h3 class="text-sm font-semibold text-[var(--text)] uppercase tracking-wider">
        {{ title }}
      </h3>
    </div>

    <div class="p-4">
      <!-- Loading skeleton -->
      <div v-if="loading" class="animate-pulse space-y-3">
        <div class="h-4 bg-[var(--card-border)] rounded w-3/4"></div>
        <div class="h-32 bg-[var(--card-border)] rounded"></div>
      </div>

      <!-- Error state -->
      <div
        v-else-if="error"
        class="flex items-center gap-2 text-[var(--accent-red)] text-sm"
      >
        <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <span>{{ error }}</span>
      </div>

      <!-- Content -->
      <slot v-else />
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  title: string;
  loading?: boolean;
  error?: string | null;
}>();
</script>
