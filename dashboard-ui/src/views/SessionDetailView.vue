<template>
  <div class="p-6 space-y-6 max-w-screen-2xl mx-auto">
    <!-- Back link -->
    <router-link
      to="/sessions"
      class="inline-flex items-center gap-1 text-xs text-[var(--color-muted)] hover:text-[var(--color-text)] transition-colors"
    >
      <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
      </svg>
      Back to Sessions
    </router-link>

    <!-- Loading state -->
    <div v-if="loading" class="animate-pulse space-y-4">
      <div class="h-6 bg-[var(--color-border)] rounded w-1/3"></div>
      <div class="h-4 bg-[var(--color-border)] rounded w-1/4"></div>
      <div class="space-y-2">
        <div v-for="n in 8" :key="n" class="h-12 bg-[var(--color-border)] rounded" />
      </div>
    </div>

    <!-- Error state -->
    <ErrorDisplay
      v-else-if="error"
      :message="error"
      :retryable="true"
      @retry="load"
    />

    <!-- Empty state -->
    <EmptyState
      v-else-if="events && events.length === 0"
      message="No events found for this session"
      icon="inbox"
    />

    <template v-else-if="events">
      <!-- Session header -->
      <div class="flex items-center gap-3 flex-wrap">
        <h2 class="text-lg font-semibold text-[var(--color-text)] font-mono text-sm">
          {{ sessionId }}
        </h2>
        <StatusBadge v-if="sessionStatus" :status="sessionStatus" />
      </div>

      <!-- Metrics bar -->
      <MetricBar :metrics="sessionMetrics" />

      <!-- Event timeline -->
      <Panel title="Event Timeline">
        <div class="divide-y divide-[var(--color-grid)]">
          <div
            v-for="event in events"
            :key="event.event_id"
          >
            <div
              class="flex items-start gap-3 px-3 py-2.5 text-sm cursor-pointer hover:bg-[var(--color-border)] transition-colors"
              :class="expandedId === event.event_id ? 'bg-[var(--color-border)]' : ''"
              :style="{ borderLeft: `3px solid ${eventColor(event.event_type, event.status)}` }"
              role="button"
              tabindex="0"
              :aria-expanded="expandedId === event.event_id"
              :aria-label="`${event.event_type}: ${event.content_preview || event.skill_name || ''}`"
              @click="toggleExpand(event)"
              @keydown.enter.prevent="toggleExpand(event)"
              @keydown.space.prevent="toggleExpand(event)"
            >
              <span class="text-xs text-[var(--color-muted)] font-mono whitespace-nowrap pt-0.5">
                {{ fmtTimestamp(event.created_at) }}
              </span>

              <div class="flex items-center gap-2 min-w-0 flex-1">
                <StatusBadge :status="event.event_type" />
                <span class="text-[var(--color-muted)] truncate">
                  {{ event.content_preview || event.skill_name || event.event_type }}
                </span>
              </div>

              <span
                v-if="event.tokens_used > 0"
                class="text-xs text-[var(--color-muted)] font-mono tabular-nums whitespace-nowrap"
              >
                {{ fmtNum(event.tokens_used) }} tok
              </span>

              <span
                v-if="event.time_delta > 0"
                class="text-xs text-[var(--color-muted)] font-mono tabular-nums whitespace-nowrap"
              >
                {{ event.time_delta.toFixed(1) }}s
              </span>

              <!-- Expand chevron -->
              <span
                class="text-[var(--color-muted)] shrink-0 transition-transform"
                :class="expandedId === event.event_id ? 'rotate-90' : ''"
              >
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
                </svg>
              </span>
            </div>

            <!-- Expanded content -->
            <div
              v-if="expandedId === event.event_id"
              class="px-4 py-3 border-l-[3px] border-[var(--color-blue)] bg-[var(--color-bg)]"
              :style="{ marginLeft: '3px' }"
              @keydown.escape="expandedId = null"
            >
              <!-- Loading skeleton -->
              <div v-if="detailLoading" class="animate-pulse space-y-2">
                <div class="h-4 bg-[var(--color-border)] rounded w-1/4"></div>
                <div class="h-3 bg-[var(--color-border)] rounded w-full"></div>
                <div class="h-3 bg-[var(--color-border)] rounded w-3/4"></div>
              </div>

              <!-- Error -->
              <div v-else-if="detailError" class="text-[var(--color-red)] text-xs">
                {{ detailError }}
              </div>

              <template v-else>
                <!-- Markdown content -->
                <div
                  v-if="detailContent"
                  class="prose prose-sm prose-invert max-w-none text-[var(--color-text)] text-xs leading-relaxed mb-3"
                >
                  <div v-html="detailContent" />
                </div>

                <!-- Raw payload (always shown, collapsed by default) -->
                <details class="mt-2" open>
                  <summary class="text-xs text-[var(--color-muted)] cursor-pointer hover:text-[var(--color-text)] transition-colors select-none">
                    Raw payload
                  </summary>
                  <pre
                    class="mt-2 text-xs text-[var(--color-muted)] bg-[var(--color-border)] rounded p-2 overflow-x-auto max-h-64 font-mono leading-relaxed whitespace-pre-wrap break-all"
                  >{{ detailPayload }}</pre>
                </details>
              </template>
            </div>
          </div>
        </div>
      </Panel>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useRoute } from 'vue-router';
import { marked } from 'marked';
import { fetchSessionEvents, fetchEventDetail } from '@/api/endpoints';
import type { SessionEventRow, EventDetail } from '@/types/dashboard';
import Panel from '@/components/shared/Panel.vue';
import MetricBar from '@/components/shared/MetricBar.vue';
import StatusBadge from '@/components/shared/StatusBadge.vue';
import ErrorDisplay from '@/components/shared/ErrorDisplay.vue';
import EmptyState from '@/components/shared/EmptyState.vue';

const route = useRoute();
const sessionId = computed(() => route.params.id as string);

const events = ref<SessionEventRow[] | null>(null);
const loading = ref(false);
const error = ref<string | null>(null);

// Expand state
const expandedId = ref<number | null>(null);
const detailLoading = ref(false);
const detailError = ref<string | null>(null);
const detailContent = ref<string | null>(null);
const detailPayload = ref<string>('');

async function toggleExpand(event: SessionEventRow) {
  if (expandedId.value === event.event_id) {
    expandedId.value = null;
    detailContent.value = null;
    detailPayload.value = '';
    return;
  }
  expandedId.value = event.event_id;
  detailLoading.value = true;
  detailError.value = null;
  detailContent.value = null;
  detailPayload.value = '';
  try {
    const detail: EventDetail = await fetchEventDetail(event.event_id);
    const raw = detail.content || '';
    if (raw) {
      detailContent.value = await marked.parse(raw);
    }
    detailPayload.value = formatJson(detail.payload);
  } catch (e) {
    detailError.value = String(e);
  } finally {
    detailLoading.value = false;
  }
}
const sessionMetrics = computed(() => {
  if (!events.value || events.value.length === 0) return [];
  const total = events.value.length;
  const tokens = events.value.reduce((sum, e) => sum + (e.tokens_used || 0), 0);
  const errors = events.value.filter((e) =>
    e.status?.toLowerCase().includes('error') || e.status?.toLowerCase().includes('failed')
  ).length;
  const first = events.value[events.value.length - 1];
  const last = events.value[0];
  const duration = first && last
    ? (new Date(last.created_at).getTime() - new Date(first.created_at).getTime()) / 1000
    : 0;
  return [
    { label: 'Events', value: String(total), color: 'var(--color-blue)' },
    { label: 'Tokens', value: fmtNum(tokens), color: 'var(--color-green)' },
    { label: 'Errors', value: String(errors), color: errors > 0 ? 'var(--color-red)' : 'var(--color-muted)' },
    { label: 'Duration', value: fmtDuration(duration), color: 'var(--color-muted)' },
  ];
});

const sessionStatus = computed(() => {
  if (!events.value || events.value.length === 0) return null;
  const lastEvent = events.value[0];
  return lastEvent.status || lastEvent.event_type;
});

async function load() {
  loading.value = true;
  error.value = null;
  try {
    events.value = await fetchSessionEvents(sessionId.value);
  } catch (e) {
    error.value = String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);

const EVENT_COLORS: Record<string, string> = {
  SkillCompleted: 'var(--color-green)',
  SkillCalled: 'var(--color-blue)',
  SkillRequested: 'var(--color-blue)',
  SkillCancelled: 'var(--color-yellow)',
  LLMActionEmitted: 'var(--color-cyan)',
  SubAgentDispatched: 'var(--color-purple)',
  SubAgentCompleted: 'var(--color-purple)',
  SubAgentTaskStarted: 'var(--color-purple)',
  SubAgentTaskCompleted: 'var(--color-purple)',
  StreamPaused: 'var(--color-yellow)',
};

function eventColor(eventType: string, status: string): string {
  for (const [prefix, color] of Object.entries(EVENT_COLORS)) {
    if (eventType.startsWith(prefix)) return color;
  }
  const s = (status || eventType).toLowerCase();
  if (s.includes('failed') || s.includes('error')) return 'var(--color-red)';
  if (s.includes('completed') || s.includes('success')) return 'var(--color-green)';
  return 'var(--color-muted)';
}

function fmtTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return iso;
  }
}

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return String(n);
}

function fmtDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

function formatJson(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}
</script>
