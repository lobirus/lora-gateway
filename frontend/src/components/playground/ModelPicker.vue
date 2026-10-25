<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ChevronDown, Search, Eye, Star, Zap, Brain, Check, Tag } from 'lucide-vue-next'
import type { PgModel } from '../../playground'
import { fmtPrice } from '../../format'

const props = defineProps<{ modelValue: string; models: PgModel[]; compact?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [v: string] }>()
const open = ref(false)
const q = ref('')
const root = ref<HTMLElement | null>(null)
const searchEl = ref<HTMLInputElement | null>(null)
const aliasIcon: Record<string, unknown> = { default: Star, fast: Zap, smart: Brain, vision: Eye }

const current = computed(() => props.models.find((m) => m.name === props.modelValue))
const reason = (m: PgModel) => (m.live ? '' : !m.provider_name ? 'No target' : !m.provider_enabled ? 'Provider disabled' : !m.enabled ? 'Model disabled' : 'No API key')
const groups = computed(() => {
  const s = q.value.trim().toLowerCase()
  const match = (m: PgModel) => !s || [m.name, m.display_name, m.target, m.upstream_id, m.provider_name].some((x) => x?.toLowerCase().includes(s))
  const out: { label: string; items: PgModel[] }[] = []
  const al = props.models.filter((m) => m.kind === 'alias' && match(m))
  if (al.length) out.push({ label: 'Aliases', items: al })
  const byProv = new Map<string, PgModel[]>()
  for (const m of props.models) if (m.kind === 'model' && match(m)) byProv.set(m.provider_name || '?', [...(byProv.get(m.provider_name || '?') || []), m])
  // live providers first, keep original order otherwise
  const entries = [...byProv.entries()].sort((a, b) => Number(b[1].some((m) => m.live)) - Number(a[1].some((m) => m.live)))
  for (const [label, items] of entries) out.push({ label, items: [...items].sort((a, b) => Number(b.live) - Number(a.live)) })
  return out
})
const flat = computed(() => groups.value.flatMap((g) => g.items).filter((m) => m.live))

const active = ref(0)
const triggerEl = ref<HTMLButtonElement>()
const listId = 'mp-' + Math.random().toString(36).slice(2, 8)
watch(q, () => (active.value = 0))
function toggle() {
  open.value = !open.value
  if (open.value) {
    q.value = ''
    nextTick(() => { active.value = Math.max(0, flat.value.findIndex((m) => m.name === props.modelValue)); searchEl.value?.focus(); scrollActive() })
  }
}
function close(refocus = true) { open.value = false; if (refocus) nextTick(() => triggerEl.value?.focus()) }
function scrollActive() { nextTick(() => root.value?.querySelector('.opt.kb')?.scrollIntoView({ block: 'nearest' })) }
function pick(m: PgModel) {
  if (!m.live) return
  emit('update:modelValue', m.name)
  close()
}
function onKey(e: KeyboardEvent) {
  const n = flat.value.length
  if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close() }
  else if (e.key === 'Tab') { close(false) }
  else if (e.key === 'ArrowDown' && n) { e.preventDefault(); active.value = (active.value + 1) % n; scrollActive() }
  else if (e.key === 'ArrowUp' && n) { e.preventDefault(); active.value = (active.value - 1 + n) % n; scrollActive() }
  else if (e.key === 'Home' && n) { e.preventDefault(); active.value = 0; scrollActive() }
  else if (e.key === 'End' && n) { e.preventDefault(); active.value = n - 1; scrollActive() }
  else if (e.key === 'Enter' && n) { e.preventDefault(); pick(flat.value[Math.min(active.value, n - 1)]) }
}
function onTriggerKey(e: KeyboardEvent) {
  if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && !open.value) { e.preventDefault(); toggle() }
}
const onDoc = (e: MouseEvent) => { if (open.value && root.value && !root.value.contains(e.target as Node)) open.value = false }
onMounted(() => document.addEventListener('mousedown', onDoc))
onBeforeUnmount(() => document.removeEventListener('mousedown', onDoc))
</script>

<template>
  <div ref="root" class="picker" :class="{ compact }">
    <button ref="triggerEl" type="button" class="trigger input" :class="{ open }" @click="toggle" @keydown="onTriggerKey" :aria-expanded="open" aria-haspopup="listbox" :aria-controls="open ? listId : undefined" :aria-label="'Model: ' + (modelValue || 'none selected')">
      <component :is="aliasIcon[modelValue] || Tag" v-if="current?.kind === 'alias'" :size="14" class="ic" />
      <span class="name mono">{{ modelValue || 'Select a model' }}</span>
      <span v-if="current?.kind === 'alias' && current.target" class="tgt muted">→ {{ current.target }}</span>
      <span class="spacer" />
      <span v-if="current?.provider_name && !compact" class="badge prov">{{ current.provider_name }}</span>
      <Eye v-if="current?.vision" :size="14" class="vis" title="Accepts images" />
      <ChevronDown :size="16" class="chev" />
    </button>
    <div v-if="open" class="pop" @keydown="onKey">
      <div class="search"><Search :size="14" /><input ref="searchEl" v-model="q" class="input" placeholder="Search models, aliases, providers" role="combobox" aria-autocomplete="list" :aria-expanded="true" :aria-controls="listId" :aria-activedescendant="flat[active] ? listId + '-' + flat[active].name : undefined" aria-label="Search models" /></div>
      <div :id="listId" class="list" role="listbox" aria-label="Models">
        <div v-for="g in groups" :key="g.label" class="grp">
          <div class="grp-h">{{ g.label }}</div>
          <button v-for="m in g.items" :key="m.name" type="button" :id="listId + '-' + m.name" tabindex="-1" class="opt" :class="{ sel: m.name === modelValue, off: !m.live, kb: m.live && flat[active]?.name === m.name }" :disabled="!m.live" role="option" :aria-selected="m.name === modelValue" @click="pick(m)" :title="m.live ? m.upstream_id || '' : reason(m)">
            <component :is="aliasIcon[m.name] || Tag" v-if="m.kind === 'alias'" :size="14" class="oic" />
            <div class="o-main">
              <div class="o-name"><span class="mono">{{ m.name }}</span><Eye v-if="m.vision" :size="14" class="vis" /></div>
              <div class="o-sub">
                <template v-if="m.kind === 'alias'">→ {{ m.target || 'unassigned' }}<template v-if="m.provider_name"> · {{ m.provider_name }}</template></template>
                <template v-else>{{ m.display_name }}<template v-if="m.input_price_per_m || m.output_price_per_m"> · {{ fmtPrice(m.input_price_per_m) }} / {{ fmtPrice(m.output_price_per_m) }} per 1M</template></template>
              </div>
            </div>
            <span v-if="!m.live" class="badge off-b">{{ reason(m) }}</span>
            <Check v-else-if="m.name === modelValue" :size="15" class="ck" />
          </button>
        </div>
        <div v-if="!groups.length" class="none muted">No models match “{{ q }}”</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.picker { position: relative; min-width: 0; }
.trigger { display: flex; align-items: center; gap: 8px; cursor: pointer; text-align: left; min-width: 0; }
.trigger.open { border-color: var(--focus); box-shadow: 0 0 0 1px var(--focus); }
.trigger .ic { color: var(--text-3); flex-shrink: 0; }
.name { font-weight: 500; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tgt { font: 11.5px var(--font); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.compact .tgt { display: none; }
.prov { height: 20px; font-size: 11px; }
.vis { color: var(--text-3); flex-shrink: 0; }
.chev { color: var(--text-3); flex-shrink: 0; }
.pop { position: absolute; z-index: 60; top: calc(100% + 6px); left: 0; width: max(100%, 360px); max-width: calc(100vw - 32px); background: var(--bg-elev); border: 1px solid var(--border-strong); border-radius: var(--radius); box-shadow: var(--shadow-lg); overflow: hidden; animation: pop .12s var(--ease); }
.search { position: relative; padding: 10px; border-bottom: 1px solid var(--border); }
.search svg { position: absolute; left: 20px; top: 19px; color: var(--text-3); }
.search .input { padding-left: 31px; height: 32px; }
.list { max-height: 380px; overflow-y: auto; padding: 4px 6px 8px; }
.grp-h { font-size: 11.5px; color: var(--text-3); font-weight: 500; padding: 10px 8px 4px; }
.opt { display: flex; align-items: center; gap: 10px; width: 100%; border: 0; background: transparent; color: var(--text); padding: 6px 8px; border-radius: var(--radius-sm); cursor: pointer; text-align: left; font: inherit; }
.opt:hover:not(:disabled) { background: var(--bg-hover); }
.opt.kb { background: var(--bg-hover); box-shadow: inset 0 0 0 1px var(--focus); }
.opt.sel { background: var(--bg-subtle); box-shadow: inset 2px 0 0 var(--primary); }
.opt.off { opacity: .45; cursor: not-allowed; }
.oic { color: var(--text-3); flex-shrink: 0; }
.o-main { flex: 1; min-width: 0; }
.o-name { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 500; }
.o-sub { font: 11px var(--font); color: var(--text-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.off-b { height: 20px; font-size: 10.5px; }
.ck { color: var(--primary); flex-shrink: 0; }
.none { padding: 18px; text-align: center; font-size: 13px; }
@media (max-width: 600px) { .tgt, .prov { display: none; } }
@keyframes pop { from { opacity: 0; transform: translateY(-4px); } }
</style>
