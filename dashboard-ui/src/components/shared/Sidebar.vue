<template>
  <aside class="w-56 flex-shrink-0 flex flex-col h-screen bg-[var(--card-bg)] border-r border-[var(--card-border)]">
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
    </nav>
  </aside>
</template>

<script setup lang="ts">
</script>
