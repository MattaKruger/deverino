<template>
  <div class="flex items-center gap-3 px-3 py-2.5">
    <span
      v-for="(w, i) in widths"
      :key="i"
      class="h-3.5 rounded bg-[var(--color-border)] animate-pulse"
      :style="{ width: w }"
    ></span>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  widths: string[]
}>()
</script>
