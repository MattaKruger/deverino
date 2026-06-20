<template>
  <aside class="w-56 flex-shrink-0 flex flex-col h-screen bg-[var(--color-cbg)] border-r border-[var(--color-border)]" role="navigation" aria-label="Main navigation">
    <!-- Title -->
    <div class="px-4 py-5">
      <span class="text-xs font-bold uppercase tracking-widest text-[var(--color-blue)]">Deverino</span>
    </div>

    <!-- Nav links -->
    <nav class="flex flex-col gap-0.5 px-2">
      <router-link
        to="/"
        class="flex items-center gap-2 px-3 py-2 rounded text-sm text-[var(--color-muted)] hover:bg-[var(--color-border)] transition-colors"
        active-class="bg-[var(--color-border)] text-[var(--color-blue)]"
        exact-active-class="bg-[var(--color-border)] text-[var(--color-blue)]"
      >
        <!-- squares-2x2 icon -->
        <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
            d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
        </svg>
        Overview
      </router-link>

      <router-link
        to="/context-map"
        class="flex items-center gap-2 px-3 py-2 rounded text-sm text-[var(--color-muted)] hover:bg-[var(--color-border)] transition-colors"
        active-class="bg-[var(--color-border)] text-[var(--color-blue)]"
        exact-active-class="bg-[var(--color-border)] text-[var(--color-blue)]"
      >
        <!-- map icon -->
        <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
            d="M9 6.75V15m6-6v8.25m.503 3.498l4.875-2.437c.381-.19.622-.58.622-1.006V4.82c0-.836-.88-1.38-1.628-1.006l-3.869 1.934c-.317.159-.69.159-1.006 0L9.503 3.252a1.125 1.125 0 00-1.006 0L3.622 5.689C3.24 5.88 3 6.27 3 6.695V19.18c0 .836.88 1.38 1.628 1.006l3.869-1.934c.317-.159.69-.159 1.006 0l4.994 2.497c.317.158.69.158 1.006 0z" />
        </svg>
        Context Map
      </router-link>

      <router-link
        to="/sessions"
        class="flex items-center gap-2 px-3 py-2 rounded text-sm text-[var(--color-muted)] hover:bg-[var(--color-border)] transition-colors"
        active-class="bg-[var(--color-border)] text-[var(--color-blue)]"
        exact-active-class="bg-[var(--color-border)] text-[var(--color-blue)]"
      >
        <!-- users icon -->
        <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
            d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
        </svg>
        Sessions
      </router-link>

      <router-link
        to="/sub-agents"
        class="flex items-center gap-2 px-3 py-2 rounded text-sm text-[var(--color-muted)] hover:bg-[var(--color-border)] transition-colors"
        active-class="bg-[var(--color-border)] text-[var(--color-blue)]"
        exact-active-class="bg-[var(--color-border)] text-[var(--color-blue)]"
      >
        <!-- network/share icon -->
        <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
            d="M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m13.35-.622l1.757-1.757a4.5 4.5 0 00-6.364-6.364l-4.5 4.5a4.5 4.5 0 001.242 7.244" />
        </svg>
        Sub-Agents
      </router-link>

      <router-link
        to="/tokens"
        class="flex items-center gap-2 px-3 py-2 rounded text-sm text-[var(--color-muted)] hover:bg-[var(--color-border)] transition-colors"
        active-class="bg-[var(--color-border)] text-[var(--color-blue)]"
        exact-active-class="bg-[var(--color-border)] text-[var(--color-blue)]"
      >
        <!-- currency/coin icon -->
        <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
            d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125v-3.75" />
        </svg>
        Tokens
      </router-link>

      <router-link
        to="/skills"
        class="flex items-center gap-2 px-3 py-2 rounded text-sm text-[var(--color-muted)] hover:bg-[var(--color-border)] transition-colors"
        active-class="bg-[var(--color-border)] text-[var(--color-blue)]"
        exact-active-class="bg-[var(--color-border)] text-[var(--color-blue)]"
      >
        <!-- puzzle/cube icon -->
        <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
            d="M14.25 6.087c0-.355.186-.676.401-.959.221-.29.349-.634.349-1.003 0-1.036-1.007-1.875-2.25-1.875s-2.25.84-2.25 1.875c0 .369.128.713.349 1.003.215.283.401.604.401.959v0a.64.64 0 01-.657.643 48.39 48.39 0 01-4.163-.3c.186 1.613.293 3.25.315 4.907a.656.656 0 01-.658.663v0c-.355 0-.676-.186-.959-.401a1.647 1.647 0 00-1.003-.349c-1.036 0-1.875 1.007-1.875 2.25s.84 2.25 1.875 2.25c.369 0 .713-.128 1.003-.349.283-.215.604-.401.959-.401v0c.31 0 .555.26.532.57a48.039 48.039 0 01-.642 5.056c1.518.19 3.058.309 4.616.354a.64.64 0 00.657-.643v0c0-.355-.186-.676-.401-.959a1.647 1.647 0 01-.349-1.003c0-1.035 1.008-1.875 2.25-1.875 1.243 0 2.25.84 2.25 1.875 0 .369-.128.713-.349 1.003-.215.283-.401.604-.401.959v0c0 .333.277.599.61.58a48.1 48.1 0 005.427-.63 48.05 48.05 0 00.582-4.717.532.532 0 00-.533-.57v0c-.355 0-.676.186-.959.401-.29.221-.634.349-1.003.349-1.035 0-1.875-1.007-1.875-2.25s.84-2.25 1.875-2.25c.37 0 .713.128 1.003.349.283.215.604.401.959.401v0a.656.656 0 00.658-.663 48.422 48.422 0 00-.37-5.36c-1.886.342-3.81.574-5.766.689a.578.578 0 01-.61-.58v0z" />
        </svg>
        Skills
      </router-link>

      <router-link
        to="/chat"
        class="flex items-center gap-2 px-3 py-2 rounded text-sm text-[var(--color-muted)] hover:bg-[var(--color-border)] transition-colors"
        active-class="bg-[var(--color-border)] text-[var(--color-blue)]"
        exact-active-class="bg-[var(--color-border)] text-[var(--color-blue)]"
      >
        <!-- chat-bubble icon -->
        <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
            d="M8.625 9.75a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375m-13.5 3.01c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.184-4.183a1.14 1.14 0 01.778-.332 48.294 48.294 0 005.83-.498c1.585-.233 2.708-1.626 2.708-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
        </svg>
        Chat
      </router-link>

      <!-- Chat sessions (only visible on /chat route) -->
      <div v-if="isChatRoute" class="ml-3 mt-0.5 space-y-0.5">
        <button
          class="w-full flex items-center gap-2 px-3 py-1.5 rounded text-xs text-[var(--color-muted)] hover:bg-[var(--color-border)] transition-colors"
          @click="handleNewChatSession"
        >
          <svg class="w-3 h-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
          </svg>
          New Chat
        </button>

        <div v-if="chatStore.loading" class="px-3 py-1 text-[10px] text-[var(--color-muted)]">
          Loading...
        </div>
        <div v-else-if="chatStore.error" class="px-3 py-1 text-[10px] text-[var(--color-red)]">
          {{ chatStore.error }}
        </div>

        <button
          v-for="s in chatStore.sessions"
          :key="s.session_id"
          class="w-full text-left px-3 py-1.5 rounded text-xs transition-colors"
          :class="s.session_id === chatStore.activeSessionId
            ? 'bg-[var(--color-border)] text-[var(--color-text)]'
            : 'text-[var(--color-muted)] hover:bg-[var(--color-border)]'"
          @click="chatStore.selectSession(s.session_id)"
        >
          <div class="flex items-center gap-1">
            <span class="truncate">{{ s.objective || 'Chat session' }}</span>
            <button
              class="ml-auto shrink-0 hover:text-[var(--color-red)]"
              title="Delete session"
              @click.stop="handleDeleteChatSession(s.session_id)"
            >
              <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          </div>
          <div class="text-[10px] text-[var(--color-muted)] mt-0.5">
            {{ s.message_count }} msgs
          </div>
        </button>
      </div>
    </nav>

    <!-- Health footer -->
    <div class="mt-auto border-t border-[var(--color-border)] px-4 py-3">
      <HealthIndicator
        :last-fetched="overviewStore.lastFetched"
        :error="overviewStore.error"
      />
    </div>
  </aside>
</template>
<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import HealthIndicator from '@/components/shared/HealthIndicator.vue';
import { useOverviewStore } from '@/stores/overview';
import { useChatStore } from '@/stores/chat'

const route = useRoute()
const overviewStore = useOverviewStore();
const chatStore = useChatStore()

const isChatRoute = computed(() => route.name === 'chat')

onMounted(() => {
  chatStore.loadSessions()
})

async function handleNewChatSession() {
  try {
    await chatStore.createSession()
  } catch {
    // error surfaced via chatStore.error
  }
}

async function handleDeleteChatSession(id: string) {
  try {
    await chatStore.deleteSession(id)
  } catch {
    // error surfaced via chatStore.error
  }
}
</script>
