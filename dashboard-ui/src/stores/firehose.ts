import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useIntervalFn } from '@vueuse/core'
import { fetchRecentEvents } from '@/api/endpoints'
import { createEventStream } from '@/api/sse'
import type { UnifiedEvent } from '@/types/dashboard'

export const useFirehoseStore = defineStore('firehose', () => {
  const data = ref<UnifiedEvent[] | null>(null)
  const loading = ref(false)
  const isStale = ref(false)
  const error = ref<string | null>(null)
  const lastFetched = ref<Date | null>(null)
  let _hasLoaded = false

  // ── SSE connection ──────────────────────────────────────────────────────

  let _sse: ReturnType<typeof createEventStream> | null = null
  let _paused = false
  const _buffer: UnifiedEvent[] = []

  function _startSSE() {
    if (_sse) return
    try {
      _sse = createEventStream((events) => {
        if (_paused) {
          _buffer.push(...events)
          return
        }
        if (!data.value) data.value = []
        // Prepend newest events (SSE delivers newest first)
        for (const e of events) {
          if (!data.value.some((x) => x.event_id === e.event_id)) {
            data.value.unshift(e)
          }
        }
        // Trim to max 200 events
        if (data.value.length > 200) {
          data.value = data.value.slice(0, 200)
        }
        lastFetched.value = new Date()
        if (!_hasLoaded) {
          _hasLoaded = true
          loading.value = false
        }
      })
    } catch {
      _sse = null
      // Fall through to polling fallback below
    }
  }

  function _stopSSE() {
    _sse?.close()
    _sse = null
  }

  // ── Polling fallback ────────────────────────────────────────────────────

  async function _poll() {
    if (_sse) return // SSE is active, skip poll
    try {
      const events = await fetchRecentEvents(50)
      data.value = events
      error.value = null
      lastFetched.value = new Date()
      _hasLoaded = true
    } catch (e) {
      error.value = String(e)
    } finally {
      loading.value = false
    }
  }

  // Start SSE first; if it fails, polling kicks in via the interval
  loading.value = true
  _startSSE()
  const { pause: _pausePoll, resume: _resumePoll } = useIntervalFn(_poll, 10000)

  // Safety: clear loading if SSE connects but stream is empty after 3s
  if (_sse) {
    setTimeout(() => {
      if (!_hasLoaded) {
        _hasLoaded = true
        loading.value = false
        data.value = data.value ?? []
        lastFetched.value = new Date()
      }
    }, 3000)
  }

  // If SSE failed to start, do an immediate poll
  if (!_sse) {
    _poll()
  }

  // ── Public API ──────────────────────────────────────────────────────────

  function fetch() {
    if (!_sse) _poll()
  }

  function pause() {
    _paused = true
    _pausePoll()
  }

  function resume() {
    _paused = false
    // Flush buffer
    if (_buffer.length && data.value) {
      for (const e of _buffer) {
        if (!data.value.some((x) => x.event_id === e.event_id)) {
          data.value.unshift(e)
        }
      }
      _buffer.length = 0
    }
    _resumePoll()
    if (!_sse) _startSSE()
  }

  return { data, loading, isStale, error, lastFetched, fetch, pause, resume }
})
