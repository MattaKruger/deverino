import { createPollingStore } from './composables'
import { fetchToolsPerformance } from '@/api/endpoints'
import type { ToolsPerformance } from '@/types/dashboard'

export const useToolsStore = createPollingStore<ToolsPerformance>(
  'tools',
  fetchToolsPerformance,
  30000,
)
