<template>
  <div class="flex flex-col">
    <!-- Scrollable event log -->
    <div
      v-if="store.data && store.data.length > 0"
      ref="scrollContainer"
      class="max-h-96 overflow-y-auto"
    >
      <FirehoseRow
        v-for="event in store.data"
        :key="event.event_id"
        :event="event"
      />
    </div>

    <!-- Empty state -->
    <div
      v-else
      class="flex items-center justify-center h-32 text-[var(--text-muted)] text-sm"
    >
      No recent events
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue';
import { useFirehoseStore } from '@/stores/firehose';
import FirehoseRow from '@/components/shared/FirehoseRow.vue';

const store = useFirehoseStore();
const scrollContainer = ref<HTMLElement | null>(null);

// Auto-scroll to bottom on new events
watch(
  () => store.data?.length,
  () => {
    nextTick(() => {
      if (scrollContainer.value) {
        scrollContainer.value.scrollTop = scrollContainer.value.scrollHeight;
      }
    });
  },
);
</script>
