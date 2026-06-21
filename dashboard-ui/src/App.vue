<template>
  <div class="app-root-shell h-screen bg-[var(--color-bg)] text-[var(--color-text)]">
    <Splitpanes class="app-shell default-theme h-full">
      <!-- Pane 1: Navigation sidebar -->
      <Pane :size="16" :min-size="12" :max-size="22">
        <Sidebar />
      </Pane>

      <!-- Pane 2: Main content (all routes) -->
      <Pane :min-size="25">
        <main class="h-screen min-w-0 overflow-y-auto">
          <router-view v-slot="{ Component }">
            <Transition name="fade" mode="out-in">
              <component :is="Component" />
            </Transition>
          </router-view>
        </main>
      </Pane>

      <!-- Pane 3: Inspector (only on /chat route) -->
      <Pane v-if="isChatRoute && isInspectorOpen" :size="26" :min-size="18" :max-size="42">
        <InspectorPanel @close="isInspectorOpen = false" />
      </Pane>
    </Splitpanes>

    <button
      v-if="isChatRoute && !isInspectorOpen"
      class="inspector-restore-button"
      type="button"
      title="Open inspector"
      aria-label="Open inspector"
      @click="isInspectorOpen = true"
    >
      <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M4 5h16M4 12h16M4 19h10" />
      </svg>
      <span>Inspector</span>
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Splitpanes, Pane } from 'splitpanes'
import 'splitpanes/dist/splitpanes.css'
import Sidebar from '@/components/shared/Sidebar.vue'
import InspectorPanel from '@/components/chat/InspectorPanel.vue'

const route = useRoute()
const isChatRoute = computed(() => route.name === 'chat')
const isInspectorOpen = ref(true)
</script>
