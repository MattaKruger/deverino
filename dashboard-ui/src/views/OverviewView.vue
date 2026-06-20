<template>
  <div class="p-6 space-y-6 max-w-screen-2xl mx-auto">
    <!-- 1. Health Banner -->
    <HealthIndicator :status="healthStatus" :metrics="healthMetrics" />

    <!-- 2. Alert Cards (only when issues exist) -->
    <div v-if="alertCards.length" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      <router-link
        v-for="card in alertCards"
        :key="card.label"
        :to="card.link"
        class="block bg-[var(--color-cbg)] border border-[var(--color-border)] rounded-lg p-4 hover:border-[var(--color-blue)]/50 transition-colors"
      >
        <div class="text-2xl font-mono font-bold" :style="{ color: card.color }">
          {{ card.value }}
        </div>
        <div class="text-xs text-[var(--color-muted)] mt-1 uppercase tracking-wider">
          {{ card.label }}
        </div>
      </router-link>
    </div>

    <!-- 3. Metric Bar -->
    <Panel
      title="Overview"
      :loading="overview.loading"
      :isStale="overview.isStale"
      :error="overview.error"
      :last-updated="overview.lastFetched"
      :health="overviewError ? 'error' : overviewHealth"
    >
      <MetricBar v-if="overview.data" :metrics="summaryMetrics" />
    </Panel>

    <!-- 4. 2x2 Chart Grid -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <Panel
        title="Active Sessions"
        :loading="sessions.loading"
        :isStale="sessions.isStale"
        :error="sessions.error"
        :last-updated="sessions.lastFetched"
        :health="sessionsError ? 'error' : sessionsHealth"
      >
        <SessionTimeline />
      </Panel>

      <Panel
        title="Token Spend Rate"
        :loading="overview.loading"
        :isStale="overview.isStale"
        :error="overview.error"
        :last-updated="overview.lastFetched"
        :health="overviewError ? 'error' : overviewHealth"
      >
        <TokenEconomicsChart />
      </Panel>

      <Panel
        title="Tool Frequency"
        :loading="tools.loading"
        :isStale="tools.isStale"
        :error="tools.error"
        :last-updated="tools.lastFetched"
        :health="toolsError ? 'error' : toolsHealth"
      >
        <ToolFrequencyChart />
      </Panel>

      <Panel
        title="Error Distribution"
        :loading="errors.loading"
        :isStale="errors.isStale"
        :error="errors.error"
        :last-updated="errors.lastFetched"
        :health="errorsError ? 'error' : errorsHealth"
      >
        <ErrorDistribution />
      </Panel>
    </div>

    <!-- 5. Event Firehose -->
    <Panel
      title="Event Firehose"
      :loading="firehose.loading"
      :isStale="firehose.isStale"
      :error="firehose.error"
      :last-updated="firehose.lastFetched"
      :health="firehoseError ? 'error' : firehoseHealth"
    >
      <EventFirehose />
    </Panel>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useOverviewStore } from '@/stores/overview';
import { useSessionsStore } from '@/stores/sessions';
import { useToolsStore } from '@/stores/tools';
import { useTokensStore } from '@/stores/tokens';
import { useErrorsStore } from '@/stores/errors';
import { useFirehoseStore } from '@/stores/firehose';
import { useContextMapsStore } from '@/stores/contextMaps';

import Panel from '@/components/shared/Panel.vue';
import MetricBar from '@/components/shared/MetricBar.vue';
import HealthIndicator from '@/components/shared/HealthIndicator.vue';
import ToolFrequencyChart from '@/components/overview/ToolFrequencyChart.vue';
import TokenEconomicsChart from '@/components/overview/TokenEconomicsChart.vue';
import SessionTimeline from '@/components/overview/SessionTimeline.vue';
import ErrorDistribution from '@/components/overview/ErrorDistribution.vue';
import EventFirehose from '@/components/overview/EventFirehose.vue';

const overview = useOverviewStore();
const sessions = useSessionsStore();
const tools = useToolsStore();
const tokens = useTokensStore();
const errors = useErrorsStore();
const firehose = useFirehoseStore();
const contextMaps = useContextMapsStore();

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return String(n);
}

function isStale(ts: Date | null): boolean {
  if (!ts) return true;
  return Date.now() - ts.getTime() > 30_000;
}

// ── Health status ────────────────────────────────────────────────────────────

const skillFailures = computed(() => overview.data?.summary.skill_failures ?? 0);
const hasErrors = computed(() => !!overview.error || !!errors.error);
const dataStale = computed(() => isStale(overview.lastFetched));

const healthStatus = computed<'good' | 'degraded' | 'bad'>(() => {
  if (hasErrors.value) return 'bad';
  if (skillFailures.value > 0 || dataStale.value) return 'degraded';
  return 'good';
});

const activeCount = computed(() => {
  const acts = overview.data?.session_activity?.filter(
    (s) => s.status === 'running' || s.status === 'active',
  ) ?? [];
  return acts.length;
});

const healthMetrics = computed(() => {
  const s = overview.data?.summary;
  if (!s) {
    return [
      { label: 'Active', value: '0' },
      { label: 'Errors', value: '0' },
      { label: 'Tokens', value: '0' },
    ];
  }
  return [
    { label: 'Active', value: String(activeCount.value) },
    { label: 'Errors', value: String(s.skill_failures) },
    { label: 'Tokens', value: fmtNum(s.total_tokens) },
  ];
});

// ── Alert cards ──────────────────────────────────────────────────────────────

const alertCards = computed(() => {
  const cards: Array<{
    label: string;
    value: string;
    color: string;
    link: string;
  }> = [];

  const failures = overview.data?.recent_failures?.length ?? 0;
  if (failures > 0) {
    cards.push({
      label: 'Recent failures',
      value: String(failures),
      color: 'var(--color-red)',
      link: '/',
    });
  }

  const pending = overview.data?.summary.context_pending ?? 0;
  if (pending > 0) {
    cards.push({
      label: 'Pending context events',
      value: String(pending),
      color: 'var(--color-yellow)',
      link: '/context-map',
    });
  }

  return cards;
});

// ── Panel health flags ───────────────────────────────────────────────────────

const overviewError = computed(() => !!(overview.error));
const sessionsError = computed(() => !!(sessions.error));
const toolsError = computed(() => !!(tools.error));
const errorsError = computed(() => !!(errors.error));
const firehoseError = computed(() => !!(firehose.error));

const overviewHealth = computed(() =>
  dataStale.value ? 'stale' as const : 'fresh' as const);
const sessionsHealth = computed(() =>
  isStale(sessions.lastFetched) ? 'stale' as const : 'fresh' as const);
const toolsHealth = computed(() =>
  isStale(tools.lastFetched) ? 'stale' as const : 'fresh' as const);
const errorsHealth = computed(() =>
  isStale(errors.lastFetched) ? 'stale' as const : 'fresh' as const);
const firehoseHealth = computed(() =>
  isStale(firehose.lastFetched) ? 'stale' as const : 'fresh' as const);

// ── Metric bar  (6 metrics) ──────────────────────────────────────────────────

const summaryMetrics = computed(() => {
  const s = overview.data?.summary;
  if (!s) return [];

  const corporaCount = contextMaps.data?.length ?? 0;

  return [
    { label: 'Sessions', value: String(s.total_sessions), color: 'var(--color-blue)' },
    { label: 'Active', value: String(activeCount.value), color: 'var(--color-green)' },
    { label: 'Tokens', value: fmtNum(s.total_tokens), color: 'var(--color-cyan)' },
    { label: 'Errors', value: String(s.skill_failures), color: 'var(--color-red)' },
    { label: 'Uptime', value: '100%', color: 'var(--color-green)' },
    { label: 'Corpora', value: String(corporaCount), color: 'var(--color-blue)' },
  ];
});
</script>
