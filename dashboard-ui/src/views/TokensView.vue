<template>
  <div class="p-6 space-y-6 max-w-screen-2xl mx-auto">
    <div class="flex items-center gap-3">
      <h2 class="text-lg font-semibold text-[var(--text)]">Token Usage</h2>
      <HealthIndicator
        :lastFetched="store.lastFetched"
        :error="store.error"
      />
    </div>

    <!-- Top-level metrics -->
    <MetricBar v-if="totals" :metrics="totalMetrics" />

    <!-- Loading state -->
    <div v-if="store.loading && !store.data" class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div class="animate-pulse space-y-3 bg-[var(--card-bg)] border border-[var(--card-border)] rounded-lg p-4">
        <div class="h-4 bg-[var(--card-border)] rounded w-1/3"></div>
        <div v-for="n in 5" :key="n" class="h-6 bg-[var(--card-border)] rounded" />
      </div>
      <div class="animate-pulse space-y-3 bg-[var(--card-bg)] border border-[var(--card-border)] rounded-lg p-4">
        <div class="h-4 bg-[var(--card-border)] rounded w-1/3"></div>
        <div v-for="n in 5" :key="n" class="h-6 bg-[var(--card-border)] rounded" />
      </div>
    </div>

    <!-- Error state -->
    <ErrorDisplay
      v-else-if="store.error"
      :message="store.error"
      :retryable="true"
      @retry="store.fetch()"
    />

    <!-- Content -->
    <div v-else-if="store.data" class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <!-- By Model -->
      <Panel title="By Model" :lastUpdated="store.lastFetched">
        <div v-if="store.data.models.length > 0" class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-[var(--card-border)] text-left text-xs text-[var(--text-muted)] uppercase tracking-wider">
                <th class="px-3 py-2 font-medium">Model</th>
                <th class="px-3 py-2 font-medium text-right">Actions</th>
                <th class="px-3 py-2 font-medium text-right">Sessions</th>
                <th class="px-3 py-2 font-medium text-right">Tokens</th>
                <th class="px-3 py-2 font-medium text-right">Input</th>
                <th class="px-3 py-2 font-medium text-right">Output</th>
                <th class="px-3 py-2 font-medium text-right">Billable</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="model in sortedModels"
                :key="model.model"
                class="border-b border-[var(--grid-line)] hover:bg-[var(--card-border)] transition-colors"
              >
                <td class="px-3 py-2 font-mono text-xs text-[var(--text)]">
                  {{ model.model }}
                </td>
                <td class="px-3 py-2 text-right font-mono tabular-nums text-[var(--text-muted)]">
                  {{ model.actions }}
                </td>
                <td class="px-3 py-2 text-right font-mono tabular-nums text-[var(--text-muted)]">
                  {{ model.sessions }}
                </td>
                <td class="px-3 py-2 text-right font-mono tabular-nums text-[var(--text)]">
                  {{ fmtNum(model.tokens) }}
                </td>
                <td class="px-3 py-2 text-right font-mono tabular-nums text-[var(--text-muted)]">
                  {{ fmtNum(model.input_tokens) }}
                </td>
                <td class="px-3 py-2 text-right font-mono tabular-nums text-[var(--text-muted)]">
                  {{ fmtNum(model.output_tokens) }}
                </td>
                <td class="px-3 py-2 text-right font-mono tabular-nums text-[var(--accent-green)]">
                  {{ fmtNum(model.billable_tokens) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <EmptyState v-else message="No model data" icon="chart" />
      </Panel>

      <!-- By Session -->
      <Panel title="By Session" :lastUpdated="store.lastFetched">
        <div v-if="store.data.sessions.length > 0" class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-[var(--card-border)] text-left text-xs text-[var(--text-muted)] uppercase tracking-wider">
                <th class="px-3 py-2 font-medium">Session</th>
                <th class="px-3 py-2 font-medium">Models</th>
                <th class="px-3 py-2 font-medium text-right">Actions</th>
                <th class="px-3 py-2 font-medium text-right">Tokens</th>
                <th class="px-3 py-2 font-medium text-right">Input</th>
                <th class="px-3 py-2 font-medium text-right">Output</th>
                <th class="px-3 py-2 font-medium text-right">Billable</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="session in sortedSessions"
                :key="session.session_id"
                class="border-b border-[var(--grid-line)] hover:bg-[var(--card-border)] transition-colors"
              >
                <td class="px-3 py-2 font-mono text-xs">
                  <router-link
                    :to="`/sessions/${session.session_id}`"
                    class="text-[var(--accent-blue)] hover:underline"
                  >
                    {{ truncateId(session.session_id) }}
                  </router-link>
                </td>
                <td class="px-3 py-2 text-xs text-[var(--text-muted)] max-w-[120px] truncate">
                  {{ session.models }}
                </td>
                <td class="px-3 py-2 text-right font-mono tabular-nums text-[var(--text-muted)]">
                  {{ session.actions }}
                </td>
                <td class="px-3 py-2 text-right font-mono tabular-nums text-[var(--text)]">
                  {{ fmtNum(session.tokens) }}
                </td>
                <td class="px-3 py-2 text-right font-mono tabular-nums text-[var(--text-muted)]">
                  {{ fmtNum(session.input_tokens) }}
                </td>
                <td class="px-3 py-2 text-right font-mono tabular-nums text-[var(--text-muted)]">
                  {{ fmtNum(session.output_tokens) }}
                </td>
                <td class="px-3 py-2 text-right font-mono tabular-nums text-[var(--accent-green)]">
                  {{ fmtNum(session.billable_tokens) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <EmptyState v-else message="No session data" icon="chart" />
      </Panel>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useTokensStore } from '@/stores/tokens';
import Panel from '@/components/shared/Panel.vue';
import MetricBar from '@/components/shared/MetricBar.vue';
import HealthIndicator from '@/components/shared/HealthIndicator.vue';
import ErrorDisplay from '@/components/shared/ErrorDisplay.vue';
import EmptyState from '@/components/shared/EmptyState.vue';

const store = useTokensStore();

const totals = computed(() => {
  if (!store.data) return null;
  const models = store.data.models;
  if (models.length === 0) return null;
  const totalTokens = models.reduce((s, m) => s + m.tokens, 0);
  const totalInput = models.reduce((s, m) => s + m.input_tokens, 0);
  const totalOutput = models.reduce((s, m) => s + m.output_tokens, 0);
  const totalBillable = models.reduce((s, m) => s + m.billable_tokens, 0);
  return { totalTokens, totalInput, totalOutput, totalBillable, modelCount: models.length };
});

const totalMetrics = computed(() => {
  if (!totals.value) return [];
  return [
    { label: 'Total Tokens', value: fmtNum(totals.value.totalTokens), color: 'var(--accent-blue)' },
    { label: 'Input', value: fmtNum(totals.value.totalInput), color: 'var(--accent-cyan)' },
    { label: 'Output', value: fmtNum(totals.value.totalOutput), color: 'var(--accent-green)' },
    { label: 'Billable', value: fmtNum(totals.value.totalBillable), color: 'var(--accent-purple)' },
    { label: 'Models', value: String(totals.value.modelCount), color: 'var(--text-muted)' },
  ];
});

const sortedModels = computed(() => {
  if (!store.data) return [];
  return [...store.data.models].sort((a, b) => b.tokens - a.tokens);
});

const sortedSessions = computed(() => {
  if (!store.data) return [];
  return [...store.data.sessions].sort((a, b) => b.tokens - a.tokens);
});

function truncateId(id: string): string {
  return id.length > 12 ? id.slice(0, 12) + '…' : id;
}

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return String(n);
}
</script>
