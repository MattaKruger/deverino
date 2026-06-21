<template>
  <div class="view-shell view-stack">
    <header class="page-header">
      <div class="page-heading">
        <div class="page-kicker">Capability registry</div>
        <h1 class="page-title">Skills</h1>
        <p class="page-subtitle">
          Compile, inspect, and triage system and project skills by extracted contracts, templates, aliases, and errors.
        </p>
      </div>
      <div class="page-actions">
        <span class="code-pill">{{ store.data?.length ?? 0 }} total</span>
        <button
          class="btn btn-primary"
          :disabled="compiling"
          @click="triggerCompile"
        >
          <span v-if="compiling" class="flex items-center gap-2">
            <svg class="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Compiling
          </span>
          <span v-else>Compile All</span>
        </button>
      </div>
    </header>

    <div
      v-if="progressCounts.running || compiling"
      class="toolbar-card border-[var(--color-blue)]/35"
    >
      <div class="w-full">
        <div class="flex items-center justify-between mb-2">
          <span class="text-sm font-medium text-[var(--color-blue)]">
          Compiling skills&hellip;
          </span>
          <span class="text-xs text-[var(--color-muted)] mono">
            {{ progressCounts.completed }} / {{ progressCounts.total }}
            <span v-if="progressCounts.errors > 0" class="text-[var(--color-red)] ml-2">
              &middot; {{ progressCounts.errors }} errors
            </span>
          </span>
        </div>
        <div class="h-2 w-full rounded-full bg-[var(--color-grid)]">
          <div
            class="h-2 rounded-full transition-all duration-500"
            :class="progressCounts.errors > 0 ? 'bg-[var(--color-yellow)]' : 'bg-[var(--color-blue)]'"
            :style="{ width: pct + '%' }"
          />
        </div>
        <div v-if="compileError" class="mt-2 text-xs text-[var(--color-red)]">{{ compileError }}</div>
      </div>
    </div>

    <div class="stat-grid">
      <button class="stat-card stat-card--button" @click="filterStatus = filterStatus === 'full' ? '' : 'full'" :class="{ 'stat-card--active': filterStatus === 'full' }">
        <div class="metric-value mono text-[var(--color-green)]">{{ counts.full }}</div>
        <div class="metric-label">Full</div>
      </button>
      <button class="stat-card stat-card--button" @click="filterStatus = filterStatus === 'partial' ? '' : 'partial'" :class="{ 'stat-card--active': filterStatus === 'partial' }">
        <div class="metric-value mono text-[var(--color-yellow)]">{{ counts.partial }}</div>
        <div class="metric-label">Partial</div>
      </button>
      <button class="stat-card stat-card--button" @click="filterStatus = filterStatus === 'rejected' ? '' : 'rejected'" :class="{ 'stat-card--active': filterStatus === 'rejected' }">
        <div class="metric-value mono text-[var(--color-red)]">{{ counts.rejected }}</div>
        <div class="metric-label">Rejected</div>
      </button>
      <button class="stat-card stat-card--button" @click="filterStatus = filterStatus === 'not_compiled' ? '' : 'not_compiled'" :class="{ 'stat-card--active': filterStatus === 'not_compiled' }">
        <div class="metric-value mono text-[var(--color-muted)]">{{ counts.notCompiled }}</div>
        <div class="metric-label">Not Compiled</div>
      </button>
    </div>

    <Panel
      title="Skill registry"
      :loading="store.loading"
      :isStale="store.isStale"
      :error="store.error"
      :last-updated="store.lastFetched"
    >
      <div v-if="filteredSkills.length" class="space-y-1">
        <div
          v-for="skill in filteredSkills"
          :key="skill.name"
          class="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-muted)]"
          :class="{ 'opacity-50': skill.compilation_status === 'not_compiled' }"
        >
          <!-- Row header -->
          <button
            class="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-[var(--color-surface-raised)] transition-colors"
            @click="toggle(skill.name)"
          >
            <span
              class="w-2.5 h-2.5 rounded-full shrink-0"
              :class="statusDot(skill.compilation_status)"
            />
            <span class="mono text-sm font-medium flex-1">{{ skill.name }}</span>
            <!-- Per-skill compile button -->
            <button
              v-if="skill.compilation_status === 'not_compiled'"
              class="btn min-h-0 px-2 py-1 text-xs"
              :class="compilingSkill === skill.name
                ? ''
                : 'text-[var(--color-blue)]'"
              :disabled="compilingSkill === skill.name"
              @click.stop="compileOne(skill.name)"
              title="Compile this skill"
            >
              <span v-if="compilingSkill === skill.name" class="inline-block w-3 h-3 border-2 border-[var(--color-muted)] border-t-transparent rounded-full animate-spin" />
              <span v-else>Compile</span>
            </button>
            <button
              v-else
              class="btn min-h-0 px-2 py-1 text-xs"
              :class="compilingSkill === skill.name
                ? ''
                : 'text-[var(--color-yellow)]'"
              :disabled="compilingSkill === skill.name"
              @click.stop="compileOne(skill.name)"
              title="Recompile this skill"
            >
              <span v-if="compilingSkill === skill.name" class="inline-block w-3 h-3 border-2 border-[var(--color-muted)] border-t-transparent rounded-full animate-spin" />
              <span v-else>Recompile</span>
            </button>
            <span class="text-xs text-[var(--color-muted)] w-16 text-right">{{ skill.skill_type }}</span>
            <span v-if="skill.version" class="text-xs text-[var(--color-muted)] w-12 text-right">v{{ skill.version }}</span>
            <span class="text-xs w-20 text-right" :class="skill.contract_count ? 'text-[var(--color-muted)]' : 'text-[var(--color-muted)]/50'">
              {{ skill.contract_count }} contracts
            </span>
            <span class="text-xs w-16 text-right" :class="skill.template_count ? 'text-[var(--color-muted)]' : 'text-[var(--color-muted)]/50'">
              {{ skill.template_count }} tmpl
            </span>
            <span class="text-xs text-[var(--color-muted)] w-32 text-right truncate" :title="skill.compiled_at">
              {{ skill.compiled_at ? new Date(skill.compiled_at).toLocaleString() : '—' }}
            </span>
          </button>

          <!-- Expanded detail -->
          <div v-if="expanded.has(skill.name)" class="border-t border-[var(--color-border)] px-4 py-3 space-y-3 bg-[var(--color-surface)]">
            <!-- Empty state -->
            <div
              v-if="!skill.contracts.length && !skill.templates.length && !skill.compilation_errors.length"
              class="text-xs text-[var(--color-muted)] py-2"
            >
              <template v-if="skill.compilation_status === 'not_compiled'">
                Not yet compiled.  Click "Compile" to extract contracts.
              </template>
              <template v-else-if="skill.compilation_status === 'rejected'">
                Compilation failed — no contracts or templates could be extracted.
              </template>
              <template v-else>
                No contracts or templates extracted.  The skill body may not contain
                parseable procedural units (fenced code blocks, numbered steps, or
                heading sections).
              </template>
            </div>
            <div v-if="skill.compilation_errors.length" class="space-y-1">
              <div class="text-xs font-semibold text-[var(--color-red)] uppercase tracking-wider">Errors</div>
              <div
                v-for="(err, i) in skill.compilation_errors"
                :key="i"
                class="text-xs text-[var(--color-red)] mono bg-[var(--color-red)]/10 rounded px-2 py-1"
              >
                {{ err }}
              </div>
            </div>

            <div v-if="skill.contracts.length" class="space-y-2">
              <div class="text-xs font-semibold text-[var(--color-muted)] uppercase tracking-wider">Contracts</div>
              <div
                v-for="c in skill.contracts"
                :key="c.name"
                class="text-xs bg-[var(--color-grid)] rounded-md border border-[var(--color-border)] px-3 py-2"
              >
                <div class="mono font-medium text-[var(--color-text)]">{{ c.name }}</div>
                <div class="text-[var(--color-muted)] mt-0.5">{{ c.description }}</div>
                <div class="flex flex-wrap gap-x-4 gap-y-1 mt-1.5">
                  <span class="text-[var(--color-muted)]">{{ c.input_count }} inputs</span>
                  <span class="text-[var(--color-muted)]">{{ c.output_count }} outputs</span>
                  <span class="text-[var(--color-muted)]">{{ c.precondition_count }} pre</span>
                  <span class="text-[var(--color-muted)]">{{ c.error_condition_count }} errors</span>
                  <span class="text-[var(--color-muted)]">cancel: {{ c.cancellation_behavior }}</span>
                </div>
              </div>
            </div>

            <div v-if="skill.templates.length" class="space-y-2">
              <div class="text-xs font-semibold text-[var(--color-muted)] uppercase tracking-wider">Templates</div>
              <div
                v-for="t in skill.templates"
                :key="t.name"
                class="text-xs bg-[var(--color-grid)] rounded-md border border-[var(--color-border)] px-3 py-2"
              >
                <div class="mono font-medium text-[var(--color-text)]">{{ t.name }}</div>
                <div class="text-[var(--color-muted)] mt-0.5">[{{ t.kind }}]</div>
                <code class="block mt-1 text-[var(--color-muted)] break-all">{{ t.template_preview }}</code>
              </div>
            </div>

            <div v-if="skill.aliases.length" class="text-xs text-[var(--color-muted)]">
              Aliases: {{ skill.aliases.join(', ') }}
            </div>
          </div>
        </div>
      </div>
      <div v-else class="text-sm text-[var(--color-muted)] py-8 text-center">
        No skills match the current filter.
      </div>
    </Panel>
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, reactive, ref } from 'vue'
import { useSkillsStore, useCompilationProgressStore, patchSkillInStore } from '@/stores/skills'
import { postCompileSkills, postCompileSkill } from '@/api/endpoints'
import { createCompilationStream } from '@/api/compilation-sse'
import type { CompilationEvent } from '@/types/dashboard'
import Panel from '@/components/shared/Panel.vue'

const store = useSkillsStore()
const progress = useCompilationProgressStore()

const expanded = reactive(new Set<string>())
const compiling = ref(false)
const compilingSkill = ref('')
const compileError = ref('')
const filterStatus = ref('')

// Reactive progress counts updated by SSE events (replaces polling progress.data)
const progressCounts = ref({ total: 0, completed: 0, errors: 0, running: false })

let streamHandle: { close: () => void } | null = null

function startCompilationStream() {
  // Pause polling while SSE is active
  progress.pause()

  streamHandle = createCompilationStream(
    (event: CompilationEvent) => {
      switch (event.event) {
        case 'skill_compiled': {
          const { event: _, ...skillData } = event
          patchSkillInStore(store, event.skill_name, skillData)
          break
        }
        case 'compilation_progress':
          progressCounts.value = {
            total: event.total,
            completed: event.completed,
            errors: event.errors,
            running: event.running,
          }
          break
        case 'compilation_done':
          progressCounts.value.running = false
          compiling.value = false
          compilingSkill.value = ''
          // Final reconciliation — catches any events missed during reconnect
          store.fetch()
          streamHandle?.close()
          streamHandle = null
          progress.resume()
          break
        case 'compilation_error':
          progressCounts.value.running = false
          compileError.value = event.detail
          compiling.value = false
          compilingSkill.value = ''
          streamHandle?.close()
          progress.resume()
          break
      }
    },
    (error: string) => {
      compileError.value = error
      progressCounts.value.running = false
      compiling.value = false
      progress.resume()
    },
  )
}

function stopCompilationStream() {
  streamHandle?.close()
  streamHandle = null
  progressCounts.value.running = false
  progress.resume()
}

onUnmounted(() => {
  stopCompilationStream()
})

function toggle(name: string) {
  if (expanded.has(name)) expanded.delete(name)
  else expanded.add(name)
}

async function triggerCompile() {
  compileError.value = ''
  compiling.value = true

  // Connect SSE stream BEFORE posting — ensures we're subscribed
  // when the daemon thread publishes events.  If POST fails, we
  // close the stream in the catch/failure paths.
  startCompilationStream()

  try {
    const res = await postCompileSkills()
    if (res.status === 'started') {
      // Stream already connected, events will arrive
    } else if (res.status === 'already_running') {
      // Stream already connected, will receive events from the
      // already-running compilation. No action needed.
    } else if (res.status === 'error') {
      compileError.value = res.detail ?? 'Unknown error'
      compiling.value = false
      stopCompilationStream()
    } else if (res.status === 'no_skills_found') {
      compileError.value = 'No SKILL.md files found.'
      compiling.value = false
      stopCompilationStream()
    }
  } catch (e: any) {
    compileError.value = e?.message ?? 'Request failed'
    compiling.value = false
    stopCompilationStream()
  }
}

async function compileOne(name: string) {
  compilingSkill.value = name

  // Connect SSE stream BEFORE posting — the daemon thread may
  // finish compiling before the POST response arrives.
  startCompilationStream()

  try {
    const res = await postCompileSkill(name)
    if (res.status === 'started') {
      // Stream already connected, events will arrive
    } else {
      compileError.value = res.detail ?? res.status
      compilingSkill.value = ''
      stopCompilationStream()
    }
  } catch (e: any) {
    compileError.value = e?.message ?? 'Request failed'
    compilingSkill.value = ''
    stopCompilationStream()
  }
}

const counts = computed(() => {
  const skills = store.data ?? []
  return {
    full: skills.filter(s => s.compilation_status === 'full').length,
    partial: skills.filter(s => s.compilation_status === 'partial').length,
    rejected: skills.filter(s => s.compilation_status === 'rejected').length,
    notCompiled: skills.filter(s => s.compilation_status === 'not_compiled').length,
  }
})

const filteredSkills = computed(() => {
  if (!filterStatus.value) return store.data ?? []
  return (store.data ?? []).filter(s => s.compilation_status === filterStatus.value)
})

const pct = computed(() => {
  if (!progressCounts.value.total) return 0
  return Math.round((progressCounts.value.completed / progressCounts.value.total) * 100)
})

function statusDot(status: string): string {
  switch (status) {
    case 'full': return 'bg-[var(--color-green)]'
    case 'partial': return 'bg-[var(--color-yellow)]'
    case 'rejected': return 'bg-[var(--color-red)]'
    default: return 'bg-[var(--color-muted-2)]'
  }
}
</script>
