<template>
  <v-chart
    v-if="chartOption"
    :option="chartOption"
    :autoresize="true"
    :init-options="{}"
    class="w-full h-64"
  />
  <div v-else class="flex items-center justify-center h-64 text-[var(--color-muted)] text-sm">
    No tool calls recorded
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import VChart from 'vue-echarts';
import 'echarts';
import { useToolsStore } from '@/stores/tools';

const store = useToolsStore();

const chartOption = computed(() => {
  const skills = store.data?.skills;
  if (!skills || skills.length === 0) return null;

  const names = skills.map((s) => s.skill_name);
  const counts = skills.map((s) => s.calls);

  return {
    tooltip: {
      trigger: 'axis' as const,
      axisPointer: { type: 'shadow' as const },
    },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category' as const,
      data: names,
      axisLabel: { color: 'var(--color-muted)', fontSize: 11, rotate: 30 },
      axisLine: { lineStyle: { color: 'var(--color-grid)' } },
    },
    yAxis: {
      type: 'value' as const,
      name: 'calls',
      nameTextStyle: { color: 'var(--color-muted)' },
      axisLabel: { color: 'var(--color-muted)' },
      splitLine: { lineStyle: { color: 'var(--color-grid)' } },
    },
    series: [
      {
        type: 'bar',
        data: counts,
        itemStyle: { color: 'var(--color-blue)' },
        emphasis: { itemStyle: { color: 'var(--color-cyan)' } },
      },
    ],
  };
});
</script>
