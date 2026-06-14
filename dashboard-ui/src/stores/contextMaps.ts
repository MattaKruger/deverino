import { createPollingStore } from './composables'
import { fetchContextMaps } from '@/api/endpoints'
import type { ContextMapHealth } from '@/types/dashboard'

export const useContextMapsStore = createPollingStore<ContextMapHealth[]>(
  'contextMaps',
  fetchContextMaps,
  60000,
)
