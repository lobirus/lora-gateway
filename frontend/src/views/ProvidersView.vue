<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Plus, KeyRound, PlugZap, Loader2, Server, Pencil, Trash2, CheckCircle2, XCircle, Search, RefreshCw } from 'lucide-vue-next'
import { api } from '../api'
import type { Provider } from '../types'
import { fmtInt, timeAgo } from '../format'
import { ok, fail, toast } from '../stores/toast'
import Modal from '../components/Modal.vue'
import Toggle from '../components/Toggle.vue'
import EmptyState from '../components/EmptyState.vue'

const providers = ref<Provider[]>([])
const loading = ref(true)
const busy = reactive<Record<number, string>>({})
const filter = ref('')

// monochrome monograms; no brand colours
const logos: Record<string, { t: string }> = {
  together: { t: 'Tg' }, zai: { t: 'Z' }, openrouter: { t: 'OR' },
  anthropic: { t: 'A' }, openai: { t: 'O' }, xai: { t: 'x' }, openai_compatible: { t: '⇄' }, groq: { t: 'Gq' }, mistral: { t: 'M' },
  gemini: { t: 'G' }, deepseek: { t: 'DS' }, deepinfra: { t: 'DI' }, fireworks: { t: 'FW' }, cerebras: { t: 'Cb' }, sambanova: { t: 'SN' },
  hyperbolic: { t: 'Hy' }, nebius: { t: 'Nb' }, novita: { t: 'Nv' }, baseten: { t: 'Bt' }, vercel: { t: 'V' }, pipeline: { t: '◖' }, local: { t: 'L' },
}
const kindLabel: Record<string, string> = { together: 'Together AI', zai: 'Z.ai', openrouter: 'OpenRouter', anthropic: 'Anthropic', openai: 'OpenAI', xai: 'xAI',
  groq: 'Groq', mistral: 'Mistral', gemini: 'Google Gemini (OpenAI-compatible)', deepseek: 'DeepSeek', deepinfra: 'DeepInfra', fireworks: 'Fireworks AI',
  cerebras: 'Cerebras', sambanova: 'SambaNova', hyperbolic: 'Hyperbolic', nebius: 'Nebius AI Studio', novita: 'Novita AI', baseten: 'Baseten',
  vercel: 'Vercel AI Gateway', openai_compatible: 'OpenAI-compatible', pipeline: 'Gateway voice pipeline' }
async function syncModels(p: Provider) {
  busy[p.id] = 'sync'
  try {
    const r = await api.post<{ ok: boolean; message?: string; error?: string }>(`/api/providers/${p.id}/sync`)
    toast(r.ok ? 'success' : 'error', r.ok ? `${p.name} catalog synced` : `${p.name} sync failed`, r.message || r.error)
    await load()
  } catch (e) { fail('Sync failed', e) } finally { delete busy[p.id] }
}
async function setAutoSync(p: Provider, v: boolean) {
  try { await api.patch(`/api/providers/${p.id}`, { auto_sync: v }); p.auto_sync = v } catch (e) { fail('Update failed', e) }
}

async function load() {
  try { providers.value = await api.get<Provider[]>('/api/providers') } catch (e) { fail('Could not load providers', e) } finally { loading.value = false }
}
onMounted(load)
const shown = computed(() => providers.value.filter((p) => !filter.value || (p.name + p.slug + p.kind).toLowerCase().includes(filter.value.toLowerCase())))

function syncNote(s: { ok: boolean; error?: string; added?: string[]; removed?: string[] }) {
  if (!s.ok) toast('error', 'Gateway sync failed', s.error)
}

async function toggle(p: Provider, v: boolean) {
  if (v && !p.has_key && p.kind !== 'pipeline') { openEdit(p); toast('info', 'Add an API key first', 'The provider will be enabled once a key is saved.'); return }
  busy[p.id] = 'toggle'
  try {
    const r = await api.patch<{ provider: Provider; sync: never }>(`/api/providers/${p.id}`, { enabled: v })
    syncNote(r.sync)
    ok(v ? `${p.name} enabled` : `${p.name} disabled`, v ? `${p.enabled_model_count} models are now live` : 'Its models were removed from routing')
    await load()
  } catch (e) { fail('Update failed', e) } finally { delete busy[p.id] }
}

async function test(p: Provider) {
  busy[p.id] = 'test'
  try {
    const r = await api.post<{ ok: boolean; message: string }>(`/api/providers/${p.id}/test`)
    toast(r.ok ? 'success' : 'error', r.ok ? `${p.name} is reachable` : `${p.name} test failed`, r.message)
    await load()
  } catch (e) { fail('Test failed', e) } finally { delete busy[p.id] }
}

// edit / create
const editing = ref<Provider | null>(null)
const creating = ref(false)
const form = reactive({ name: '', kind: 'openai_compatible', api_base: '', api_key: '', enabled: true, description: '' })
const saving = ref(false)
function openEdit(p: Provider) {
  editing.value = p
  Object.assign(form, { name: p.name, kind: p.kind, api_base: p.api_base, api_key: '', enabled: p.enabled || !p.has_key, description: p.description || '' })
}
function openCreate() {
  creating.value = true
  Object.assign(form, { name: '', kind: 'openai_compatible', api_base: '', api_key: '', enabled: true, description: '' })
}
function close() { editing.value = null; creating.value = false }
async function save() {
  saving.value = true
  try {
    if (editing.value) {
      const body: Record<string, unknown> = { name: form.name, api_base: form.api_base, description: form.description }
      if (form.api_key.trim()) body.api_key = form.api_key.trim()
      if (form.api_key.trim() || editing.value.has_key) body.enabled = form.enabled
      const r = await api.patch<{ sync: never }>(`/api/providers/${editing.value.id}`, body)
      syncNote(r.sync)
      ok('Provider saved', form.api_key ? 'API key stored encrypted' : undefined)
    } else {
      const r = await api.post<{ sync: never }>('/api/providers', { ...form, api_key: form.api_key || null })
      syncNote(r.sync)
      ok('Provider added', 'Now add models for it on the Models page')
    }
    close()
    await load()
  } catch (e) { fail('Save failed', e) } finally { saving.value = false }
}
async function removeKey() {
  if (!editing.value || !confirm(`Remove the API key for ${editing.value.name}? Its models will stop working.`)) return
  try { await api.patch(`/api/providers/${editing.value.id}`, { api_key: '', enabled: false }); ok('API key removed'); close(); await load() } catch (e) { fail('Failed', e) }
}
async function remove(p: Provider) {
  if (!confirm(`Delete provider ${p.name} and its ${p.model_count} models? This cannot be undone.`)) return
  try { await api.del(`/api/providers/${p.id}`); ok('Provider deleted'); await load() } catch (e) { fail('Delete failed', e) }
}
const defaultBase: Record<string, string> = { together: 'https://api.together.xyz/v1', openai: 'https://api.openai.com/v1', anthropic: 'https://api.anthropic.com', openrouter: 'https://openrouter.ai/api/v1', xai: 'https://api.x.ai/v1', zai: 'https://api.z.ai/api/paas/v4',
  groq: 'https://api.groq.com/openai/v1', mistral: 'https://api.mistral.ai/v1', gemini: 'https://generativelanguage.googleapis.com/v1beta/openai', deepseek: 'https://api.deepseek.com', deepinfra: 'https://api.deepinfra.com/v1/openai',
  fireworks: 'https://api.fireworks.ai/inference/v1', cerebras: 'https://api.cerebras.ai/v1', sambanova: 'https://api.sambanova.ai/v1', hyperbolic: 'https://api.hyperbolic.xyz/v1', nebius: 'https://api.studio.nebius.com/v1',
  novita: 'https://api.novita.ai/v3/openai', baseten: 'https://inference.baseten.co/v1', vercel: 'https://ai-gateway.vercel.sh/v1', openai_compatible: '' }
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1>Providers</h1>
        <p>Upstream LLM providers. Keys are encrypted at rest and pushed to the routing engine.</p>
      </div>
      <div class="toolbar">
        <div class="search"><Search :size="14" /><input v-model="filter" class="input" placeholder="Filter providers" /></div>
        <button class="btn btn-primary" @click="openCreate"><Plus /> Add provider</button>
      </div>
    </div>

    <div v-if="loading" class="grid"><div v-for="i in 6" :key="i" class="card skeleton" style="height: 210px" /></div>
    <div v-else-if="!providers.length" class="card"><EmptyState :icon="Server" title="No providers yet" description="Add an upstream provider to start routing requests."><button class="btn btn-primary" @click="openCreate"><Plus /> Add provider</button></EmptyState></div>
    <div v-else class="grid">
      <div v-for="p in shown" :key="p.id" class="card prov" :class="{ dim: !p.enabled }">
        <div class="head">
          <div class="logo">{{ (logos[p.slug] || logos[p.kind] || logos.openai_compatible).t }}</div>
          <div class="meta">
            <div class="name">{{ p.name }}</div>
            <div class="kind">{{ kindLabel[p.kind] || p.kind }}</div>
          </div>
          <Toggle :model-value="p.enabled" :disabled="!!busy[p.id]" :aria-label="'Route traffic to ' + p.name" @update:model-value="(v: boolean) => toggle(p, v)" />
        </div>
        <p class="desc">{{ p.description || p.api_base }}</p>
        <div class="facts">
          <div><span class="muted">Status</span>
            <span v-if="p.status === 'active'" class="badge badge-success"><span class="dot" />Active</span>
            <span v-else-if="p.status === 'missing_key'" class="badge badge-warning"><span class="dot" />Needs key</span>
            <span v-else class="badge"><span class="dot" />Disabled</span>
          </div>
          <div><span class="muted">API key</span><span class="mono">{{ p.key_masked || 'not set' }}</span></div>
          <div><span class="muted">Models</span><span>{{ fmtInt(p.enabled_model_count) }} / {{ fmtInt(p.model_count) }} enabled<template v-if="p.synced_count"> · {{ fmtInt(p.synced_count) }} synced</template></span></div>
          <div><span class="muted">Last test</span>
            <span v-if="p.last_test_ok === true" class="ok"><CheckCircle2 :size="14" /> {{ timeAgo(p.last_test_at) }}</span>
            <span v-else-if="p.last_test_ok === false" class="bad" :title="p.last_test_msg || ''"><XCircle :size="14" /> failed {{ timeAgo(p.last_test_at) }}</span>
            <span v-else class="muted">never</span>
          </div>
          <div v-if="p.can_sync" class="wide"><span class="muted">Catalog sync</span>
            <span class="syncline">
              <Toggle :model-value="p.auto_sync" :aria-label="'Daily catalog sync for ' + p.name" @update:model-value="(v: boolean) => setAutoSync(p, v)" />
              <span v-if="p.last_sync_at" :class="p.last_sync_ok ? 'muted' : 'bad'" :title="p.last_sync_msg || ''">{{ p.last_sync_ok ? '' : 'failed · ' }}{{ timeAgo(p.last_sync_at) }} · {{ p.last_sync_msg }}</span>
              <span v-else class="muted">{{ p.auto_sync ? 'daily, and as soon as a key is added' : 'off' }}</span>
            </span>
          </div>
        </div>
        <div class="actions">
          <button class="btn btn-sm" @click="openEdit(p)"><KeyRound /> {{ p.has_key || p.kind === 'pipeline' ? 'Edit' : 'Add key' }}</button>
          <button v-if="p.kind !== 'pipeline'" class="btn btn-sm" :disabled="!p.has_key || !!busy[p.id]" @click="test(p)"><Loader2 v-if="busy[p.id] === 'test'" class="spin" /><PlugZap v-else /> Test</button>
          <button v-if="p.can_sync" class="btn btn-sm" :disabled="!p.has_key || !!busy[p.id]" title="Import every model this provider serves, with prices" @click="syncModels(p)"><Loader2 v-if="busy[p.id] === 'sync'" class="spin" /><RefreshCw v-else /> Sync models</button>
          <RouterLink class="btn btn-sm btn-ghost" :to="{ name: 'models', query: { provider: p.slug } }">Models</RouterLink>
          <span class="spacer" />
          <button class="btn btn-sm btn-ghost btn-icon" title="Delete provider" :aria-label="'Delete provider ' + p.name" @click="remove(p)"><Trash2 /></button>
        </div>
      </div>
    </div>

    <Modal v-if="editing || creating" :title="editing ? `Edit ${editing.name}` : 'Add provider'" :subtitle="editing ? editing.api_base : 'Any OpenAI-compatible endpoint or a supported provider type'" @close="close">
      <form id="pform" @submit.prevent="save">
        <div class="field"><label>Display name</label><input v-model="form.name" class="input" required /></div>
        <div v-if="creating" class="field">
          <label>Provider type</label>
          <select v-model="form.kind" class="input" @change="form.api_base = defaultBase[form.kind] || ''">
            <option v-for="(l, k) in kindLabel" :key="k" :value="k">{{ l }}</option>
          </select>
        </div>
        <div class="field">
          <label>API base URL</label>
          <input v-model="form.api_base" class="input mono" :placeholder="defaultBase[form.kind] || 'https://host/v1'" :required="form.kind === 'openai_compatible'" />
          <span class="hint">Leave as default unless you use a proxy or regional endpoint.</span>
        </div>
        <div class="field">
          <label>API key</label>
          <input v-model="form.api_key" class="input mono" type="password" autocomplete="off" :placeholder="editing?.has_key ? `Current: ${editing.key_masked} — leave empty to keep` : 'Paste API key'" />
          <span class="hint">Stored encrypted (Fernet) and never shown again in full.</span>
        </div>
        <div class="field row" style="justify-content: space-between"><span id="lbl-penabled" class="label">Enabled (route traffic to this provider)</span><Toggle v-model="form.enabled" aria-labelledby="lbl-penabled" /></div>
        <div class="field"><label>Description</label><textarea v-model="form.description" class="input" rows="2" /></div>
      </form>
      <template #footer>
        <button v-if="editing?.has_key" class="btn btn-danger" style="margin-right: auto" @click="removeKey">Remove key</button>
        <button class="btn" @click="close">Cancel</button>
        <button class="btn btn-primary" form="pform" :disabled="saving"><Loader2 v-if="saving" class="spin" /><Pencil v-else /> Save</button>
      </template>
    </Modal>
  </div>
</template>

<style scoped>
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 16px; }
.prov { padding: 16px; display: flex; flex-direction: column; gap: 12px; transition: border-color .12s var(--ease); }
.prov:hover { border-color: var(--border-strong); }
.prov.dim { background: var(--bg); }
.prov.dim .logo, .prov.dim .name { opacity: .6; }
.head { display: flex; align-items: center; gap: 12px; }
.logo { width: 34px; height: 34px; border-radius: var(--radius-sm); border: 1px solid var(--border-strong); background: var(--bg); color: var(--text); display: grid; place-items: center; font: 500 13px var(--font); letter-spacing: -.02em; flex-shrink: 0; }
.meta { flex: 1; min-width: 0; }
.name { font-weight: 600; font-size: 14px; }
.kind { font-size: 12px; color: var(--text-3); }
.desc { margin: 0; color: var(--text-2); font-size: 12.5px; min-height: 37px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.facts { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 14px; padding: 12px 0; border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); font-size: 12.5px; }
.facts > div { display: flex; flex-direction: column; gap: 3px; align-items: flex-start; }
.facts .muted { font-size: 12px; }
.ok { color: var(--success); display: inline-flex; gap: 4px; align-items: center; }
.bad { color: var(--danger); display: inline-flex; gap: 4px; align-items: center; cursor: help; }
.actions { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.facts > .wide { grid-column: 1 / -1; }
.syncline { display: flex; align-items: center; gap: 8px; min-width: 0; max-width: 100%; }
.syncline span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 12px; }
.search { position: relative; }
.search svg { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); pointer-events: none; color: var(--text-3); }
.search .input { padding-left: 32px; width: 220px; }
</style>
