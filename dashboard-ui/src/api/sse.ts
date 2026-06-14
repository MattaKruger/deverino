import type { UnifiedEvent } from '@/types/dashboard'

const BASE = '/api'

export type SSEHandler = (events: UnifiedEvent[]) => void

export function createEventStream(onEvents: SSEHandler): { close: () => void } {
  const url = `${BASE}/events/stream`
  const source = new EventSource(url)

  source.onmessage = (evt) => {
    try {
      const event = JSON.parse(evt.data) as UnifiedEvent
      onEvents([event])
    } catch {
      // ignore malformed messages
    }
  }

  source.onerror = () => {
    // EventSource auto-reconnects; no action needed
  }

  return {
    close() {
      source.close()
    },
  }
}
