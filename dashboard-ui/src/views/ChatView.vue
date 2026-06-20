<template>
  <div class="flex flex-col h-full min-w-0">
    <!-- No session state -->
    <div v-if="!chatStore.activeSessionId" class="flex-1 flex items-center justify-center">
      <div class="text-center space-y-4">
        <div class="text-[var(--color-muted)] text-sm">
          Select a chat session from the sidebar, or create a new one
        </div>
        <button
          class="px-4 py-2 rounded bg-[var(--color-blue)] text-white text-sm hover:opacity-90 transition-opacity"
          @click="handleNewSession"
        >
          New Chat
        </button>
      </div>
    </div>

    <!-- Active chat -->
    <Chatbot
      v-else
      :key="chatStore.activeSessionId"
      :chat-service-config="chatConfig"
      class="flex-1"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { Chatbot, useAgentToolcall } from '@tdesign-vue-next/chat'
import { useChatStore } from '@/stores/chat'

import GenericToolCard from '@/components/chat/GenericToolCard.vue'
import FileReadCard from '@/components/chat/FileReadCard.vue'
import FileWriteCard from '@/components/chat/FileWriteCard.vue'
import SearchCard from '@/components/chat/SearchCard.vue'
import ContainerExecCard from '@/components/chat/ContainerExecCard.vue'
import ContainerSpawnCard from '@/components/chat/ContainerSpawnCard.vue'
import WebSearchCard from '@/components/chat/WebSearchCard.vue'
import DelegateTaskCard from '@/components/chat/DelegateTaskCard.vue'
import BlackboardCard from '@/components/chat/BlackboardCard.vue'
import SkillToolCard from '@/components/chat/SkillToolCard.vue'

const chatStore = useChatStore()

const identityHandler = async <T>(_args: T, backendResult?: unknown) => backendResult ?? _args

const { register } = useAgentToolcall()

const toolCards = [
  { name: 'read_file',         component: FileReadCard,      handler: identityHandler },
  { name: 'view_file',         component: FileReadCard,      handler: identityHandler },
  { name: 'write_file',        component: FileWriteCard,     handler: identityHandler },
  { name: 'patch',             component: FileWriteCard,     handler: identityHandler },
  { name: 'apply_diff',        component: FileWriteCard,     handler: identityHandler },
  { name: 'search_files',      component: SearchCard,        handler: identityHandler },
  { name: 'search_in_file',    component: SearchCard,        handler: identityHandler },
  { name: 'semble_search',     component: SearchCard,        handler: identityHandler },
  { name: 'container_exec',    component: ContainerExecCard,  handler: identityHandler },
  { name: 'execute_python',    component: ContainerExecCard,  handler: identityHandler },
  { name: 'container_spawn',   component: ContainerSpawnCard, handler: identityHandler },
  { name: 'container_destroy', component: ContainerSpawnCard, handler: identityHandler },
  { name: 'web_search',        component: WebSearchCard,     handler: identityHandler },
  { name: 'delegate_task',     component: DelegateTaskCard,  handler: identityHandler },
  { name: 'read_memory',       component: BlackboardCard,    handler: identityHandler },
  { name: 'list_corpora',      component: BlackboardCard,    handler: identityHandler },
  { name: 'inspect_own_context', component: BlackboardCard,  handler: identityHandler },
  { name: 'skills_list',       component: SkillToolCard,     handler: identityHandler },
  { name: 'skill_view',        component: SkillToolCard,     handler: identityHandler },
  { name: 'skill_manage',      component: SkillToolCard,     handler: identityHandler },
  { name: 'acdl_inspect',      component: SkillToolCard,     handler: identityHandler },
  { name: '*',                 component: GenericToolCard,   handler: identityHandler },
]
register(toolCards)

const chatConfig = computed(() => ({
  endpoint: '/api/chat',
  protocol: 'agui' as const,
  stream: true,
  onRequest: (body: Record<string, unknown>) => ({
    body: JSON.stringify({
      threadId: chatStore.activeSessionId ?? body.threadId,
      runId: crypto.randomUUID(),
      state: body.state ?? {},
      messages: Array.isArray(body.messages) && body.messages.length
        ? body.messages
        : body.prompt
          ? [{ id: (body as Record<string,string>).messageID ?? crypto.randomUUID(), role: 'user', content: body.prompt }]
          : [],
      tools: body.tools ?? [],
      context: body.context ?? [],
      forwardedProps: body.forwardedProps ?? {},
    }),
  }),
}))

onMounted(() => {
  chatStore.loadSessions()
})

async function handleNewSession() {
  try {
    await chatStore.createSession()
  } catch {
    // Error surfaced via chatStore.error
  }
}

</script>
