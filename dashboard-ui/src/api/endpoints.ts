import { get, type GetOpts } from './client'
import type {
  CompilationProgress,
  ContextMapEntrySummary,
  ContextMapHealth,
  DashboardSnapshot,
  ErrorSummary,
  EventDetail,
  SessionActivity,
  SessionEventRow,
  SkillCompilationSummary,
  SubAgentNode,
  TokenBucket,
  TokenUsage,
  ToolsPerformance,
  UnifiedEvent,
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

export function fetchSkills(opts?: GetOpts): Promise<SkillCompilationSummary[]> {
  return get<SkillCompilationSummary[]>('/skills', opts)
}

export function fetchCompilationProgress(opts?: GetOpts): Promise<CompilationProgress> {
  return get<CompilationProgress>('/skills/progress', opts)
}

export function postCompileSkills(): Promise<{ status: string; detail?: string }> {
  return fetch('/api/skills/compile', { method: 'POST' }).then(r => r.json())
}

export function postCompileSkill(name: string): Promise<{ status: string; detail?: string }> {
  return fetch(`/api/skills/${encodeURIComponent(name)}/compile`, { method: 'POST' }).then(r => r.json())
}
