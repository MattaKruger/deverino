<template>
  <aside class="w-56 flex-shrink-0 flex flex-col h-screen bg-[var(--card-bg)] border-r border-[var(--card-border)]" role="navigation" aria-label="Main navigation">
    <!-- Title -->
    <div class="px-4 py-5">
      <span class="text-xs font-bold uppercase tracking-widest text-[var(--accent-blue)]">Deverino</span>
    </div>

    <!-- Nav links -->
    <nav class="flex flex-col gap-0.5 px-2">
      <router-link
        to="/"
        class="flex items-center gap-2 px-3 py-2 rounded text-sm text-[var(--text-muted)] hover:bg-[var(--card-border)] transition-colors"
        active-class="bg-[var(--card-border)] text-[var(--accent-blue)]"
        exact-active-class="bg-[var(--card-border)] text-[var(--accent-blue)]"
      >
        <!-- squares-2x2 icon -->
        <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
            d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
        </svg>
        Overview
      </router-link>

      <router-link
        to="/context-map"
        class="flex items-center gap-2 px-3 py-2 rounded text-sm text-[var(--text-muted)] hover:bg-[var(--card-border)] transition-colors"
        active-class="bg-[var(--card-border)] text-[var(--accent-blue)]"
        exact-active-class="bg-[var(--card-border)] text-[var(--accent-blue)]"
      >
        <!-- map icon -->
        <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
            d="M9 6.75V15m6-6v8.25m.503 3.498l4.875-2.437c.381-.19.622-.58.622-1.006V4.82c0-.836-.88-1.38-1.628-1.006l-3.869 1.934c-.317.159-.69.159-1.006 0L9.503 3.252a1.125 1.125 0 00-1.006 0L3.622 5.689C3.24 5.88 3 6.27 3 6.695V19.18c0 .836.88 1.38 1.628 1.006l3.869-1.934c.317-.159.69-.159 1.006 0l4.994 2.497c.317.158.69.158 1.006 0z" />
        </svg>
        Context Map
      </router-link>

      <router-link
        to="/sessions"
        class="flex items-center gap-2 px-3 py-2 rounded text-sm text-[var(--text-muted)] hover:bg-[var(--card-border)] transition-colors"
        active-class="bg-[var(--card-border)] text-[var(--accent-blue)]"
        exact-active-class="bg-[var(--card-border)] text-[var(--accent-blue)]"
      >
        <!-- users icon -->
        <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
            d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
        </svg>
        Sessions
      </router-link>

      <router-link
        to="/sub-agents"
        class="flex items-center gap-2 px-3 py-2 rounded text-sm text-[var(--text-muted)] hover:bg-[var(--card-border)] transition-colors"
        active-class="bg-[var(--card-border)] text-[var(--accent-blue)]"
        exact-active-class="bg-[var(--card-border)] text-[var(--accent-blue)]"
      >
        <!-- network/share icon -->
        <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
            d="M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m13.35-.622l1.757-1.757a4.5 4.5 0 00-6.364-6.364l-4.5 4.5a4.5 4.5 0 001.242 7.244" />
        </svg>
        Sub-Agents
      </router-link>

      <router-link
        to="/tokens"
        class="flex items-center gap-2 px-3 py-2 rounded text-sm text-[var(--text-muted)] hover:bg-[var(--card-border)] transition-colors"
        active-class="bg-[var(--card-border)] text-[var(--accent-blue)]"
        exact-active-class="bg-[var(--card-border)] text-[var(--accent-blue)]"
      >
        <!-- currency/coin icon -->
        <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
            d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125v-3.75" />
        </svg>
        Tokens
      </router-link>
    </nav>

    <!-- Health footer -->
    <div class="mt-auto border-t border-[var(--card-border)] px-4 py-3">
      <HealthIndicator
        :last-fetched="overviewStore.lastFetched"
        :error="overviewStore.error"
      />
    </div>
  </aside>
</template>
<script setup lang="ts">
import HealthIndicator from '@/components/shared/HealthIndicator.vue';
import { useOverviewStore } from '@/stores/overview';

const overviewStore = useOverviewStore();
</script>
