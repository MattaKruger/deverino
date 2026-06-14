<template>
  <div class="p-6 space-y-6 max-w-screen-2xl mx-auto">
    <div class="flex items-center gap-3">
      <h2 class="text-lg font-semibold text-[var(--text)]">Sub-Agents</h2>
      <HealthIndicator
        :lastFetched="store.lastFetched"
        :error="store.error"
      />
    </div>

    <Panel
      title="Sub-Agents"
      :loading="store.loading && !store.data"
      :isStale="store.isStale"
      :error="store.error"
      :lastUpdated="store.lastFetched"
    >
      <template v-if="store.data && store.data.length > 0">
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-[var(--card-border)] text-left text-xs text-[var(--text-muted)] uppercase tracking-wider">
                <th class="px-3 py-2 font-medium">Persona</th>
                <th class="px-3 py-2 font-medium">Parent Session</th>
                <th class="px-3 py-2 font-medium">Status</th>
                <th class="px-3 py-2 font-medium text-right">Duration</th>
                <th class="px-3 py-2 font-medium">Objective</th>
                <th class="px-3 py-2 font-medium">Summary</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="agent in sortedAgents"
                :key="agent.sub_session_id"
                class="border-b border-[var(--grid-line)] hover:bg-[var(--card-border)] transition-colors"
              >
                <td class="px-3 py-2 font-medium text-[var(--text)] whitespace-nowrap">
                  {{ agent.persona }}
                </td>
                <td class="px-3 py-2 font-mono text-xs text-[var(--text-muted)]">
                  {{ truncateId(agent.parent_session_id) }}
                </td>
                <td class="px-3 py-2">
                  <StatusBadge :status="agent.status" />
                </td>
                <td class="px-3 py-2 text-right font-mono tabular-nums text-[var(--text-muted)] whitespace-nowrap">
                  {{ fmtDuration(agent.duration_s) }}
                </td>
                <td class="px-3 py-2 text-xs text-[var(--text-muted)] max-w-xs truncate">
                  {{ agent.objective || '—' }}
                </td>
                <td class="px-3 py-2 text-xs text-[var(--text-muted)] max-w-xs truncate">
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
