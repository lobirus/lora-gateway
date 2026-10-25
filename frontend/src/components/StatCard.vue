<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ label: string; value: string; delta?: number | null; invert?: boolean; hint?: string; loading?: boolean; icon?: unknown; tone?: string }>()
// > +999% means the previous period was ~empty: say "new" instead of an absurd percentage
const deltaText = computed(() => {
  const d = props.delta
  if (d == null) return ''
  if (d >= 10) return 'new'
  return (d >= 0 ? '+' : '−') + Math.round(Math.abs(d) * 100).toLocaleString('en-US') + '%'
})
const exact = computed(() => (props.delta == null ? undefined : (props.delta >= 0 ? '+' : '−') + Math.round(Math.abs(props.delta) * 100).toLocaleString('en-US') + '% vs previous period'))
const good = computed(() => (props.delta == null ? null : props.invert ? props.delta < 0 : props.delta > 0))
</script>

<template>
  <div class="card stat">
    <div class="top">
      <span class="label">{{ label }}</span>
    </div>
    <div v-if="loading" class="skeleton" style="height: 26px; width: 60%; margin-top: 8px" />
    <div v-else class="value">{{ value }}</div>
    <div class="foot">
      <span v-if="delta != null" class="delta" :class="good ? 'up' : 'down'" :title="exact">
{{ deltaText }}
      </span>
      <span class="hint">{{ hint }}</span>
    </div>
  </div>
</template>

<style scoped>
.stat { padding: 14px 16px 12px; min-width: 0; }
.top { display: flex; align-items: center; justify-content: space-between; }
.label { font-size: 12.5px; font-weight: 500; color: var(--text-2); }
.value { font-size: 24px; font-weight: 600; letter-spacing: -.03em; margin-top: 8px; line-height: 1.15; font-variant-numeric: tabular-nums; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.foot { display: flex; flex-wrap: wrap; align-items: baseline; gap: 2px 6px; margin-top: 6px; min-height: 18px; }
.delta { display: inline-flex; align-items: center; gap: 2px; font: 500 11.5px var(--font); font-variant-numeric: tabular-nums; }
.delta svg { width: 12px; height: 12px; align-self: center; }
.delta.up { color: var(--success); }
.delta.down { color: var(--danger); }
.hint { font-size: 11.5px; color: var(--text-3); min-width: 0; }
</style>
