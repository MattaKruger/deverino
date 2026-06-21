<template>
  <aside class="inspector-panel" role="complementary" aria-label="Chat inspector">
    <div class="inspector-panel__header">
      <span class="text-xs font-semibold uppercase tracking-wider text-[var(--color-blue)]">Inspector</span>
      <button
        class="icon-btn"
        type="button"
        title="Close inspector"
        aria-label="Close inspector"
        @click="emit('close')"
      >
        <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>

    <div class="inspector-panel__body">
      <ToolActivityMini :session-id="chatStore.activeSessionId" />
      <TokenBudgetMini :session-id="chatStore.activeSessionId" />
      <SubAgentTreeMini :session-id="chatStore.activeSessionId" />
      <EventFirehoseMini :session-id="chatStore.activeSessionId" />
    </div>
  </aside>
</template>

<script setup lang="ts">
import { useChatStore } from '@/stores/chat'
import ToolActivityMini from './ToolActivityMini.vue'
import TokenBudgetMini from './TokenBudgetMini.vue'
import SubAgentTreeMini from './SubAgentTreeMini.vue'
import EventFirehoseMini from './EventFirehoseMini.vue'

const chatStore = useChatStore()
const emit = defineEmits<{
  close: []
}>()
</script>
