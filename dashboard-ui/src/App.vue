<template>
  <Splitpanes class="default-theme h-screen bg-[var(--color-bg)] text-[var(--color-text)]">
    <!-- Pane 1: Navigation sidebar -->
    <Pane :size="14" :min-size="8" :max-size="20">
      <Sidebar />
    </Pane>

    <!-- Pane 2: Main content (all routes) -->
    <Pane :min-size="25">
      <router-view v-slot="{ Component }">
        <Transition name="fade" mode="out-in">
          <component :is="Component" />
        </Transition>
      </router-view>
    </Pane>

    <!-- Pane 3: Inspector (only on /chat route) -->
    <Pane v-if="isChatRoute" :size="25" :min-size="15" :max-size="40">
      <InspectorPanel />
    </Pane>
  </Splitpanes>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Splitpanes, Pane } from 'splitpanes'
import 'splitpanes/dist/splitpanes.css'
import Sidebar from '@/components/shared/Sidebar.vue'
import InspectorPanel from '@/components/chat/InspectorPanel.vue'

const route = useRoute()
const isChatRoute = computed(() => route.name === 'chat')
</script>
