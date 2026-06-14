import { createPollingStore } from './composables'
import { fetchSessions } from '@/api/endpoints'
import type { SessionActivity } from '@/types/dashboard'

export const useSessionsStore = createPollingStore<SessionActivity[]>(
  'sessions',
  fetchSessions,
  30000,
)
