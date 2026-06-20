<template>
  <div v-if="sessionId" class="card">
    <div class="panel-header">Events</div>
    <div v-if="!store.data" class="text-xs text-[var(--color-muted)]">Loading...</div>
    <div v-else-if="!filtered.length" class="text-xs text-[var(--color-muted)]">No events yet</div>
    <div v-else class="space-y-1">
      <div
        v-for="e in filtered.slice(0, 30)"
        :key="e.event_id"
        class="text-[11px] flex items-start gap-1.5"
      >
        <span class="font-mono text-[var(--color-muted)] shrink-0 w-8 text-right">{{ e.event_id }}</span>
        <span class="truncate text-[var(--color-text)]">{{ e.event_type }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useFirehoseStore } from '@/stores/firehose'

const props = defineProps<{ sessionId: string | null }>()

const store = useFirehoseStore()

const filtered = computed(() =>
  (store.data ?? []).filter(e => e.session_id === props.sessionId),
)
</script>
