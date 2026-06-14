import { createPollingStore } from './composables'
import { fetchErrors } from '@/api/endpoints'
import type { ErrorSummary } from '@/types/dashboard'

export const useErrorsStore = createPollingStore<ErrorSummary[]>(
  'errors',
  fetchErrors,
  60000,
)
