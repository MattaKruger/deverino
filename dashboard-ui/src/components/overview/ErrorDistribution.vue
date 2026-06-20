<template>
  <v-chart
    v-if="chartOption"
    :option="chartOption"
    :autoresize="true"
    :init-options="{}"
    class="w-full h-64"
  />
  <div v-else class="flex items-center justify-center h-64 text-[var(--color-muted)] text-sm">
    No errors in last 24h
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import VChart from 'vue-echarts';
import 'echarts';
import { useErrorsStore } from '@/stores/errors';

const CHART_PALETTE = [
  '#689df2',
  '#53c677',
  '#f1576b',
  '#dcaf55',
  '#ae91f0',
  '#4cc6bd',
  '#ef7e47',
  '#e5539a',
  '#88829b',
  '#85b0f5',
];

const store = useErrorsStore();

const chartOption = computed(() => {
  const errors = store.data;
  if (!errors || errors.length === 0) return null;

  const data = errors.map((e, i) => ({
    name: e.skill_name,
    value: e.error_count,
    itemStyle: { color: CHART_PALETTE[i % CHART_PALETTE.length] },
  }));

  return {
    tooltip: {
      trigger: 'item' as const,
      formatter: '{b}: {c} errors ({d}%)' as const,
    },
    legend: {
      orient: 'vertical' as const,
      right: '5%',
      top: 'center',
      textStyle: { color: 'var(--color-muted)', fontSize: 11 },
    },
    series: [
      {
        type: 'pie',
        radius: ['40%', '70%'],
        center: ['40%', '50%'],
        avoidLabelOverlap: false,
        label: { show: false },
        emphasis: {
          label: { show: true, fontSize: 14, fontWeight: 'bold' },
        },
        data,
      },
    ],
  };
});
</script>
