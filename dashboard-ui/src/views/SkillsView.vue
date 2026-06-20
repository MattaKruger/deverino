<template>
  <div class="p-6 space-y-6 max-w-screen-2xl mx-auto">
    <!-- Compilation Progress -->
    <div
      v-if="progressCounts.running || compiling"
      class="bg-[var(--color-cbg)] border border-[var(--color-blue)]/30 rounded-lg p-4"
    >
      <div class="flex items-center justify-between mb-2">
        <span class="text-sm font-medium text-[var(--color-blue)]">
          Compiling skills&hellip;
        </span>
        <span class="text-xs text-[var(--color-muted)] font-mono">
          {{ progressCounts.completed }} / {{ progressCounts.total }}
          <span v-if="progressCounts.errors > 0" class="text-red-400 ml-2">
            &middot; {{ progressCounts.errors }} errors
          </span>
        </span>
      </div>
      <div class="w-full bg-[var(--color-border)] rounded-full h-2">
        <div
          class="h-2 rounded-full transition-all duration-500"
          :class="progressCounts.errors > 0 ? 'bg-amber-400' : 'bg-[var(--color-blue)]'"
          :style="{ width: pct + '%' }"
        />
      </div>
      <div v-if="compileError" class="mt-2 text-xs text-red-400">{{ compileError }}</div>
    </div>

    <!-- Toolbar -->
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-3">
        <h2 class="text-lg font-semibold">Skills</h2>
        <span class="text-xs text-[var(--color-muted)] font-mono">
          {{ store.data?.length ?? 0 }} total
        </span>
      </div>
      <button
        class="px-4 py-2 rounded text-sm font-medium transition-colors"
        :class="compiling
          ? 'bg-[var(--color-border)] text-[var(--color-muted)] cursor-not-allowed'
          : 'bg-[var(--color-blue)] text-white hover:bg-[var(--color-blue)]/80'"
        :disabled="compiling"
        @click="triggerCompile"
      >
        <span v-if="compiling" class="flex items-center gap-2">
          <svg class="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          Compiling...
        </span>
        <span v-else>Compile All</span>
      </button>
    </div>

    <!-- Summary Cards -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
      <div class="bg-[var(--color-cbg)] border border-[var(--color-border)] rounded-lg p-4 text-center">
        <div class="text-2xl font-mono font-bold text-green-400">{{ counts.full }}</div>
        <div class="text-xs text-[var(--color-muted)] mt-1 uppercase tracking-wider">Full</div>
      </div>
      <div class="bg-[var(--color-cbg)] border border-[var(--color-border)] rounded-lg p-4 text-center">
        <div class="text-2xl font-mono font-bold text-amber-400">{{ counts.partial }}</div>
        <div class="text-xs text-[var(--color-muted)] mt-1 uppercase tracking-wider">Partial</div>
      </div>
      <div class="bg-[var(--color-cbg)] border border-[var(--color-border)] rounded-lg p-4 text-center">
        <div class="text-2xl font-mono font-bold text-red-400">{{ counts.rejected }}</div>
        <div class="text-xs text-[var(--color-muted)] mt-1 uppercase tracking-wider">Rejected</div>
      </div>
      <div class="bg-[var(--color-cbg)] border border-[var(--color-border)] rounded-lg p-4 text-center cursor-pointer hover:border-[var(--color-blue)]/50 transition-colors"
           @click="filterStatus = filterStatus === 'not_compiled' ? '' : 'not_compiled'"
           :class="{ 'border-[var(--color-blue)]/50': filterStatus === 'not_compiled' }">
        <div class="text-2xl font-mono font-bold text-[var(--color-muted)]">{{ counts.notCompiled }}</div>
        <div class="text-xs text-[var(--color-muted)] mt-1 uppercase tracking-wider">Not Compiled</div>
      </div>
    </div>

    <!-- Skill List -->
    <Panel
      title=""
      :loading="store.loading"
      :isStale="store.isStale"
      :error="store.error"
      :last-updated="store.lastFetched"
    >
      <div v-if="filteredSkills.length" class="space-y-1">
        <div
          v-for="skill in filteredSkills"
          :key="skill.name"
          class="border border-[var(--color-border)] rounded-lg"
          :class="{ 'opacity-50': skill.compilation_status === 'not_compiled' }"
        >
          <!-- Row header -->
          <button
            class="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-[var(--color-border)]/30 transition-colors"
            @click="toggle(skill.name)"
          >
            <span
              class="w-2.5 h-2.5 rounded-full shrink-0"
              :class="statusDot(skill.compilation_status)"
            />
            <span class="font-mono text-sm font-medium flex-1">{{ skill.name }}</span>
            <!-- Per-skill compile button -->
            <button
              v-if="skill.compilation_status === 'not_compiled'"
              class="px-2 py-0.5 rounded text-xs transition-colors"
              :class="compilingSkill === skill.name
                ? 'bg-[var(--color-border)] text-[var(--color-muted)] cursor-not-allowed'
                : 'bg-[var(--color-blue)]/20 text-[var(--color-blue)] hover:bg-[var(--color-blue)]/30'"
              :disabled="compilingSkill === skill.name"
              @click.stop="compileOne(skill.name)"
              title="Compile this skill"
            >
              <span v-if="compilingSkill === skill.name" class="inline-block w-3 h-3 border-2 border-[var(--color-muted)] border-t-transparent rounded-full animate-spin" />
              <span v-else>Compile</span>
            </button>
            <button
              v-else
              class="px-2 py-0.5 rounded text-xs transition-colors"
              :class="compilingSkill === skill.name
                ? 'bg-[var(--color-border)] text-[var(--color-muted)] cursor-not-allowed'
                : 'bg-amber-500/20 text-amber-400 hover:bg-amber-500/30'"
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
          <div v-if="expanded.has(skill.name)" class="border-t border-[var(--color-border)] px-4 py-3 space-y-3 bg-[var(--color-cbg)]/50">
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
              <div class="text-xs font-semibold text-red-400 uppercase tracking-wider">Errors</div>
              <div
                v-for="(err, i) in skill.compilation_errors"
                :key="i"
                class="text-xs text-red-300 font-mono bg-red-950/30 rounded px-2 py-1"
              >
                {{ err }}
              </div>
            </div>

            <div v-if="skill.contracts.length" class="space-y-2">
              <div class="text-xs font-semibold text-[var(--color-muted)] uppercase tracking-wider">Contracts</div>
              <div
                v-for="c in skill.contracts"
                :key="c.name"
                class="text-xs bg-[var(--color-border)]/30 rounded px-3 py-2"
              >
                <div class="font-mono font-medium text-[var(--color-text-primary)]">{{ c.name }}</div>
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
                class="text-xs bg-[var(--color-border)]/30 rounded px-3 py-2"
              >
                <div class="font-mono font-medium text-[var(--color-text-primary)]">{{ t.name }}</div>
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
    case 'full': return 'bg-green-400'
    case 'partial': return 'bg-amber-400'
    case 'rejected': return 'bg-red-400'
    default: return 'bg-gray-500'
  }
}
</script>
