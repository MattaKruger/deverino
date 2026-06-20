<template>
  <v-chart
    v-if="chartOption"
    :option="chartOption"
    :autoresize="true"
    :init-options="{}"
    class="w-full h-64"
  />
  <div v-else class="flex items-center justify-center h-64 text-[var(--color-muted)] text-sm">
    No token data
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import VChart from 'vue-echarts';
import 'echarts';
import { useOverviewStore } from '@/stores/overview';

const store = useOverviewStore();

const chartOption = computed(() => {
  const buckets = store.data?.token_buckets;
  if (!buckets || buckets.length === 0) return null;

  const labels = buckets.map((b) => b.bucket);
  const input = buckets.map((b) => b.input_tokens);
  const output = buckets.map((b) => b.output_tokens);

  return {
    tooltip: {
      trigger: 'axis' as const,
    },
    legend: {
      data: ['Input', 'Output'],
      textStyle: { color: 'var(--color-muted)' },
      top: 0,
    },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '12%', containLabel: true },
    xAxis: {
      type: 'category' as const,
      boundaryGap: false,
      data: labels,
      axisLabel: { color: 'var(--color-muted)', fontSize: 11 },
      axisLine: { lineStyle: { color: 'var(--color-grid)' } },
    },
    yAxis: {
      type: 'value' as const,
      name: 'tokens',
      nameTextStyle: { color: 'var(--color-muted)' },
      axisLabel: { color: 'var(--color-muted)' },
      splitLine: { lineStyle: { color: 'var(--color-grid)' } },
    },
    series: [
      {
        name: 'Input',
        type: 'line',
        areaStyle: {},
        data: input,
        itemStyle: { color: 'var(--color-green)' },
        lineStyle: { color: 'var(--color-green)', width: 2 },
        smooth: true,
      },
      {
        name: 'Output',
        type: 'line',
        areaStyle: {},
        data: output,
        itemStyle: { color: 'var(--color-cyan)' },
        lineStyle: { color: 'var(--color-cyan)', width: 2 },
        smooth: true,
      },
    ],
  };
});
</script>
