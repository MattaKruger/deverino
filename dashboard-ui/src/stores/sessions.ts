import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useIntervalFn } from '@vueuse/core'
import { fetchSessions } from '@/api/endpoints'
import type { SessionActivity } from '@/types/dashboard'

export const useSessionsStore = defineStore('sessions', () => {
  const data = ref<SessionActivity[] | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetch() {
    loading.value = true
    try {
      data.value = await fetchSessions()
      error.value = null
    } catch (e) {
      error.value = String(e)
    } finally {
      loading.value = false
    }
  }

  const { pause, resume } = useIntervalFn(fetch, 30000)
  fetch()

  return { data, loading, error, fetch, pause, resume }
})
