<template>
  <div class="panel" role="region" :aria-label="title || 'Dashboard panel'" tabindex="0">
    <div v-if="title || health || timeAgoText || isStale" class="panel__header">
      <div class="panel__title-group">
        <span v-if="health" class="health-dot" :class="healthDotClass" />
        <h3 v-if="title" class="panel__title">
          {{ title }}
        </h3>
        <span v-if="isStale" class="panel__meta text-[var(--color-yellow)]">
          updating…
        </span>
      </div>
      <span v-if="timeAgoText" class="panel__meta">{{ timeAgoText }}</span>
    </div>

    <div class="panel__body">
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
    case 'fresh': return 'text-[var(--color-green)] bg-[var(--color-green)]';
    case 'stale': return 'text-[var(--color-yellow)] bg-[var(--color-yellow)]';
    case 'error': return 'text-[var(--color-red)] bg-[var(--color-red)]';
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
