<template>
  <div class="view-shell view-stack">
    <header class="page-header">
      <div class="page-heading">
        <div class="page-kicker">Delegation graph</div>
        <h1 class="page-title">Sub-Agents</h1>
        <p class="page-subtitle">
          Track delegated work by persona, parent session, lifecycle state, duration, objective, and result summary.
        </p>
      </div>
      <HealthIndicator
        :lastFetched="store.lastFetched"
        :error="store.error"
      />
    </header>

    <Panel
      title="Sub-Agents"
      :loading="store.loading && !store.data"
      :isStale="store.isStale"
      :error="store.error"
      :lastUpdated="store.lastFetched"
    >
      <template v-if="store.data && store.data.length > 0">
        <div class="overflow-x-auto">
          <table class="data-table">
            <thead>
              <tr>
                <th>Persona</th>
                <th>Parent Session</th>
                <th>Status</th>
                <th class="text-right">Duration</th>
                <th>Objective</th>
                <th>Summary</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="agent in sortedAgents"
                :key="agent.sub_session_id"
              >
                <td class="font-medium text-[var(--color-text)] whitespace-nowrap">
                  {{ agent.persona }}
                </td>
                <td class="mono text-xs text-[var(--color-muted)]">
                  {{ truncateId(agent.parent_session_id) }}
                </td>
                <td>
                  <StatusBadge :status="agent.status" />
                </td>
                <td class="text-right mono tabular-nums text-[var(--color-muted)] whitespace-nowrap">
                  {{ fmtDuration(agent.duration_s) }}
                </td>
                <td class="text-xs text-[var(--color-muted)] max-w-xs truncate">
                  {{ agent.objective || '—' }}
                </td>
                <td class="text-xs text-[var(--color-muted)] max-w-xs truncate">
                  {{ agent.summary || '—' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <EmptyState
        v-else-if="store.data"
        message="No sub-agents found"
        icon="code"
      />
    </Panel>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useSubAgentsStore } from '@/stores/subagents';
import Panel from '@/components/shared/Panel.vue';
import StatusBadge from '@/components/shared/StatusBadge.vue';
import HealthIndicator from '@/components/shared/HealthIndicator.vue';
import EmptyState from '@/components/shared/EmptyState.vue';

const store = useSubAgentsStore();

const sortedAgents = computed(() => {
  if (!store.data) return [];
  return [...store.data].sort((a, b) =>
    new Date(b.started_at).getTime() - new Date(a.started_at).getTime()
  );
});

function truncateId(id: string): string {
  return id.length > 12 ? id.slice(0, 12) + '…' : id;
}

function fmtDuration(seconds: number): string {
  if (!seconds || seconds <= 0) return '—';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  return `${(seconds / 3600).toFixed(1)}h`;
}
</script>
