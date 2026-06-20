<template>
  <div class="flex flex-col gap-2">
    <!-- Control bar -->
    <div class="flex items-center gap-3 px-1">
      <button
        class="px-3 py-1 text-xs font-medium rounded border transition-colors"
        :class="paused
          ? 'bg-[var(--color-yellow)] bg-opacity-20 border-[var(--color-yellow)] text-[var(--color-yellow)]'
          : 'bg-[var(--color-cbg)] border-[var(--color-border)] text-[var(--color-muted)] hover:text-[var(--color-text)] hover:border-[var(--color-muted)]'"
        @click="togglePause"
      >
        {{ paused ? '▶ Resume' : '⏸ Pause' }}
      </button>

      <span
        v-if="paused"
        class="text-xs font-semibold text-[var(--color-yellow)] uppercase tracking-wider"
      >
        PAUSED
      </span>

      <div class="flex-1"></div>

      <select
        v-model="filter"
        class="px-2 py-1 text-xs rounded border border-[var(--color-border)] bg-[var(--color-cbg)] text-[var(--color-text)]"
      >
        <option value="all">All events</option>
        <option value="errors">Errors only</option>
        <option value="skills">Skills only</option>
        <option value="subagents">Sub-agents only</option>
      </select>

      <span class="text-xs text-[var(--color-muted)] font-mono tabular-nums">
        {{ filteredEvents.length }} event{{ filteredEvents.length !== 1 ? 's' : '' }}
      </span>
    </div>

    <!-- Virtual scrollable event log -->
    <div
      v-if="filteredEvents.length > 0"
      v-bind="containerProps"
      class="max-h-96 overflow-y-auto border border-[var(--color-border)] rounded-lg bg-[var(--color-cbg)]"
    >
      <div v-bind="wrapperProps">
        <FirehoseRow
          v-for="{ data: event } in list"
          :key="event.event_id"
          :event="event"
        />
      </div>
    </div>

    <!-- Empty state -->
    <div
      v-else
      class="flex items-center justify-center py-8 text-sm text-[var(--color-muted)] border border-[var(--color-border)] rounded-lg bg-[var(--color-cbg)]"
    >
      No events yet
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue';
import { useVirtualList } from '@vueuse/core';
import { useFirehoseStore } from '@/stores/firehose';
import FirehoseRow from '@/components/shared/FirehoseRow.vue';

const store = useFirehoseStore();
const scrollContainer = ref<HTMLElement | null>(null);
const paused = ref(false);
const filter = ref('all');

const filteredEvents = computed(() => {
  if (!store.data) return [];
  switch (filter.value) {
    case 'errors':
      return store.data.filter((e) =>
        e.event_type.toLowerCase().includes('error') ||
        e.event_type.toLowerCase().includes('failed')
      );
    case 'skills':
      return store.data.filter((e) =>
        e.event_type.toLowerCase().includes('skill')
      );
    case 'subagents':
      return store.data.filter((e) =>
        e.event_type.toLowerCase().includes('subagent') ||
        e.event_type.toLowerCase().includes('sub_agent')
      );
    default:
      return store.data;
  }
});

const { list, containerProps, wrapperProps, scrollTo } = useVirtualList(
  filteredEvents,
  { itemHeight: 40, overscan: 5 },
);

function togglePause() {
  paused.value = !paused.value;
  if (paused.value) {
    store.pause();
  } else {
    store.resume();
  }
}

// Auto-scroll to bottom on new events (only when not paused)
watch(
  () => filteredEvents.value.length,
  () => {
    if (paused.value) return;
    nextTick(() => {
      scrollTo(filteredEvents.value.length - 1);
    });
  },
);
</script>
