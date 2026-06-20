<template>
  <aside class="h-full flex flex-col bg-[var(--color-cbg)] border-l border-[var(--color-border)] overflow-y-auto" role="complementary" aria-label="Chat inspector">
    <div class="px-3 py-3 border-b border-[var(--color-border)]">
      <span class="text-xs font-semibold uppercase tracking-wider text-[var(--color-blue)]">Inspector</span>
    </div>

    <div class="flex-1 space-y-3 p-3">
      <TokenBudgetMini :session-id="chatStore.activeSessionId" />
      <SubAgentTreeMini :session-id="chatStore.activeSessionId" />
      <EventFirehoseMini :session-id="chatStore.activeSessionId" />
    </div>
  </aside>
</template>

<script setup lang="ts">
import { useChatStore } from '@/stores/chat'
import TokenBudgetMini from './TokenBudgetMini.vue'
import SubAgentTreeMini from './SubAgentTreeMini.vue'
import EventFirehoseMini from './EventFirehoseMini.vue'

const chatStore = useChatStore()
</script>
