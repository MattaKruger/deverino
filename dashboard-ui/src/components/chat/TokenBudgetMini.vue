<template>
  <div v-if="sessionId" class="card">
    <div class="panel-header">Token Budget</div>
    <div v-if="!tokensStore.data" class="text-xs text-[var(--color-muted)]">Loading...</div>
    <div v-else-if="!sessionTokens" class="text-xs text-[var(--color-muted)]">No token data yet</div>
    <div v-else class="space-y-2">
      <div class="flex justify-between text-xs">
        <span class="text-[var(--color-muted)]">Total</span>
        <span class="font-mono tabular-nums">{{ fmt(sessionTokens.tokens) }}</span>
      </div>
      <div class="flex justify-between text-xs">
        <span class="text-[var(--color-muted)]">Input</span>
        <span class="font-mono tabular-nums text-[var(--color-blue)]">{{ fmt(sessionTokens.input_tokens) }}</span>
      </div>
      <div class="flex justify-between text-xs">
        <span class="text-[var(--color-muted)]">Output</span>
        <span class="font-mono tabular-nums text-[var(--color-green)]">{{ fmt(sessionTokens.output_tokens) }}</span>
      </div>
      <div class="flex justify-between text-xs">
        <span class="text-[var(--color-muted)]">Billable</span>
        <span class="font-mono tabular-nums text-[var(--color-yellow)]">{{ fmt(sessionTokens.billable_tokens) }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useTokensStore } from '@/stores/tokens'

const props = defineProps<{ sessionId: string | null }>()

const tokensStore = useTokensStore()

const sessionTokens = computed(() =>
  tokensStore.data?.sessions?.find(s => s.session_id === props.sessionId) ?? null,
)

function fmt(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}
</script>
