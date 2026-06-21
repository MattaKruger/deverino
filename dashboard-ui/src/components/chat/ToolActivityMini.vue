<template>
  <div v-if="sessionId" class="card tool-activity-mini">
    <div class="tool-activity-mini__header">
      <div class="panel-header">Tools &amp; Skills</div>
      <span class="tool-activity-mini__count">{{ activity.length }}</span>
    </div>

    <div v-if="!store.data" class="text-xs text-[var(--color-muted)]">Loading...</div>
    <div v-else-if="!activity.length" class="text-xs text-[var(--color-muted)]">
      No tool or skill activity yet
    </div>
    <div v-else>
      <div class="tool-activity-mini__stats">
        <div>
          <span>{{ startedCount }}</span>
          <small>started</small>
        </div>
        <div>
          <span>{{ completedCount }}</span>
          <small>done</small>
        </div>
        <div>
          <span>{{ errorCount }}</span>
          <small>errors</small>
        </div>
      </div>

      <div class="tool-activity-mini__list">
        <div
          v-for="item in activity.slice(0, 12)"
          :key="item.id"
          class="tool-activity-mini__row"
        >
          <span class="tool-activity-mini__status" :class="`tool-activity-mini__status--${item.tone}`" />
          <div class="min-w-0 flex-1">
            <div class="truncate font-mono text-[11px] text-[var(--color-text)]">
              {{ item.name }}
            </div>
            <div class="truncate text-[10px] uppercase tracking-[0.08em] text-[var(--color-muted-2)]">
              {{ item.label }}
            </div>
          </div>
          <span class="tool-activity-mini__time">{{ item.time }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useFirehoseStore } from '@/stores/firehose'
import type { UnifiedEvent } from '@/types/dashboard'

const props = defineProps<{ sessionId: string | null }>()

const store = useFirehoseStore()

type ActivityTone = 'running' | 'success' | 'error'

interface ToolActivity {
  id: string
  name: string
  label: string
  tone: ActivityTone
  time: string
}

const activity = computed(() =>
  (store.data ?? [])
    .filter(e => e.session_id === props.sessionId)
    .map(toActivity)
    .filter((item): item is ToolActivity => item !== null),
)

const startedCount = computed(() => activity.value.filter(item => item.label !== 'completed').length)
const completedCount = computed(() => activity.value.filter(item => item.tone === 'success').length)
const errorCount = computed(() => activity.value.filter(item => item.tone === 'error').length)

function toActivity(event: UnifiedEvent): ToolActivity | null {
  if (!['SkillCalled', 'SkillRequested', 'SkillCompleted'].includes(event.event_type)) {
    return null
  }

  const detail = parseDetail(event.detail_json)
  const name = readName(detail)
  if (!name) return null

  const status = String(detail.status ?? '')
  const label = event.event_type === 'SkillCompleted' ? 'completed' : 'started'
  const tone = event.event_type === 'SkillCompleted'
    ? status && status !== 'success'
      ? 'error'
      : 'success'
    : 'running'

  return {
    id: event.event_id,
    name,
    label,
    tone,
    time: formatTime(event.timestamp),
  }
}

function parseDetail(raw: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : {}
  } catch {
    return {}
  }
}

function readName(detail: Record<string, unknown>): string {
  const value = detail.skill_name ?? detail.tool_name
  return typeof value === 'string' ? value : ''
}

function formatTime(raw: string): string {
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}
</script>
