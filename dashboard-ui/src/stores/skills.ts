import { createPollingStore } from './composables'
import { fetchSkills, fetchCompilationProgress } from '@/api/endpoints'
import type { SkillCompilationSummary, CompilationProgress } from '@/types/dashboard'

export const useSkillsStore = createPollingStore<SkillCompilationSummary[]>(
  'skills',
  fetchSkills,
  15000,
)

export const useCompilationProgressStore = createPollingStore<CompilationProgress>(
  'compilation-progress',
  fetchCompilationProgress,
  5000,
)

/**
 * Patch a single skill in the skills store in-place, triggering Vue reactivity.
 * Uses array replacement (rather than index assignment) for reliable ref tracking.
 */
export function patchSkillInStore(
  store: ReturnType<typeof useSkillsStore>,
  name: string,
  data: Partial<SkillCompilationSummary>,
): void {
  const current = store.data ?? []
  const idx = current.findIndex(s => s.name === name)
  const updated = [...current]
  if (idx >= 0) {
    updated[idx] = { ...updated[idx], ...data } as SkillCompilationSummary
  } else {
    // First compilation for this skill — push new entry.
    // Caller guarantees the event carries required fields.
    updated.push(data as SkillCompilationSummary)
  }
  store.data = updated
}
