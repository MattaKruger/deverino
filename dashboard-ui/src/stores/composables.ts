import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useIntervalFn } from '@vueuse/core'

// ── Singleton visibility watcher ────────────────────────────────────────────────

const isPageVisible = ref(true)
let _visInit = false

const _onVisible = new Set<() => void>()

function _ensureVisibilityWatcher() {
  if (_visInit) return
  _visInit = true
  if (typeof document === 'undefined') return
  document.addEventListener('visibilitychange', () => {
    isPageVisible.value = document.visibilityState === 'visible'
    if (isPageVisible.value) {
      for (const cb of _onVisible) cb()
    }
  })
  isPageVisible.value = document.visibilityState === 'visible'
}

// ── Composable ──────────────────────────────────────────────────────────────────

export function createPollingStore<T>(
  storeId: string,
  fetcher: (opts: { signal: AbortSignal }) => Promise<T>,
  intervalMs: number,
) {
  return defineStore(storeId, () => {
    _ensureVisibilityWatcher()

    const data = ref<T | null>(null)
    const loading = ref(false)
    const isStale = ref(false)
    const error = ref<string | null>(null)
    const lastFetched = ref<Date | null>(null)
    let controller: AbortController | null = null
    let _hasLoaded = false

    async function fetch() {
      // Skip when page hidden; registered callback will fire on resume
      if (!isPageVisible.value) return

      controller?.abort()
      controller = new AbortController()
      const signal = controller.signal

      // Show full loading only on first fetch; stale indicator on subsequent polls
      if (!_hasLoaded) {
        loading.value = true
      } else {
        isStale.value = true
      }

      try {
        data.value = await fetcher({ signal })
        error.value = null
        lastFetched.value = new Date()
        _hasLoaded = true
      } catch (e) {
        if (e instanceof DOMException && e.name === 'AbortError') return
        error.value = String(e)
      } finally {
        loading.value = false
        isStale.value = false
      }
    }

    const { pause, resume } = useIntervalFn(fetch, intervalMs)
    fetch()

    // Re-fetch when page becomes visible again
    _onVisible.add(() => { fetch() })

    return { data, loading, isStale, error, lastFetched, fetch, pause, resume }

  })
}
