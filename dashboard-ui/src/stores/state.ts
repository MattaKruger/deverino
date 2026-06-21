import { defineStore } from 'pinia'
import { ref } from 'vue'
import { fetchProjectState, fetchStateEvents, fetchStateProposals } from '@/api/endpoints'
import type { ProjectState, StateEvent, StateProposal } from '@/types/dashboard'

export const useStateStore = defineStore('state', () => {
  const projectState = ref<ProjectState | null>(null)
  const events = ref<StateEvent[]>([])
  const proposals = ref<StateProposal[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function loadAll() {
    loading.value = true
    error.value = null
    try {
      const [ps, ev, pr] = await Promise.all([
        fetchProjectState(),
        fetchStateEvents(50),
        fetchStateProposals(),
      ])
      projectState.value = ps
      events.value = ev
      proposals.value = pr
    } catch (e) {
      error.value = String(e)
    } finally {
      loading.value = false
    }
  }

  const pendingCount = () => proposals.value.length

  return {
    projectState,
    events,
    proposals,
    loading,
    error,
    loadAll,
    pendingCount,
  }
})
