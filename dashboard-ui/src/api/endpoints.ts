import { get, type GetOpts } from './client'
import type {
  DashboardSnapshot,
  EventDetail,
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

export function fetchOverview(opts?: GetOpts): Promise<DashboardSnapshot> {
  return get<DashboardSnapshot>('/overview', opts)
}

export function fetchSessions(opts?: GetOpts): Promise<SessionActivity[]> {
  return get<SessionActivity[]>('/sessions', opts)
}

export function fetchSessionEvents(id: string, opts?: GetOpts): Promise<SessionEventRow[]> {
  return get<SessionEventRow[]>(`/sessions/${id}/events`, opts)
}

export function fetchEventDetail(eventId: number, opts?: GetOpts): Promise<EventDetail> {
  return get<EventDetail>(`/events/${eventId}`, opts)
}

export function fetchToolsPerformance(opts?: GetOpts): Promise<ToolsPerformance> {
  return get<ToolsPerformance>('/tools/performance', opts)
}

export function fetchSubAgentTree(opts?: GetOpts): Promise<SubAgentNode[]> {
  return get<SubAgentNode[]>('/subagents/tree', opts)
}

export function fetchTokenEconomics(opts?: GetOpts): Promise<TokenBucket[]> {
  return get<TokenBucket[]>('/tokens/economics', opts)
}

export function fetchTokenUsage(opts?: GetOpts): Promise<TokenUsage> {
  return get<TokenUsage>('/tokens/usage', opts)
}

export function fetchContextMaps(opts?: GetOpts): Promise<ContextMapHealth[]> {
  return get<ContextMapHealth[]>('/context-maps', opts)
}

export function fetchContextMapEntries(key: string, opts?: GetOpts): Promise<ContextMapEntrySummary[]> {
  return get<ContextMapEntrySummary[]>(`/context-maps/${key}/entries`, opts)
}

export function fetchRecentEvents(limit?: number, opts?: GetOpts): Promise<UnifiedEvent[]> {
  return get<UnifiedEvent[]>(`/events/recent?limit=${limit ?? 50}`, opts)
}

export function fetchErrors(opts?: GetOpts): Promise<ErrorSummary[]> {
  return get<ErrorSummary[]>('/errors', opts)
}
