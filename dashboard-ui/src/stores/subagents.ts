import { createPollingStore } from './composables'
import { fetchSubAgentTree } from '@/api/endpoints'
import type { SubAgentNode } from '@/types/dashboard'

export const useSubAgentsStore = createPollingStore<SubAgentNode[]>(
  'subagents',
  fetchSubAgentTree,
  30000,
)
