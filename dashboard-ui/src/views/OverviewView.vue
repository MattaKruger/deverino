<template>
  <div class="p-6 space-y-6 max-w-screen-2xl mx-auto">
    <!-- Metric Bar -->
    <Panel title="Overview" :loading="overview.loading" :error="overview.error">
      <MetricBar v-if="overview.data" :metrics="summaryMetrics" />
    </Panel>

    <!-- Chart Grid 2x2 -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <!-- Top-left: Tool Frequency -->
      <Panel
        title="Tool Frequency"
        :loading="tools.loading"
        :error="tools.error"
      >
        <ToolFrequencyChart />
      </Panel>

      <!-- Top-right: Token Economics -->
      <Panel
        title="Token Economics"
        :loading="overview.loading"
        :error="overview.error"
      >
        <TokenEconomicsChart />
      </Panel>

      <!-- Bottom-left: Session Timeline -->
      <Panel
        title="Session Timeline"
        :loading="sessions.loading"
        :error="sessions.error"
      >
        <SessionTimeline />
      </Panel>

      <!-- Bottom-right: Error Distribution -->
      <Panel
        title="Error Distribution"
        :loading="errors.loading"
        :error="errors.error"
      >
        <ErrorDistribution />
      </Panel>
    </div>

    <!-- Event Firehose -->
    <Panel
      title="Event Firehose"
      :loading="firehose.loading"
      :error="firehose.error"
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

import Panel from '@/components/shared/Panel.vue';
import MetricBar from '@/components/shared/MetricBar.vue';
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

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return String(n);
}

const summaryMetrics = computed(() => {
  const s = overview.data?.summary;
  if (!s) return [];

  const activeCount = overview.data?.session_activity?.filter(
    (sa) => sa.status === 'running' || sa.status === 'active',
  ).length ?? 0;

  return [
    { label: 'Sessions', value: String(s.total_sessions), color: 'var(--accent-blue)' },
    { label: 'Active', value: String(activeCount), color: 'var(--accent-green)' },
    { label: 'Tokens', value: fmtNum(s.total_tokens), color: 'var(--accent-cyan)' },
    { label: 'Errors', value: String(s.skill_failures), color: 'var(--accent-red)' },
  ];
});
</script>
