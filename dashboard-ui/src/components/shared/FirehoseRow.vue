<template>
  <div
    class="flex items-center gap-3 px-3 py-2 border-b border-[var(--grid-line)] text-sm"
    :style="{ borderLeft: `3px solid ${rowColor}` }"
  >
    <span class="text-xs text-[var(--text-muted)] font-mono whitespace-nowrap">
      {{ formattedTime }}
    </span>
    <StatusBadge :status="event.event_type" />
    <span class="font-semibold text-[var(--text)] whitespace-nowrap">
      {{ event.event_type }}
    </span>
    <span class="text-[var(--text-muted)] truncate">
      {{ contentPreview }}
    </span>
  </div>
</template>


<script setup lang="ts">
import { computed } from 'vue';
import type { UnifiedEvent } from '@/types/dashboard';
import StatusBadge from './StatusBadge.vue';

const props = defineProps<{
  event: UnifiedEvent;
}>();


const EVENT_COLORS: Record<string, string> = {
  SkillCompleted: 'var(--accent-green)',
  SkillCalled: 'var(--accent-blue)',
  SkillRequested: 'var(--accent-blue)',
  SkillCancelled: 'var(--accent-yellow)',
  LLMActionEmitted: 'var(--accent-cyan)',
  SubAgentDispatched: 'var(--accent-purple)',
  SubAgentCompleted: 'var(--accent-purple)',
  SubAgentTaskStarted: 'var(--accent-purple)',
  SubAgentTaskCompleted: 'var(--accent-purple)',
  StreamPaused: 'var(--accent-yellow)',
  GoalEvaluated: 'var(--accent-green)',
  GatePassed: 'var(--accent-green)',
  GateFailed: 'var(--accent-red)',
  SpecCommitted: 'var(--accent-green)',
};

function eventRowColor(eventType: string): string {
  for (const [prefix, color] of Object.entries(EVENT_COLORS)) {
    if (eventType.startsWith(prefix)) {
      return color;
    }
  }
  if (eventType.toLowerCase().includes('failed') || eventType.toLowerCase().includes('error')) {
    return 'var(--accent-red)';
  }
  return 'var(--text-muted)';
}

const rowColor = computed(() => eventRowColor(props.event.event_type));

const formattedTime = computed(() => {
  try {
    const d = new Date(props.event.timestamp);
    return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return props.event.timestamp;
  }
});

const contentPreview = computed(() => {
  try {
    const detail = JSON.parse(props.event.detail_json);
    if (detail.content_preview) return detail.content_preview;
    if (detail.label) return detail.label;
    if (detail.objective) return detail.objective;
    return JSON.stringify(detail).slice(0, 80);
  } catch {
    return props.event.detail_json?.slice(0, 80) || '';
  }
});
</script>
