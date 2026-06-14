const BASE = '/api'

export interface GetOpts {
  signal?: AbortSignal
}

// ── In-flight request deduplication ──────────────────────────────────────────

const _inflight = new Map<string, Promise<unknown>>()

export async function get<T>(path: string, opts?: GetOpts): Promise<T> {
  const key = `${BASE}${path}`

  // Return existing in-flight promise for duplicate GETs
  const existing = _inflight.get(key)
  if (existing) return existing as Promise<T>

  const promise = fetch(key, { signal: opts?.signal })
    .then(res => {
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
      return res.json()
    })
    .finally(() => {
      _inflight.delete(key)
    })

  _inflight.set(key, promise)
  return promise as Promise<T>
}
