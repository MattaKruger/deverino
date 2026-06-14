<template>
  <div class="flex h-screen bg-[var(--bg)] text-[var(--text)]">
    <Sidebar />
    <main class="flex-1 overflow-y-auto">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import Sidebar from '@/components/shared/Sidebar.vue';
</script>
