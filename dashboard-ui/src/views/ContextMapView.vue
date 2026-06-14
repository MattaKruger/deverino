<template>
  <div class="p-6 space-y-6 max-w-screen-2xl mx-auto">
    <!-- Page header with health indicator -->
    <div class="flex items-center gap-3">
      <h2 class="text-lg font-semibold text-[var(--text)]">Context Map</h2>
      <HealthIndicator
        :lastFetched="store.lastFetched"
        :error="store.error"
      />
    </div>

    <!-- Corpus list loading -->
    <div v-if="store.loading && !store.data" class="animate-pulse space-y-3">
      <div class="h-4 bg-[var(--card-border)] rounded w-1/4"></div>
      <div class="h-10 bg-[var(--card-border)] rounded w-3/4"></div>
    </div>

    <!-- Corpus list error -->
    <ErrorDisplay
      v-else-if="store.error"
      :message="store.error"
      :retryable="true"
      @retry="store.fetch()"
    />

    <!-- Corpus list empty -->
    <EmptyState
      v-else-if="!store.data || store.data.length === 0"
      message="No context maps available"
      icon="inbox"
    />

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
        <!-- Metrics bar -->
        <MetricBar :metrics="selectedMetrics" />


        <!-- Full-width entries table -->
        <Panel
          title="Entries"
          :loading="entriesLoading"
          :error="entriesError"
        >
          <ContextMapTable
            :entries="entries"
            :loading="false"
            :error="null"
          />
        </Panel>
      </template>

      <!-- No selection prompt -->
      <EmptyState
        v-else
        message="Select a corpus above to view details"
        icon="search"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import { useContextMapsStore } from '@/stores/contextMaps';
import { fetchContextMapEntries } from '@/api/endpoints';
import type { ContextMapEntrySummary, ContextMapHealth } from '@/types/dashboard';
import ContextMapTable from '@/components/contextmap/ContextMapTable.vue';
import Panel from '@/components/shared/Panel.vue';
import MetricBar from '@/components/shared/MetricBar.vue';
import HealthIndicator from '@/components/shared/HealthIndicator.vue';
import EmptyState from '@/components/shared/EmptyState.vue';
import ErrorDisplay from '@/components/shared/ErrorDisplay.vue';

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
