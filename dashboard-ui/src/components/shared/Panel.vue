<template>
  <div
    class="bg-[var(--color-cbg)] border border-[var(--color-border)] rounded-lg"
    role="region"
    :aria-label="title"
    tabindex="0"
  >
    <!-- Title bar with accent stripe -->
    <div
      class="flex items-center justify-between gap-2 px-4 py-3 border-b border-[var(--color-border)]"
      :style="{ borderLeft: `3px solid var(--color-blue)` }"
    >
      <div class="flex items-center gap-2">
        <span v-if="health" class="w-2 h-2 rounded-full shrink-0" :class="healthDotClass" />
        <h3 class="text-sm font-semibold text-[var(--color-text)] uppercase tracking-wider">
          {{ title }}
        </h3>
        <span v-if="isStale" class="text-xs text-[var(--color-yellow)] animate-pulse">
          updating…
        </span>
      </div>
      <span v-if="timeAgoText" class="text-xs text-[var(--color-muted)] shrink-0">{{ timeAgoText }}</span>
    </div>

    <div class="p-4">
      <!-- Loading skeleton — first load only -->
      <div v-if="loading" class="space-y-2">
        <SkeletonRow :widths="['75%', '50%']" />
        <SkeletonRow :widths="['60%', '40%', '30%']" />
        <SkeletonRow :widths="['80%', '35%']" />
      </div>

      <!-- Error state -->
      <div
        v-else-if="error"
        class="flex items-center gap-2 text-[var(--color-red)] text-sm"
      >
        <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <span>{{ error }}</span>
      </div>

      <!-- Content (may be stale but still shown) -->
      <slot v-else />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import SkeletonRow from './SkeletonRow.vue';

const props = defineProps<{
  title: string;
  loading?: boolean;
  isStale?: boolean;
  error?: string | null;
  lastUpdated?: Date | null;
  health?: 'fresh' | 'stale' | 'error' | null;
}>();

const healthDotClass = computed(() => {
  switch (props.health) {
    case 'fresh': return 'bg-[var(--color-green)]';
    case 'stale': return 'bg-[var(--color-yellow)]';
    case 'error': return 'bg-[var(--color-red)]';
    default: return '';
  }
});

function fmtTimeAgo(date: Date): string {
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 0) return 'Just now';
  if (seconds < 60) return `Updated ${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `Updated ${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `Updated ${hours}h ago`;
  return `Updated ${Math.floor(hours / 24)}d ago`;
}

const timeAgoText = computed(() => {
  if (!props.lastUpdated) return null;
  return fmtTimeAgo(props.lastUpdated);
});

// Catch render errors within the panel so one bad chart doesn't crash the page
function onErrorCaptured(err: unknown) {
  console.warn(`[Panel "${props.title}"] render error:`, err)
  return false // prevent propagation
}
</script>
