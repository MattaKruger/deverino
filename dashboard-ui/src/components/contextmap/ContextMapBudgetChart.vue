<template>
  <div>
    <v-chart
      v-if="chartOption"
      :option="chartOption"
      :autoresize="true"
      :init-options="{ theme: 'dark' }"
      class="w-full h-80"
    />
    <div v-else class="flex items-center justify-center h-80 text-[var(--text-muted)] text-sm">
      No entries
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import VChart from 'vue-echarts';
import 'echarts';
import type { ContextMapEntrySummary } from '@/types/dashboard';

const props = defineProps<{
  entries: ContextMapEntrySummary[];
}>();

const SECTION_COLORS = [
  'var(--accent-blue)',
  'var(--accent-green)',
  'var(--accent-cyan)',
  'var(--accent-purple)',
  'var(--accent-orange)',
  'var(--accent-yellow)',
];

const chartOption = computed(() => {
  if (!props.entries.length) return null;

  // Build a color map for sections
  const sectionSet = new Set(props.entries.map((e) => e.section));
  const sectionColors: Record<string, string> = {};
  Array.from(sectionSet).forEach((s, i) => {
    sectionColors[s] = SECTION_COLORS[i % SECTION_COLORS.length];
  });

  return {
    tooltip: {
      formatter: (params: any) => {
        if (!params.data) return '';
        const d = params.data;
        return [
          `<strong>${d.name}</strong>`,
          `Section: ${d.section}`,
          `Tokens: ${d.token_estimate?.toLocaleString() ?? '?'}`,
          `Priority: ${d.priority != null ? (d.priority * 100).toFixed(0) + '%' : '?'}`,
        ].join('<br>');
      },
    },
    series: [
      {
        type: 'treemap',
        roam: false,
        nodeClick: false,
        breadcrumb: { show: false },
        label: {
          show: true,
          formatter: '{b}',
          fontSize: 11,
          color: '#c9d1d9',
        },
        upperLabel: {
          show: true,
          height: 20,
          fontSize: 11,
          color: '#8b949e',
        },
        itemStyle: {
          borderColor: 'var(--card-bg)',
          borderWidth: 2,
        },
        levels: [
          {
            itemStyle: {
              borderWidth: 0,
              gapWidth: 2,
            },
          },
          {
            colorSaturation: [0.35, 0.5],
            itemStyle: {
              borderColorSaturation: 0.6,
              gapWidth: 1,
            },
          },
        ],
        data: props.entries.map((e) => ({
          name: e.key,
          value: Math.max(1, e.token_estimate),
          section: e.section,
          token_estimate: e.token_estimate,
          priority: e.priority,
          itemStyle: {
            color: sectionColors[e.section] || 'var(--accent-blue)',
          },
        })),
      },
    ],
  };
});
</script>
