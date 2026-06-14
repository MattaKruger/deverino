<template>
  <v-chart
    v-if="chartOption"
    :option="chartOption"
    :autoresize="true"
    :init-options="{ theme: 'dark' }"
    class="w-full h-64"
  />
  <div v-else class="flex items-center justify-center h-64 text-[var(--text-muted)] text-sm">
    No sessions
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import VChart from 'vue-echarts';
import 'echarts';
import { useOverviewStore } from '@/stores/overview';

const STATUS_COLORS: Record<string, string> = {
  success: 'var(--accent-green)',
  completed: 'var(--accent-green)',
  running: 'var(--accent-green)',
  active: 'var(--accent-green)',
  failed: 'var(--accent-red)',
  error: 'var(--accent-red)',
  cancelled: 'var(--accent-red)',
  timeout: 'var(--accent-red)',
  paused: 'var(--accent-yellow)',
  pending: 'var(--accent-yellow)',
  queued: 'var(--accent-yellow)',
};

const store = useOverviewStore();

const chartOption = computed(() => {
  const sessions = store.data?.session_activity;
  if (!sessions || sessions.length === 0) return null;

  // SessionTimeline: each session is a horizontal bar
  const names = sessions.map((s) => (s.session_id || '').slice(0, 12));
  const colors = sessions.map((s) => STATUS_COLORS[s.status.toLowerCase()] || 'var(--accent-blue)');

  // Use a synthetic time range: each bar spans a fixed interval rendered as event_count width
  const values = sessions.map((s) => s.event_count);

  return {
    tooltip: {
      trigger: 'axis' as const,
      axisPointer: { type: 'shadow' as const },
      formatter: (params: any) => {
        const idx = params[0]?.dataIndex;
        if (idx == null) return '';
        const s = sessions[idx];
        return [
          `Session: ${s.session_id}`,
          `Status: ${s.status}`,
          `Events: ${s.event_count}`,
          `Tokens: ${s.total_tokens.toLocaleString()}`,
          `Goal: ${s.goal || '-'}`,
        ].join('<br/>');
      },
    },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'value' as const,
      name: 'events',
      nameTextStyle: { color: 'var(--text-muted)' },
      axisLabel: { color: 'var(--text-muted)' },
      splitLine: { lineStyle: { color: 'var(--grid-line)' } },
    },
    yAxis: {
      type: 'category' as const,
      data: names,
      axisLabel: { color: 'var(--text-muted)', fontSize: 11, fontFamily: 'monospace' },
      axisLine: { lineStyle: { color: 'var(--grid-line)' } },
      inverse: true,
    },
    series: [
      {
        type: 'bar',
        data: values.map((v, i) => ({
          value: v,
          itemStyle: { color: colors[i] },
        })),
      },
    ],
  };
});
</script>
