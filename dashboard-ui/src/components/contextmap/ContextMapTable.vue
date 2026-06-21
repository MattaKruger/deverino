<template>
  <div>
    <!-- Loading -->
    <div v-if="loading" class="animate-pulse space-y-2">
      <div class="h-4 bg-[var(--color-border)] rounded w-1/3"></div>
      <div class="h-4 bg-[var(--color-border)] rounded w-2/3"></div>
      <div class="h-4 bg-[var(--color-border)] rounded w-1/2"></div>
    </div>

    <!-- Error -->
    <div v-else-if="error" class="flex items-center gap-2 text-[var(--color-red)] text-sm">
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
          d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
      <span>{{ error }}</span>
    </div>

    <!-- Empty -->
    <div v-else-if="!entries.length" class="text-sm text-[var(--color-muted)] py-4 text-center">
      No entries for this corpus
    </div>

    <!-- Table -->
    <div v-else class="max-h-[70vh] overflow-auto">
      <table class="data-table table-fixed">
        <thead class="sticky top-0 z-10 bg-[var(--color-surface-raised)]">
          <tr>
            <th class="w-[15%]">Key</th>
            <th class="w-[14%]">Section</th>
            <th class="w-[12%]">Type</th>
            <th class="w-[8%]">Priority</th>
            <th class="w-[8%] text-right">Tokens</th>
            <th class="w-[43%]">Summary</th>
          </tr>
        </thead>
        <TransitionGroup name="list" tag="tbody">
          <tr
            v-for="entry in entries"
            :key="entry.entry_id"
          >
            <td class="text-[var(--color-blue)] mono text-xs break-all">{{ entry.key }}</td>
            <td class="text-[var(--color-muted)] break-words">{{ entry.section }}</td>
            <td class="text-[var(--color-muted)] break-words">{{ entry.observation_type }}</td>
            <td>
              <div class="flex items-center gap-1.5">
                <div
                  class="h-1.5 rounded-full shrink-0"
                  :style="{
                    width: Math.max(4, Math.round(entry.priority * 48)) + 'px',
                    backgroundColor: priorityColor(entry.priority),
                  }"
                ></div>
                <span class="text-xs text-[var(--color-muted)] mono">{{ (entry.priority * 100).toFixed(0) }}%</span>
              </div>
            </td>
            <td class="text-right mono">{{ fmtTokens(entry.token_estimate) }}</td>
            <td class="text-[var(--color-muted)] whitespace-pre-wrap break-words">{{ entry.summary }}</td>
          </tr>
        </TransitionGroup>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ContextMapEntrySummary } from '@/types/dashboard';

defineProps<{
  entries: ContextMapEntrySummary[];
  loading: boolean;
  error: string | null;
}>();

function priorityColor(p: number): string {
  if (p >= 0.8) return 'var(--color-red)';
  if (p >= 0.5) return 'var(--color-yellow)';
  return 'var(--color-green)';
}

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return String(n);
}
</script>
