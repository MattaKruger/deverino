import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useIntervalFn } from '@vueuse/core'
import { fetchContextMaps } from '@/api/endpoints'
import type { ContextMapHealth } from '@/types/dashboard'

export const useContextMapsStore = defineStore('contextMaps', () => {
  const data = ref<ContextMapHealth[] | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetch() {
    loading.value = true
    try {
      data.value = await fetchContextMaps()
      error.value = null
    } catch (e) {
      error.value = String(e)
    } finally {
      loading.value = false
    }
  }

  const { pause, resume } = useIntervalFn(fetch, 60000)
  fetch()

  return { data, loading, error, fetch, pause, resume }
})
