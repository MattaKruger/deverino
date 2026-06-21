<template>
  <div class="view-shell view-stack">
    <header class="page-header">
      <div class="page-heading">
        <div class="page-kicker">Institutional knowledge</div>
        <h1 class="page-title">Project State</h1>
        <p class="page-subtitle">
          Durable decisions, constraints, facts, and session proposals that persist across sessions.
        </p>
      </div>
    </header>

    <div v-if="store.loading" class="text-sm text-[var(--color-muted)] p-4">Loading...</div>
    <div v-else-if="store.error" class="text-sm text-[var(--color-red)] p-4">{{ store.error }}</div>

    <template v-else>
      <!-- Pending proposals alert -->
      <div
        v-if="store.proposals.length"
        class="mb-4 p-4 rounded-lg border border-[var(--color-purple)]/35 bg-[var(--color-purple)]/10"
      >
        <div class="flex items-center justify-between">
          <span class="text-sm font-medium text-[var(--color-purple)]">
            {{ store.proposals.length }} pending state proposal{{ store.proposals.length !== 1 ? 's' : '' }}
          </span>
          <span class="text-xs text-[var(--color-muted)]">
            Use the REPL: <code class="code-pill">state approve &lt;id&gt;</code>
          </span>
        </div>
        <div class="mt-2 space-y-1">
          <div
            v-for="p in store.proposals.slice(0, 5)"
            :key="p.proposal_id"
            class="text-xs text-[var(--color-muted)]"
          >
            <span class="font-mono text-[var(--color-text)]">{{ p.proposal_id.slice(0, 8) }}</span>
            <span class="ml-2">session {{ p.session_id.slice(0, 8) }}</span>
            <span class="ml-2">{{ p.created_at }}</span>
          </div>
        </div>
      </div>

      <!-- Project State -->
      <section v-if="store.projectState" class="space-y-6">
        <!-- Summary -->
        <div class="card">
          <h3 class="panel-header">Summary</h3>
          <p class="text-sm text-[var(--color-text)]">
            {{ store.projectState.summary || 'No summary yet.' }}
          </p>
        </div>

        <!-- Facts -->
        <div class="card">
          <h3 class="panel-header">Facts</h3>
          <div v-if="factEntries.length" class="grid grid-cols-2 gap-2">
            <div
              v-for="[k, v] in factEntries"
              :key="k"
              class="flex items-baseline gap-2 px-3 py-1.5 rounded bg-[var(--color-bg)]"
            >
              <span class="text-xs font-mono text-[var(--color-blue)]">{{ k }}</span>
              <span class="text-xs text-[var(--color-muted)]">{{ v }}</span>
            </div>
          </div>
          <p v-else class="text-xs text-[var(--color-muted)]">No facts set.</p>
        </div>

        <!-- Constraints -->
        <div class="card">
          <h3 class="panel-header">Constraints</h3>
          <ul v-if="store.projectState.constraints.length" class="space-y-1">
            <li
              v-for="(c, i) in store.projectState.constraints"
              :key="i"
              class="text-sm text-[var(--color-yellow)]"
            >{{ c }}</li>
          </ul>
          <p v-else class="text-xs text-[var(--color-muted)]">No constraints.</p>
        </div>

        <!-- Decisions -->
        <div class="card">
          <h3 class="panel-header">Decisions</h3>
          <ul v-if="store.projectState.decisions.length" class="space-y-1">
            <li
              v-for="(d, i) in store.projectState.decisions"
              :key="i"
              class="text-sm text-[var(--color-text)]"
            >{{ d }}</li>
          </ul>
          <p v-else class="text-xs text-[var(--color-muted)]">No decisions.</p>
        </div>

        <!-- Notes -->
        <div class="card">
          <h3 class="panel-header">Notes</h3>
          <ul v-if="store.projectState.notes.length" class="space-y-1">
            <li
              v-for="(n, i) in store.projectState.notes"
              :key="i"
              class="text-sm text-[var(--color-muted)]"
            >{{ n }}</li>
          </ul>
          <p v-else class="text-xs text-[var(--color-muted)]">No notes.</p>
        </div>

        <!-- Next Actions -->
        <div class="card">
          <h3 class="panel-header">Next Actions</h3>
          <ul v-if="store.projectState.next_actions.length" class="space-y-1">
            <li
              v-for="(a, i) in store.projectState.next_actions"
              :key="i"
              class="text-sm text-[var(--color-green)]"
            >{{ a }}</li>
          </ul>
          <p v-else class="text-xs text-[var(--color-muted)]">No next actions.</p>
        </div>
      </section>

      <!-- State Events -->
      <section class="mt-6">
        <h2 class="panel-header">Recent Events</h2>
        <div v-if="store.events.length" class="card">
          <div class="space-y-1">
            <div
              v-for="e in store.events"
              :key="e.id"
              class="flex items-start gap-3 text-xs py-1"
            >
              <span class="font-mono text-[var(--color-muted)] shrink-0 w-20">
                {{ e.created_at }}
              </span>
              <span
                class="px-1.5 py-0.5 rounded font-mono text-[11px] shrink-0"
                :class="scopeBadgeClass(e.scope)"
              >{{ e.scope === 'session' ? 'SESS' : 'PROJ' }}</span>
              <span class="text-[var(--color-text)]">{{ e.event_type }}</span>
              <span class="text-[var(--color-muted)] truncate">{{ eventDetail(e) }}</span>
            </div>
          </div>
        </div>
        <p v-else class="text-xs text-[var(--color-muted)] p-4">No events yet.</p>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useStateStore } from '@/stores/state'
import type { StateEvent } from '@/types/dashboard'

const store = useStateStore()

const factEntries = computed(() => {
  if (!store.projectState?.facts) return []
  return Object.entries(store.projectState.facts).sort(([a], [b]) => a.localeCompare(b))
})

function scopeBadgeClass(scope: string) {
  return scope === 'session'
    ? 'bg-[var(--color-blue)]/20 text-[var(--color-blue)]'
    : 'bg-[var(--color-purple)]/20 text-[var(--color-purple)]'
}

function eventDetail(e: StateEvent): string {
  const inner = (e.payload as Record<string, unknown> | null)?.payload as Record<string, unknown> | undefined
  if (!inner) return ''
  if (typeof inner.text === 'string') return inner.text.slice(0, 60)
  if (typeof inner.key === 'string') return `${inner.key}=${inner.value ?? ''}`
  if (typeof inner.proposal_id === 'string') return inner.proposal_id.slice(0, 8)
  return ''
}

onMounted(() => {
  store.loadAll()
})
</script>
