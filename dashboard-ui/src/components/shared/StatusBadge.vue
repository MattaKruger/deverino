<template>
  <span
    class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
    :class="badgeClass"
  >
    {{ status }}
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue';

const props = defineProps<{
  status: string;
}>();

const badgeClass = computed(() => {
  const s = props.status.toLowerCase();
  if (s === 'success' || s === 'completed') {
    return 'bg-green-900/40 text-green-400 border border-green-800';
  }
  if (s === 'failed' || s === 'error') {
    return 'bg-red-900/40 text-red-400 border border-red-800';
  }
  if (s === 'cancelled' || s === 'timeout') {
    return 'bg-yellow-900/40 text-yellow-400 border border-yellow-800';
  }
  if (s === 'running' || s === 'active') {
    return 'bg-blue-900/40 text-blue-400 border border-blue-800';
  }
  // pending, queued, paused, or unknown
  return 'bg-gray-800 text-gray-400 border border-gray-700';
});
</script>
