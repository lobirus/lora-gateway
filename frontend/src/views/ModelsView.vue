<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Plus, Play, Pencil, Trash2, Loader2, Search, ArrowRightLeft, Boxes, Star, Zap, Brain, Eye, Tag, CheckCircle2, XCircle, CloudDownload } from 'lucide-vue-next'
import { api } from '../api'
import type { Alias, Model, Provider, TestResult } from '../types'
import { fmtCtx, fmtMs, fmtPrice } from '../format'
import { ok, fail, toast } from '../stores/toast'
import Modal from '../components/Modal.vue'
import Toggle from '../components/Toggle.vue'
import EmptyState from '../components/EmptyState.vue'
import CopyButton from '../components/CopyButton.vue'

const route = useRoute()
const models = ref<Model[]>([])
const aliases = ref<Alias[]>([])
const providers = ref<Provider[]>([])
const loading = ref(true)
const q = ref('')
const prov = ref((route.query.provider as string) || '')
const onlyLive = ref(false)

async function load() {
  try {
    const [m, a, p] = await Promise.all([api.get<Model[]>('/api/models'), api.get<Alias[]>('/api/aliases'), api.get<Provider[]>('/api/providers')])
    models.value = m; aliases.value = a; providers.value = p
  } catch (e) { fail('Could not load models', e) } finally { loading.value = false }
}
onMounted(load)

const filtered = computed(() => models.value.filter((m) =>
  (!prov.value || m.provider_slug === prov.value) && (!onlyLive.value || m.live) &&
  (!q.value || (m.model_name + m.upstream_id + m.display_name).toLowerCase().includes(q.value.toLowerCase()))))
const liveModels = computed(() => models.value.filter((m) => m.live))
const aliasIcon: Record<string, unknown> = { default: Star, fast: Zap, smart: Brain, vision: Eye }

function syncNote(s?: { ok: boolean; error?: string }) { if (s && !s.ok) toast('error', 'Gateway sync failed', s.error) }

// aliases
const aliasBusy = reactive<Record<number, boolean>>({})
async function switchAlias(a: Alias, targetId: number) {
  aliasBusy[a.id] = true
  try {
    const r = await api.patch<{ sync: { ok: boolean; error?: string } }>(`/api/aliases/${a.id}`, { target_model_id: targetId })
    syncNote(r.sync)
    const t = models.value.find((m) => m.id === targetId)
    ok(`"${a.name}" now points to ${t?.display_name}`, 'Clients using this alias switch immediately')
    await load()
  } catch (e) { fail('Switch failed', e) } finally { delete aliasBusy[a.id] }
}
const showAlias = ref(false)
const aliasForm = reactive({ name: '', target_model_id: 0, description: '' })
async function createAlias() {
  try {
    const r = await api.post<{ sync: { ok: boolean } }>('/api/aliases', { ...aliasForm, target_model_id: aliasForm.target_model_id || null })
    syncNote(r.sync); ok(`Alias "${aliasForm.name}" created`); showAlias.value = false; await load()
  } catch (e) { fail('Create failed', e) }
}
async function deleteAlias(a: Alias) {
  if (!confirm(`Delete alias "${a.name}"? Clients using it will get errors.`)) return
  try { await api.del(`/api/aliases/${a.id}`); ok('Alias deleted'); await load() } catch (e) { fail('Delete failed', e) }
}

// models
const busy = reactive<Record<number, string>>({})
const results = reactive<Record<number, TestResult>>({})
async function toggleModel(m: Model, v: boolean) {
  busy[m.id] = 'toggle'
  try { const r = await api.patch<{ sync: { ok: boolean } }>(`/api/models/${m.id}`, { enabled: v }); syncNote(r.sync); await load() } catch (e) { fail('Update failed', e) } finally { delete busy[m.id] }
}
async function testModel(m: Model) {
  busy[m.id] = 'test'
  try {
    const r = await api.post<TestResult>(`/api/models/${m.id}/test`, { prompt: 'Reply with a one-sentence greeting.', max_tokens: 400 })
    results[m.id] = r
    toast(r.ok ? 'success' : 'error', r.ok ? `${m.display_name}: ${fmtMs(r.latency_ms)}` : `${m.display_name} failed`, r.ok ? (r.output || `(reasoning only, ${r.reasoning_chars} chars)`).slice(0, 140) : r.error || '')
  } catch (e) { fail('Test failed', e) } finally { delete busy[m.id] }
}
async function testAll() {
  for (const m of filtered.value.filter((x) => x.live)) await testModel(m)
}

const editing = ref<Model | null>(null)
const creating = ref(false)
type Tri = 'auto' | 'yes' | 'no'
const EFFORTS = ['off', 'low', 'medium', 'high'] as const
const form = reactive({ provider_id: 0, model_name: '', upstream_id: '', display_name: '', input_price_per_m: 0, output_price_per_m: 0, context_window: null as number | null, enabled: true,
  max_output_tokens: null as number | null, default_max_tokens: null as number | null, reasoning: 'auto' as Tri, vision: 'auto' as Tri, reasoning_efforts: [] as Model['reasoning_efforts'] })
const toTri = (v: boolean | null | undefined): Tri => (v === true ? 'yes' : v === false ? 'no' : 'auto')
const fromTri = (v: Tri) => (v === 'yes' ? true : v === 'no' ? false : null)
const intOrNull = (v: unknown) => { const n = parseInt(String(v ?? '').replace(/[\s,.]/g, ''), 10); return Number.isFinite(n) && n > 0 ? n : null }
const capsPayload = () => ({ max_output_tokens: intOrNull(form.max_output_tokens), default_max_tokens: intOrNull(form.default_max_tokens),
  supports_reasoning: fromTri(form.reasoning), supports_vision: fromTri(form.vision), reasoning_efforts: [...form.reasoning_efforts] })
function toggleEffort(e: (typeof EFFORTS)[number]) {
  const i = form.reasoning_efforts.indexOf(e)
  if (i >= 0) form.reasoning_efforts.splice(i, 1); else form.reasoning_efforts = EFFORTS.filter((x) => x === e || form.reasoning_efforts.includes(x))
}
function openEdit(m: Model) {
  editing.value = m
  Object.assign(form, { provider_id: m.provider_id, model_name: m.model_name, upstream_id: m.upstream_id, display_name: m.display_name, input_price_per_m: m.input_price_per_m, output_price_per_m: m.output_price_per_m, context_window: m.context_window, enabled: m.enabled,
    max_output_tokens: m.max_output_tokens, default_max_tokens: m.default_max_tokens, reasoning: toTri(m.supports_reasoning), vision: toTri(m.supports_vision), reasoning_efforts: [...(m.reasoning_efforts || [])] })
}
function openCreate() {
  creating.value = true
  upstream.value = []
  const p = providers.value.find((x) => x.slug === prov.value) || providers.value.find((x) => x.status === 'active') || providers.value[0]
  Object.assign(form, { provider_id: p?.id || 0, model_name: '', upstream_id: '', display_name: '', input_price_per_m: 0, output_price_per_m: 0, context_window: null, enabled: true,
    max_output_tokens: null, default_max_tokens: null, reasoning: 'auto', vision: 'auto', reasoning_efforts: [] })
}
function close() { editing.value = null; creating.value = false }
const saving = ref(false)
async function save() {
  saving.value = true
  try {
    if (editing.value) {
      const r = await api.patch<{ sync: { ok: boolean } }>(`/api/models/${editing.value.id}`, { model_name: form.model_name, upstream_id: form.upstream_id, display_name: form.display_name, input_price_per_m: +form.input_price_per_m, output_price_per_m: +form.output_price_per_m, context_window: form.context_window ? +form.context_window : null, enabled: form.enabled, ...capsPayload() })
      syncNote(r.sync); ok('Model updated', 'Pricing applies to new requests')
    } else {
      const { reasoning: _r, vision: _v, ...base } = form
      const r = await api.post<{ sync: { ok: boolean } }>('/api/models', { ...base, input_price_per_m: +form.input_price_per_m, output_price_per_m: +form.output_price_per_m, context_window: form.context_window ? +form.context_window : null, ...capsPayload() })
      syncNote(r.sync); ok('Model added')
    }
    close(); await load()
  } catch (e) { fail('Save failed', e) } finally { saving.value = false }
}
async function remove(m: Model) {
  if (!confirm(`Delete model ${m.model_name}?`)) return
  try { await api.del(`/api/models/${m.id}`); ok('Model deleted'); await load() } catch (e) { fail('Delete failed', e) }
}

// upstream discovery
interface Up { id: string; name: string; type: string | null; context_length: number | null; input_price_per_m: number | null; output_price_per_m: number | null }
const upstream = ref<Up[]>([])
const upLoading = ref(false)
const upQ = ref('')
async function discover() {
  upLoading.value = true
  try { upstream.value = await api.get<Up[]>(`/api/providers/${form.provider_id}/upstream-models`) } catch (e) { fail('Discovery failed', e) } finally { upLoading.value = false }
}
const upFiltered = computed(() => upstream.value.filter((u) => !upQ.value || (u.id + u.name).toLowerCase().includes(upQ.value.toLowerCase())).slice(0, 60))
function pick(u: Up) {
  form.upstream_id = u.id
  form.display_name = u.name
  form.model_name = u.id.split('/').pop()!.toLowerCase()
  if (u.input_price_per_m != null) form.input_price_per_m = u.input_price_per_m
  if (u.output_price_per_m != null) form.output_price_per_m = u.output_price_per_m
  if (u.context_length) form.context_window = u.context_length
}
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1>Models &amp; aliases</h1>
        <p>Point stable aliases at any model in one click. Prices drive cost tracking (USD per 1M tokens).</p>
      </div>
      <div class="toolbar">
        <button class="btn" @click="showAlias = true; Object.assign(aliasForm, { name: '', target_model_id: liveModels[0]?.id || 0, description: '' })"><Tag /> New alias</button>
        <button class="btn btn-primary" @click="openCreate"><Plus /> Add model</button>
      </div>
    </div>

    <h2 class="section">Aliases</h2>
    <div class="aliases">
      <div v-for="a in aliases" :key="a.id" class="card alias">
        <div class="ahead">
          <span class="aic"><component :is="aliasIcon[a.name] || Tag" :size="15" :stroke-width="1.6" /></span>
          <div class="aname"><span class="mono">{{ a.name }}</span><span class="muted">{{ a.description }}</span></div>
          <span v-if="a.live" class="badge badge-success"><span class="dot" />Live</span>
          <span v-else class="badge badge-warning"><span class="dot" />Inactive</span>
        </div>
        <label class="label" style="margin-top: 12px; display: flex; align-items: center; gap: 6px"><ArrowRightLeft :size="14" /> Routes to</label>
        <div class="row" style="margin-top: 6px">
          <select class="input" :aria-label="'Model for alias ' + a.name" :value="a.target_model_id ?? ''" :disabled="aliasBusy[a.id]" @change="switchAlias(a, +($event.target as HTMLSelectElement).value)">
            <option v-if="!a.target_model_id" value="">— choose a model —</option>
            <optgroup v-for="p in providers.filter((p) => models.some((m) => m.provider_id === p.id))" :key="p.id" :label="p.name + (p.status === 'active' ? '' : ' (inactive)')">
              <option v-for="m in models.filter((m) => m.provider_id === p.id)" :key="m.id" :value="m.id" :disabled="!m.live">{{ m.display_name }}</option>
            </optgroup>
          </select>
          <Loader2 v-if="aliasBusy[a.id]" class="spin" :size="16" />
          <button class="btn btn-ghost btn-icon btn-sm" title="Delete alias" :aria-label="'Delete alias ' + a.name" @click="deleteAlias(a)"><Trash2 /></button>
        </div>
        <div v-if="a.target" class="atarget muted">{{ a.target.provider_name }} · {{ fmtPrice(a.target.input_price_per_m) }} in / {{ fmtPrice(a.target.output_price_per_m) }} out</div>
      </div>
    </div>

    <div class="card" style="margin-top: 24px">
      <div class="card-header">
        <div><h3>Model catalog</h3><div class="sub">{{ liveModels.length }} live of {{ models.length }} configured</div></div>
        <div class="toolbar">
          <div class="search"><Search :size="14" /><input v-model="q" class="input" placeholder="Search models" /></div>
          <select v-model="prov" class="input" style="width: 170px"><option value="">All providers</option><option v-for="p in providers" :key="p.id" :value="p.slug">{{ p.name }}</option></select>
          <label class="row" style="gap: 8px; font-size: 13px"><Toggle v-model="onlyLive" /> Live only</label>
          <button class="btn btn-sm" @click="testAll"><Play /> Test all live</button>
        </div>
      </div>
      <div v-if="loading" class="card-body"><div v-for="i in 5" :key="i" class="skeleton" style="height: 36px; margin-bottom: 8px" /></div>
      <EmptyState v-else-if="!filtered.length" :icon="Boxes" title="No models match" description="Try a different filter or add a model." />
      <div v-else class="table-wrap">
        <table class="table">
          <thead><tr><th>Model</th><th>Provider</th><th>Upstream ID</th><th class="num">Input / 1M</th><th class="num">Output / 1M</th><th class="num">Context</th><th>Status</th><th>Last test</th><th style="width: 1%"></th></tr></thead>
          <tbody>
            <tr v-for="m in filtered" :key="m.id">
              <td><div class="mname clip" :title="m.display_name">{{ m.display_name }}</div><div class="row" style="gap: 4px"><span class="mono muted clip" :title="m.model_name">{{ m.model_name }}</span><CopyButton :text="m.model_name" class="tiny" /></div></td>
              <td>{{ m.provider_name }}</td>
              <td class="mono muted" style="max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap" :title="m.upstream_id">{{ m.upstream_id }}</td>
              <td class="num">{{ fmtPrice(m.input_price_per_m) }}</td>
              <td class="num">{{ fmtPrice(m.output_price_per_m) }}</td>
              <td class="num">{{ fmtCtx(m.context_window) }}</td>
              <td>
                <div class="row" style="gap: 8px">
                  <Toggle :model-value="m.enabled" :disabled="!!busy[m.id]" :aria-label="'Enable ' + m.display_name" @update:model-value="(v: boolean) => toggleModel(m, v)" />
                  <span v-if="m.live" class="badge badge-success">Live</span>
                  <span v-else-if="m.enabled && !m.provider_enabled" class="badge" title="Provider disabled or missing API key">Provider off</span>
                  <span v-else class="badge">Off</span>
                </div>
              </td>
              <td>
                <span v-if="results[m.id]?.ok" class="ok" :title="results[m.id].output"><CheckCircle2 :size="14" /> {{ fmtMs(results[m.id].latency_ms) }}<span v-if="results[m.id].ttft_ms" class="muted"> · TTFT {{ fmtMs(results[m.id].ttft_ms) }}</span></span>
                <span v-else-if="results[m.id]" class="bad" :title="results[m.id].error || ''"><XCircle :size="14" /> failed</span>
                <span v-else class="muted">—</span>
              </td>
              <td>
                <div class="row" style="gap: 4px">
                  <button class="btn btn-sm" :disabled="!m.live || !!busy[m.id]" :aria-label="'Test ' + m.display_name" @click="testModel(m)"><Loader2 v-if="busy[m.id] === 'test'" class="spin" /><Play v-else /> Test</button>
                  <button class="btn btn-sm btn-ghost btn-icon" title="Edit" :aria-label="'Edit ' + m.display_name" @click="openEdit(m)"><Pencil /></button>
                  <button class="btn btn-sm btn-ghost btn-icon" title="Delete" :aria-label="'Delete ' + m.display_name" @click="remove(m)"><Trash2 /></button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <Modal v-if="editing || creating" :title="editing ? 'Edit model' : 'Add model'" :subtitle="editing ? editing.upstream_id : 'Register an upstream model under a public name'" width="640px" @close="close">
      <form id="mform" @submit.prevent="save">
        <div v-if="creating" class="field">
          <label>Provider</label>
          <div class="row">
            <select v-model.number="form.provider_id" class="input" @change="upstream = []"><option v-for="p in providers" :key="p.id" :value="p.id">{{ p.name }}{{ p.has_key ? '' : ' (no key)' }}</option></select>
            <button type="button" class="btn" :disabled="upLoading || !providers.find((p) => p.id === form.provider_id)?.has_key" @click="discover"><Loader2 v-if="upLoading" class="spin" /><CloudDownload v-else /> Browse upstream</button>
          </div>
        </div>
        <div v-if="upstream.length" class="upstream">
          <input v-model="upQ" class="input" placeholder="Filter upstream models…" />
          <div class="uplist">
            <button v-for="u in upFiltered" :key="u.id" type="button" class="upitem" :class="{ sel: form.upstream_id === u.id }" @click="pick(u)">
              <span class="mono">{{ u.id }}</span><span class="muted">{{ u.type }}<template v-if="u.input_price_per_m != null"> · {{ fmtPrice(u.input_price_per_m) }}/{{ fmtPrice(u.output_price_per_m) }}</template></span>
            </button>
          </div>
        </div>
        <div class="grid-2">
          <div class="field"><label>Public model name</label><input v-model="form.model_name" class="input mono" required placeholder="e.g. my-model" /><span class="hint">What clients send as "model"</span></div>
          <div class="field"><label>Upstream model ID</label><input v-model="form.upstream_id" class="input mono" required /></div>
        </div>
        <div class="field"><label>Display name</label><input v-model="form.display_name" class="input" /></div>
        <div class="grid-2">
          <div class="field"><label>Input price (USD / 1M tokens)</label><input v-model="form.input_price_per_m" type="number" step="0.0001" min="0" class="input" /></div>
          <div class="field"><label>Output price (USD / 1M tokens)</label><input v-model="form.output_price_per_m" type="number" step="0.0001" min="0" class="input" /></div>
        </div>
        <div class="grid-2">
          <div class="field"><label>Context window (tokens)</label><input v-model="form.context_window" type="number" class="input" /></div>
          <div class="field"><label>Enabled</label><Toggle v-model="form.enabled" /></div>
        </div>
        <div class="caps-h">Capabilities <span class="hint">used by the Playground for defaults and guards</span></div>
        <div class="grid-2">
          <div class="field"><label>Max output tokens</label><input v-model="form.max_output_tokens" inputmode="numeric" class="input" placeholder="131072" /><span class="hint">Upper limit for max_tokens</span></div>
          <div class="field"><label>Default max tokens</label><input v-model="form.default_max_tokens" inputmode="numeric" class="input" placeholder="8192" /><span class="hint">Playground default; reasoning models need room to think</span></div>
        </div>
        <div class="grid-2">
          <div class="field"><label>Reasoning model</label><select v-model="form.reasoning" class="input"><option value="auto">Unknown</option><option value="yes">Yes — thinks before answering</option><option value="no">No</option></select></div>
          <div class="field"><label>Accepts images</label><select v-model="form.vision" class="input"><option value="auto">Auto (from name / tags)</option><option value="yes">Yes</option><option value="no">No — Playground strips images</option></select></div>
        </div>
        <div class="field"><label>Reasoning control levels</label>
          <div class="segmented"><button v-for="e in EFFORTS" :key="e" type="button" :class="{ active: form.reasoning_efforts.includes(e) }" :aria-pressed="form.reasoning_efforts.includes(e)" @click="toggleEffort(e)">{{ e }}</button></div>
          <span class="hint">Levels the upstream honours (off = reasoning.enabled=false, others = reasoning_effort). None selected hides the control.</span>
        </div>
      </form>
      <template #footer>
        <button class="btn" @click="close">Cancel</button>
        <button class="btn btn-primary" form="mform" :disabled="saving"><Loader2 v-if="saving" class="spin" /> Save model</button>
      </template>
    </Modal>

    <Modal v-if="showAlias" title="New alias" subtitle="A stable name you can re-point at any model later" @close="showAlias = false">
      <form id="aform" @submit.prevent="createAlias">
        <div class="field"><label>Alias name</label><input v-model="aliasForm.name" class="input mono" required placeholder="e.g. coder" pattern="[A-Za-z0-9._:/-]+" /></div>
        <div class="field"><label>Target model</label><select v-model.number="aliasForm.target_model_id" class="input"><option v-for="m in liveModels" :key="m.id" :value="m.id">{{ m.display_name }} ({{ m.provider_name }})</option></select></div>
        <div class="field"><label>Description</label><input v-model="aliasForm.description" class="input" /></div>
      </form>
      <template #footer><button class="btn" @click="showAlias = false">Cancel</button><button class="btn btn-primary" form="aform">Create alias</button></template>
    </Modal>
  </div>
</template>

<style scoped>
.caps-h { font-size: 12.5px; font-weight: 600; color: var(--text-2); margin: 6px 0 10px; padding-top: 12px; border-top: 1px solid var(--border); display: flex; gap: 8px; align-items: baseline; }
.caps-h .hint { font-weight: 400; }
.section { font-size: 14px; letter-spacing: -.01em; color: var(--text); font-weight: 600; margin-bottom: 10px; }
.aliases { display: grid; grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 12px; }
.alias { padding: 14px 16px; }
.ahead { display: flex; align-items: center; gap: 10px; }
.aic { width: 18px; display: grid; place-items: center; color: var(--text-3); flex-shrink: 0; }
.aname { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.aname .mono { font-weight: 500; font-size: 14px; }
.aname .muted { font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.atarget { font-size: 12px; margin-top: 8px; }
.mname { font-weight: 500; }
.clip { display: block; max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.search { position: relative; }
.search svg { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); pointer-events: none; color: var(--text-3); }
.search .input { padding-left: 32px; width: 200px; }
.ok { color: var(--success); display: inline-flex; gap: 4px; align-items: center; white-space: nowrap; font-size: 12.5px; }
.bad { color: var(--danger); display: inline-flex; gap: 4px; align-items: center; cursor: help; font-size: 12.5px; }
.tiny { height: 22px !important; width: 22px !important; border: 0 !important; background: transparent !important; color: var(--text-3); }
.tiny:hover { color: var(--text) !important; }
.tiny :deep(svg) { width: 12px; height: 12px; }
.upstream { margin-bottom: 14px; }
.uplist { max-height: 210px; overflow-y: auto; border: 1px solid var(--border); border-radius: var(--radius-sm); margin-top: 8px; }
.upitem { display: flex; justify-content: space-between; gap: 10px; width: 100%; text-align: left; padding: 6px 10px; border: 0; border-bottom: 1px solid var(--border); background: transparent; color: var(--text); cursor: pointer; font-size: 12.5px; }
.upitem:hover { background: var(--bg-hover); }
.upitem.sel { background: var(--primary-soft); box-shadow: inset 2px 0 0 var(--primary); }
</style>
