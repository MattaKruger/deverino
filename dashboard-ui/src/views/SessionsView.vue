<template>
  <div class="p-6 space-y-6 max-w-screen-2xl mx-auto">
    <div class="flex items-center gap-3">
      <h2 class="text-lg font-semibold text-[var(--text)]">Sessions</h2>
      <HealthIndicator
        :lastFetched="store.lastFetched"
        :error="store.error"
      />
    </div>

    <Panel
      title="Sessions"
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
                <th class="px-3 py-2 font-medium">Session ID</th>
                <th class="px-3 py-2 font-medium">Status</th>
                <th class="px-3 py-2 font-medium text-right">Events</th>
                <th class="px-3 py-2 font-medium text-right">Tokens</th>
                <th class="px-3 py-2 font-medium text-right">Errors</th>
                <th class="px-3 py-2 font-medium">Last Seen</th>
                <th class="px-3 py-2 font-medium">Goal</th>
              </tr>
            </thead>
            <TransitionGroup name="list" tag="tbody">
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
                <td class="px-3 py-2">
                  <StatusBadge :status="session.status" />
                </td>
                <td class="px-3 py-2 text-right font-mono tabular-nums text-[var(--text)]">
                  {{ fmtNum(session.event_count) }}
                </td>
                <td class="px-3 py-2 text-right font-mono tabular-nums text-[var(--text)]">
                  {{ fmtNum(session.total_tokens) }}
                </td>
                <td class="px-3 py-2 text-right font-mono tabular-nums"
                  :class="session.skill_failures > 0 ? 'text-[var(--accent-red)]' : 'text-[var(--text-muted)]'"
                >
                  {{ session.skill_failures }}
                </td>
                <td class="px-3 py-2 text-xs text-[var(--text-muted)] whitespace-nowrap">
                  {{ fmtTime(session.last_seen) }}
                </td>
                <td class="px-3 py-2 text-xs text-[var(--text-muted)] max-w-xs truncate">
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
