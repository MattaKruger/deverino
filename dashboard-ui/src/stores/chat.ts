import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface ChatSession {
  session_id: string
  objective: string
  created_at: string
  message_count: number
}

export const useChatStore = defineStore('chat', () => {
  const sessions = ref<ChatSession[]>([])
  const activeSessionId = ref<string | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const activeSession = computed(() =>
    sessions.value.find(s => s.session_id === activeSessionId.value) ?? null,
  )

  async function loadSessions() {
    loading.value = true
    error.value = null
    try {
      const res = await fetch('/api/sessions/chat')
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
      sessions.value = await res.json()
    } catch (e) {
      error.value = String(e)
    } finally {
      loading.value = false
    }
  }

  async function createSession(): Promise<string> {
    const res = await fetch('/api/sessions/chat', { method: 'POST' })
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    const { session_id } = await res.json()
    activeSessionId.value = session_id
    await loadSessions()
    return session_id
  }

  async function deleteSession(id: string) {
    const res = await fetch(`/api/sessions/chat/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    })
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    if (activeSessionId.value === id) {
      activeSessionId.value = null
    }
    await loadSessions()
  }

  function selectSession(id: string) {
    activeSessionId.value = id
  }

  return {
    sessions,
    activeSessionId,
    activeSession,
    loading,
    error,
    loadSessions,
    createSession,
    deleteSession,
    selectSession,
  }
})
