// ── Core dataclass mirrors ───────────────────────────────────────────────────

export interface DashboardSummary {
  total_sessions: number
  total_events: number
  total_tokens: number
  skill_calls: number
  skill_failures: number
  context_pending: number
}

export interface SkillPerformance {
  skill_name: string
  calls: number
  failures: number
  last_status: string
  last_seen: string
}

export interface RecentFailure {
  event_id: number
  session_id: string
  event_type: string
  status: string
  label: string
  created_at: string
  detail: string
}

export interface TokenBucket {
  bucket: string
  tokens: number
  input_tokens: number
  output_tokens: number
}

export interface ContextMapHealth {
  corpus_key: string
  version: number
  token_count: number
  last_updated: string
  freeze_until: string
  pending_events: number
}

export interface ContextMapEntrySummary {
  entry_id: string
  key: string
  section: string
  observation_type: string
  priority: number
  materialization_count: number
  token_estimate: number
  summary: string
}

export interface SessionActivity {
  session_id: string
  status: string
  last_event_type: string
  event_count: number
  total_tokens: number
  skill_failures: number
  last_seen: string
  goal: string
}

export interface ModelTokenUsage {
  model: string
  actions: number
  sessions: number
  tokens: number
  input_tokens: number
  output_tokens: number
  billable_tokens: number
  new_tokens: number
}

export interface SessionTokenUsage {
  session_id: string
  models: string
  actions: number
  tokens: number
  input_tokens: number
  output_tokens: number
  billable_tokens: number
  new_tokens: number
  last_seen: string
}

export interface SessionEventRow {
  event_id: number
  event_type: string
  created_at: string
  time_delta: number
  skill_name: string
  status: string
  tokens_used: number
  content_preview: string
}

export interface EventDetail {
  event_id: number
  event_type: string
  created_at: string
  skill_name: string
  status: string
  tokens_used: number
  content: string
  payload: string
}

export interface DashboardSnapshot {
  summary: DashboardSummary
  skills: SkillPerformance[]
  recent_failures: RecentFailure[]
  token_buckets: TokenBucket[]
  context_maps: ContextMapHealth[]
  session_activity: SessionActivity[]
  model_token_usage: ModelTokenUsage[]
  session_token_usage: SessionTokenUsage[]
}

export interface UnifiedEvent {
  event_id: string
  event_type: string
  timestamp: string
  session_id: string
  detail_json: string
  source_table: string
}

export interface ToolLatency {
  skill_name: string
  session_id: string
  latency_s: number
  status: string
  tokens_used: number
}

export interface SubAgentNode {
  sub_session_id: string
  parent_session_id: string
  persona: string
  objective: string
  status: string
  started_at: string
  completed_at: string
  duration_s: number
  summary: string
}

export interface ErrorSummary {
  skill_name: string
  error_count: number
  cancel_count: number
  last_error_at: string
}

// ── Composite / helper types ─────────────────────────────────────────────────

export interface ToolsPerformance {
  skills: SkillPerformance[]
  latency: ToolLatency[]
}

export interface TokenUsage {
  models: ModelTokenUsage[]
  sessions: SessionTokenUsage[]
}
