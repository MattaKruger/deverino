<template>
  <div class="p-6 space-y-6 max-w-screen-2xl mx-auto">
    <!-- Page header -->
    <h2 class="text-lg font-semibold text-[var(--text)]">Context Map</h2>

    <!-- Corpses loading / error / empty -->
    <div v-if="store.loading && !store.data" class="animate-pulse space-y-3">
      <div class="h-4 bg-[var(--card-border)] rounded w-1/4"></div>
      <div class="h-10 bg-[var(--card-border)] rounded w-3/4"></div>
    </div>
    <div
      v-else-if="store.error"
      class="flex items-center gap-2 text-[var(--accent-red)] text-sm"
    >
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
          d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
      <span>{{ store.error }}</span>
    </div>
    <div v-else-if="!store.data || store.data.length === 0" class="text-sm text-[var(--text-muted)]">
      No context maps available
    </div>

    <template v-else>
      <!-- Corpus selector pills -->
      <div class="flex flex-wrap gap-2">
        <button
          v-for="cm in store.data"
          :key="cm.corpus_key"
          class="px-4 py-1.5 rounded-md text-sm font-medium border transition-colors"
          :class="selectedCorpus === cm.corpus_key
            ? 'bg-[var(--accent-blue)] border-[var(--accent-blue)] text-white'
            : 'bg-[var(--card-bg)] border-[var(--card-border)] text-[var(--text-muted)] hover:text-[var(--text)] hover:border-[var(--text-muted)]'"
          @click="selectCorpus(cm.corpus_key)"
        >
          {{ cm.corpus_key }}
        </button>
      </div>

      <template v-if="selectedCorpus">
        <!-- Metrics row -->
        <div class="flex flex-row gap-6 flex-wrap">
          <div
            v-for="metric in selectedMetrics"
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

        <!-- Two panels: table + chart -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <!-- Left: Entries table -->
          <div class="bg-[var(--card-bg)] border border-[var(--card-border)] rounded-lg">
            <div
              class="flex items-center gap-2 px-4 py-3 border-b border-[var(--card-border)]"
              :style="{ borderLeft: '3px solid var(--accent-blue)' }"
            >
              <h3 class="text-sm font-semibold text-[var(--text)] uppercase tracking-wider">
                Entries
              </h3>
            </div>
            <div class="p-4">
              <ContextMapTable
                :entries="entries"
                :loading="entriesLoading"
                :error="entriesError"
              />
            </div>
          </div>

          <!-- Right: Budget chart -->
          <div class="bg-[var(--card-bg)] border border-[var(--card-border)] rounded-lg">
            <div
              class="flex items-center gap-2 px-4 py-3 border-b border-[var(--card-border)]"
              :style="{ borderLeft: '3px solid var(--accent-green)' }"
            >
              <h3 class="text-sm font-semibold text-[var(--text)] uppercase tracking-wider">
                Token Budget
              </h3>
            </div>
            <div class="p-4">
              <ContextMapBudgetChart :entries="entries" />
            </div>
          </div>
        </div>
      </template>

      <!-- No selection prompt -->
      <div v-else class="text-sm text-[var(--text-muted)]">
        Select a corpus above to view details
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import { useContextMapsStore } from '@/stores/contextMaps';
import { fetchContextMapEntries } from '@/api/endpoints';
import type { ContextMapEntrySummary, ContextMapHealth } from '@/types/dashboard';
import ContextMapTable from '@/components/contextmap/ContextMapTable.vue';
import ContextMapBudgetChart from '@/components/contextmap/ContextMapBudgetChart.vue';

const store = useContextMapsStore();

const selectedCorpus = ref<string | null>(null);
const entries = ref<ContextMapEntrySummary[]>([]);
const entriesLoading = ref(false);
const entriesError = ref<string | null>(null);

// Auto-select first corpus when data arrives
watch(
  () => store.data,
  (data) => {
    if (data && data.length > 0 && !selectedCorpus.value) {
      selectCorpus(data[0].corpus_key);
    }
  },
  { immediate: true },
);

const selectedHealth = computed<ContextMapHealth | null>(() => {
  if (!store.data || !selectedCorpus.value) return null;
  return store.data.find((cm) => cm.corpus_key === selectedCorpus.value) ?? null;
});

const selectedMetrics = computed(() => {
  const h = selectedHealth.value;
  if (!h) return [];
  return [
    { label: 'Tokens', value: fmtNum(h.token_count), color: 'var(--accent-blue)' },
    { label: 'Version', value: String(h.version), color: 'var(--accent-green)' },
    { label: 'Pending', value: String(h.pending_events), color: h.pending_events > 0 ? 'var(--accent-yellow)' : 'var(--text-muted)' },
    { label: 'Updated', value: fmtTime(h.last_updated), color: 'var(--text-muted)' },
  ];
});

async function selectCorpus(key: string) {
  selectedCorpus.value = key;
  entries.value = [];
  entriesError.value = null;
  entriesLoading.value = true;
  try {
    entries.value = await fetchContextMapEntries(key);
  } catch (e) {
    entriesError.value = String(e);
  } finally {
    entriesLoading.value = false;
  }
}


function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return String(n);
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}
</script>
