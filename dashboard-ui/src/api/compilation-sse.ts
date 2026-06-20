import type { CompilationEvent } from '@/types/dashboard'

export function createCompilationStream(
  onEvent: (event: CompilationEvent) => void,
  onError?: (error: string) => void,
): { close: () => void } {
  const source = new EventSource('/api/skills/compile/stream')

  const addHandler = (type: CompilationEvent['event']) => {
    source.addEventListener(type, (e: MessageEvent) => {
      try {
        onEvent(JSON.parse(e.data) as CompilationEvent)
      } catch {
        // ignore malformed messages
      }
    })
  }

  addHandler('skill_compiled')
  addHandler('compilation_progress')
  addHandler('compilation_done')
  addHandler('compilation_error')

  source.onerror = () => {
    // EventSource auto-reconnects on network errors, but not on HTTP 4xx/5xx.
    // If the stream is unreachable (404, 500), the connection dies silently.
    // Surface this to the UI so the user knows something is wrong.
    if (source.readyState === EventSource.CLOSED) {
      onError?.('Compilation stream disconnected. The server may be unavailable.')
    }
  }

  return {
    close() {
      source.close()
    },
  }
}
