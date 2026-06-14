import { createPollingStore } from './composables'
import { fetchOverview } from '@/api/endpoints'
import type { DashboardSnapshot } from '@/types/dashboard'

export const useOverviewStore = createPollingStore<DashboardSnapshot>(
  'overview',
  fetchOverview,
  15000,
)
