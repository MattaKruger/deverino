import { get } from './client'
import type {
  DashboardSnapshot,
  SessionActivity,
  SessionEventRow,
  ToolsPerformance,
  SubAgentNode,
  TokenBucket,
  TokenUsage,
  ContextMapHealth,
  ContextMapEntrySummary,
  UnifiedEvent,
  ErrorSummary,
} from '@/types/dashboard'

export function fetchOverview(): Promise<DashboardSnapshot> {
  return get<DashboardSnapshot>('/overview')
}

export function fetchSessions(): Promise<SessionActivity[]> {
  return get<SessionActivity[]>('/sessions')
}

export function fetchSessionEvents(id: string): Promise<SessionEventRow[]> {
  return get<SessionEventRow[]>(`/sessions/${id}/events`)
}

export function fetchToolsPerformance(): Promise<ToolsPerformance> {
  return get<ToolsPerformance>('/tools/performance')
}

export function fetchSubAgentTree(): Promise<SubAgentNode[]> {
  return get<SubAgentNode[]>('/subagents/tree')
}

export function fetchTokenEconomics(): Promise<TokenBucket[]> {
  return get<TokenBucket[]>('/tokens/economics')
}

export function fetchTokenUsage(): Promise<TokenUsage> {
  return get<TokenUsage>('/tokens/usage')
}

export function fetchContextMaps(): Promise<ContextMapHealth[]> {
  return get<ContextMapHealth[]>('/context-maps')
}

export function fetchContextMapEntries(key: string): Promise<ContextMapEntrySummary[]> {
  return get<ContextMapEntrySummary[]>(`/context-maps/${key}/entries`)
}

export function fetchRecentEvents(limit?: number): Promise<UnifiedEvent[]> {
  return get<UnifiedEvent[]>(`/events/recent?limit=${limit ?? 50}`)
}

export function fetchErrors(): Promise<ErrorSummary[]> {
  return get<ErrorSummary[]>('/errors')
}
