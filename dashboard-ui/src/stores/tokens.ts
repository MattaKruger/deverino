import { createPollingStore } from './composables'
import { fetchTokenUsage } from '@/api/endpoints'
import type { TokenUsage } from '@/types/dashboard'

export const useTokensStore = createPollingStore<TokenUsage>(
  'tokens',
  fetchTokenUsage,
  30000,
)
