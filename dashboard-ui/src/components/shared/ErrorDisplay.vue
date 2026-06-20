<template>
  <div class="flex flex-col items-center justify-center gap-4 px-4 py-6 text-center" style="min-height: 12rem">
    <svg class="w-8 h-8 text-[var(--color-red)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
        d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
    </svg>

    <p class="text-sm text-[var(--color-red)]">{{ message }}</p>

    <button
      v-if="retryable"
      class="px-4 py-1.5 text-xs font-medium rounded border border-[var(--color-border)] text-[var(--color-text)] bg-[var(--color-cbg)] hover:bg-[var(--color-border)] transition-colors"
      @click="$emit('retry')"
    >
      Retry
    </button>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  message: string;
  retryable?: boolean;
}>(), {
  retryable: true,
});

defineEmits<{ retry: [] }>();
</script>
