<template>
  <div class="view-shell view-stack">
    <header class="page-header">
      <div class="page-heading">
        <div class="page-kicker">Execution ledger</div>
        <h1 class="page-title">Sessions</h1>
        <p class="page-subtitle">
          Inspect active and historical agent runs with event volume, token cost, failures, and goals.
        </p>
      </div>
      <HealthIndicator
        :lastFetched="store.lastFetched"
        :error="store.error"
      />
    </header>

    <Panel
      title="Sessions"
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
                <th>Session ID</th>
                <th>Status</th>
                <th class="text-right">Events</th>
                <th class="text-right">Tokens</th>
                <th class="text-right">Errors</th>
                <th>Last Seen</th>
                <th>Goal</th>
              </tr>
            </thead>
            <TransitionGroup name="list" tag="tbody">
              <tr
                v-for="session in sortedSessions"
                :key="session.session_id"
              >
                <td class="mono text-xs">
                  <router-link
                    :to="`/sessions/${session.session_id}`"
                    class="text-[var(--color-blue)] hover:underline"
                  >
                    {{ truncateId(session.session_id) }}
                  </router-link>
                </td>
                <td>
                  <StatusBadge :status="session.status" />
                </td>
                <td class="text-right mono tabular-nums text-[var(--color-text)]">
                  {{ fmtNum(session.event_count) }}
                </td>
                <td class="text-right mono tabular-nums text-[var(--color-text)]">
                  {{ fmtNum(session.total_tokens) }}
                </td>
                <td class="text-right mono tabular-nums"
                  :class="session.skill_failures > 0 ? 'text-[var(--color-red)]' : 'text-[var(--color-muted)]'"
                >
                  {{ session.skill_failures }}
                </td>
                <td class="text-xs text-[var(--color-muted)] whitespace-nowrap">
                  {{ fmtTime(session.last_seen) }}
                </td>
                <td class="text-xs text-[var(--color-muted)] max-w-xs truncate">
                  {{ session.goal || '—' }}
                </td>
              </tr>
            </TransitionGroup>
          </table>
        </div>
      </template>

      <EmptyState
        v-else-if="store.data"
        message="No sessions found"
        icon="inbox"
      />
    </Panel>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useSessionsStore } from '@/stores/sessions';
import Panel from '@/components/shared/Panel.vue';
import StatusBadge from '@/components/shared/StatusBadge.vue';
import HealthIndicator from '@/components/shared/HealthIndicator.vue';
import EmptyState from '@/components/shared/EmptyState.vue';

const store = useSessionsStore();

const sortedSessions = computed(() => {
  if (!store.data) return [];
  return [...store.data].sort((a, b) =>
    new Date(b.last_seen).getTime() - new Date(a.last_seen).getTime()
  );
});

function truncateId(id: string): string {
  return id.length > 12 ? id.slice(0, 12) + '…' : id;
}

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return String(n);
}

function fmtTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch {
    return iso;
  }
}
</script>
