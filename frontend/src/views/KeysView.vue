<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Plus, KeyRound, Trash2, Loader2, Eye, EyeOff, Pencil, Plug, ShieldAlert } from 'lucide-vue-next'
import { api } from '../api'
import type { ApiKey, ConnectInfo, Model, Alias } from '../types'
import { fmtCompact, fmtCost, fmtDate, fmtInt, timeAgo } from '../format'
import { ok, fail } from '../stores/toast'
import Modal from '../components/Modal.vue'
import EmptyState from '../components/EmptyState.vue'
import CopyButton from '../components/CopyButton.vue'
import CodeBlock from '../components/CodeBlock.vue'
import { buildSnippets } from '../snippets'

const keys = ref<ApiKey[]>([])
const loading = ref(true)
const showRevoked = ref(false)
const info = ref<ConnectInfo | null>(null)
const modelNames = ref<string[]>([])

async function load() {
  try {
    const [k, c, m, a] = await Promise.all([api.get<ApiKey[]>('/api/keys'), api.get<ConnectInfo>('/api/connect'), api.get<Model[]>('/api/models'), api.get<Alias[]>('/api/aliases')])
    keys.value = k; info.value = c
    modelNames.value = [...a.filter((x) => x.live).map((x) => x.name), ...m.filter((x) => x.live).map((x) => x.model_name)]
  } catch (e) { fail('Could not load keys', e) } finally { loading.value = false }
}
onMounted(load)
const shown = computed(() => keys.value.filter((k) => showRevoked.value || !k.revoked))

const revealed = reactive<Record<number, string>>({})
async function toggleReveal(k: ApiKey) {
  if (revealed[k.id]) { delete revealed[k.id]; return }
  try { revealed[k.id] = (await api.get<{ key: string }>(`/api/keys/${k.id}/reveal`)).key } catch (e) { fail('Could not reveal', e) }
}
const getKey = (k: ApiKey) => async () => revealed[k.id] || (await api.get<{ key: string }>(`/api/keys/${k.id}/reveal`)).key

// create / edit
const creating = ref(false)
const editing = ref<ApiKey | null>(null)
const form = reactive({ name: '', max_budget: '' as string | number, budget_duration: '', rpm_limit: '' as string | number, tpm_limit: '' as string | number, models: [] as string[], expires_days: '' as string | number })
const created = ref<ApiKey | null>(null)
const saving = ref(false)
function openCreate() { creating.value = true; Object.assign(form, { name: '', max_budget: '', budget_duration: '', rpm_limit: '', tpm_limit: '', models: [], expires_days: '' }) }
function openEdit(k: ApiKey) { editing.value = k; Object.assign(form, { name: k.name, max_budget: k.max_budget ?? '', budget_duration: k.budget_duration ?? '', rpm_limit: k.rpm_limit ?? '', tpm_limit: k.tpm_limit ?? '', models: [...k.models], expires_days: '' }) }
const num = (v: string | number) => (v === '' || v === null ? null : Number(v))
async function save() {
  saving.value = true
  try {
    if (editing.value) {
      await api.patch(`/api/keys/${editing.value.id}`, { max_budget: num(form.max_budget), clear_budget: form.max_budget === '', budget_duration: form.budget_duration || null, rpm_limit: num(form.rpm_limit), tpm_limit: num(form.tpm_limit), models: form.models })
      ok('Key updated'); editing.value = null
    } else {
      created.value = await api.post<ApiKey>('/api/keys', { name: form.name, max_budget: num(form.max_budget), budget_duration: form.budget_duration || null, rpm_limit: num(form.rpm_limit), tpm_limit: num(form.tpm_limit), models: form.models.length ? form.models : null, expires_days: num(form.expires_days) })
      creating.value = false
    }
    await load()
  } catch (e) { fail('Save failed', e) } finally { saving.value = false }
}
async function revoke(k: ApiKey) {
  if (!confirm(`Revoke key "${k.name}"? Clients using it will immediately get 401 errors.`)) return
  try { await api.del(`/api/keys/${k.id}`); ok('Key revoked'); await load() } catch (e) { fail('Revoke failed', e) }
}

// connection snippet
const snippetFor = ref<{ key: ApiKey; value: string } | null>(null)
const snippetTab = ref('curl')
async function openSnippet(k: ApiKey) {
  try { snippetFor.value = { key: k, value: await getKey(k)() }; snippetTab.value = 'curl' } catch (e) { fail('Could not load key', e) }
}
const snippets = computed(() => snippetFor.value && info.value ? buildSnippets({ openai: info.value.openai_base_url, anthropic: info.value.anthropic_base_url, key: snippetFor.value.value, model: 'default', models: modelNames.value }) : [])
const budgetPct = (k: ApiKey) => (k.max_budget ? Math.min(100, (k.spend / k.max_budget) * 100) : 0)
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1>API keys</h1>
        <p>Virtual keys for clients. Each key can have its own budget, rate limits and model allow-list.</p>
      </div>
      <div class="toolbar">
        <label class="row muted" style="gap: 6px; font-size: 13px"><input v-model="showRevoked" type="checkbox" /> Show revoked</label>
        <button class="btn btn-primary" @click="openCreate"><Plus /> Create key</button>
      </div>
    </div>

    <div class="card">
      <div v-if="loading" class="card-body"><div v-for="i in 3" :key="i" class="skeleton" style="height: 40px; margin-bottom: 8px" /></div>
      <EmptyState v-else-if="!shown.length" :icon="KeyRound" title="No API keys" description="Create a virtual key to let a client (OpenCode, scripts, apps) use the gateway."><button class="btn btn-primary" @click="openCreate"><Plus /> Create key</button></EmptyState>
      <div v-else class="table-wrap">
        <table class="table">
          <thead><tr><th>Name</th><th>Key</th><th>Models</th><th>Budget</th><th>Limits</th><th class="num">Requests</th><th class="num">Tokens</th><th>Last used</th><th style="width: 1%"></th></tr></thead>
          <tbody>
            <tr v-for="k in shown" :key="k.id" :class="{ revoked: k.revoked }">
              <td><div style="font-weight: 600">{{ k.name }}</div><div class="muted" style="font-size: 12px">Created {{ fmtDate(k.created_at, false) }}</div></td>
              <td>
                <div class="row" style="gap: 4px">
                  <code class="keyval">{{ revealed[k.id] || k.key_prefix }}</code>
                  <template v-if="!k.revoked">
                    <button class="btn btn-sm btn-ghost btn-icon" :title="revealed[k.id] ? 'Hide' : 'Reveal'" :aria-label="revealed[k.id] ? 'Hide' : 'Reveal'" @click="toggleReveal(k)"><EyeOff v-if="revealed[k.id]" /><Eye v-else /></button>
                    <CopyButton :text="getKey(k)" label="" class="btn-ghost" />
                  </template>
                  <span v-else class="badge badge-danger">Revoked</span>
                </div>
              </td>
              <td><span v-if="!k.models.length" class="badge badge-primary">All models</span><span v-else class="muted" :title="k.models.join(', ')">{{ k.models.length }} models</span></td>
              <td style="min-width: 150px">
                <div v-if="k.max_budget != null">
                  <div class="row" style="justify-content: space-between; font-size: 12.5px"><span>{{ fmtCost(k.spend) }}</span><span class="muted">of {{ fmtCost(k.max_budget) }}{{ k.budget_duration ? ' / ' + k.budget_duration : '' }}</span></div>
                  <div class="meter"><div :style="{ width: budgetPct(k) + '%' }" :class="{ hot: budgetPct(k) > 85 }" /></div>
                </div>
                <div v-else><span>{{ fmtCost(k.spend) }}</span> <span class="muted">· no limit</span></div>
              </td>
              <td class="muted" style="font-size: 12.5px">{{ k.rpm_limit ? k.rpm_limit + ' rpm' : '' }}{{ k.rpm_limit && k.tpm_limit ? ' · ' : '' }}{{ k.tpm_limit ? fmtCompact(k.tpm_limit) + ' tpm' : '' }}{{ !k.rpm_limit && !k.tpm_limit ? 'Unlimited' : '' }}</td>
              <td class="num">{{ fmtInt(k.requests) }}</td>
              <td class="num">{{ fmtCompact(k.tokens) }}</td>
              <td class="muted">{{ timeAgo(k.last_used_at) }}</td>
              <td>
                <div v-if="!k.revoked" class="row" style="gap: 4px">
                  <button class="btn btn-sm" @click="openSnippet(k)"><Plug /> Connect</button>
                  <button class="btn btn-sm btn-ghost btn-icon" title="Edit limits" :aria-label="'Edit limits for ' + k.name" @click="openEdit(k)"><Pencil /></button>
                  <button class="btn btn-sm btn-ghost btn-icon" title="Revoke" :aria-label="'Revoke ' + k.name" @click="revoke(k)"><Trash2 /></button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <Modal v-if="creating || editing" :title="editing ? `Edit ${editing.name}` : 'Create API key'" subtitle="Leave limits empty for unlimited" @close="creating = false; editing = null">
      <form id="kform" @submit.prevent="save">
        <div class="field"><label>Name</label><input v-model="form.name" class="input" required :disabled="!!editing" placeholder="e.g. laptop-opencode" /></div>
        <div class="grid-2">
          <div class="field"><label>Max budget (USD)</label><input v-model="form.max_budget" type="number" step="0.01" min="0" class="input" placeholder="Unlimited" /></div>
          <div class="field"><label>Budget resets every</label>
            <select v-model="form.budget_duration" class="input"><option value="">Never</option><option value="1d">Day</option><option value="7d">Week</option><option value="30d">30 days</option></select>
          </div>
          <div class="field"><label>Requests / minute</label><input v-model="form.rpm_limit" type="number" min="1" class="input" placeholder="Unlimited" /></div>
          <div class="field"><label>Tokens / minute</label><input v-model="form.tpm_limit" type="number" min="1" class="input" placeholder="Unlimited" /></div>
        </div>
        <div v-if="!editing" class="field"><label>Expires after (days)</label><input v-model="form.expires_days" type="number" min="1" class="input" placeholder="Never" /></div>
        <div class="field">
          <label>Allowed models</label>
          <div class="chips">
            <label v-for="m in modelNames" :key="m" class="chip" :class="{ on: form.models.includes(m) }"><input v-model="form.models" type="checkbox" :value="m" />{{ m }}</label>
          </div>
          <span class="hint">{{ form.models.length ? form.models.length + ' selected' : 'None selected = access to all models' }}</span>
        </div>
      </form>
      <template #footer><button class="btn" @click="creating = false; editing = null">Cancel</button><button class="btn btn-primary" form="kform" :disabled="saving"><Loader2 v-if="saving" class="spin" /> {{ editing ? 'Save' : 'Create key' }}</button></template>
    </Modal>

    <Modal v-if="created" title="Your new API key" subtitle="You can reveal it again later from this page." @close="created = null">
      <div class="newkey"><ShieldAlert :size="18" /><span>Treat this key like a password. Anyone with it can spend your provider credits.</span></div>
      <div class="row" style="margin-top: 14px"><code class="keyval big">{{ created.key }}</code><CopyButton :text="created.key || ''" label="Copy" /></div>
      <template #footer><button class="btn" @click="openSnippet(created!); created = null"><Plug /> Connection snippets</button><button class="btn btn-primary" @click="created = null">Done</button></template>
    </Modal>

    <Modal v-if="snippetFor" :title="`Connect with ${snippetFor.key.name}`" subtitle="Ready-to-paste configuration with this key filled in" width="820px" @close="snippetFor = null">
      <div class="tabs"><button v-for="s in snippets" :key="s.id" :class="{ active: snippetTab === s.id }" :aria-pressed="snippetTab === s.id" @click="snippetTab = s.id">{{ s.title }}</button></div>
      <template v-for="s in snippets" :key="s.id">
        <div v-if="s.id === snippetTab">
          <p v-if="s.note" class="muted" style="margin: 0 0 10px; font-size: 13px">{{ s.note }}</p>
          <CodeBlock :code="s.code" :title="s.file" />
        </div>
      </template>
    </Modal>
  </div>
</template>

<style scoped>
.revoked td { opacity: .55; }
.keyval { background: var(--bg); border: 1px solid var(--border); padding: 2px 7px; border-radius: 3px; font-size: 12px; max-width: 360px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: inline-block; }
.keyval.big { flex: 1; font-size: 13px; padding: 8px 10px; max-width: none; user-select: all; }
.meter { height: 3px; border-radius: 0; background: var(--bg-subtle); margin-top: 5px; overflow: hidden; }
.meter > div { height: 100%; background: var(--text-2); }
.meter > div.hot { background: var(--danger); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; max-height: 150px; overflow-y: auto; }
.chip { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; font-family: var(--font); border: 1px solid var(--border-strong); border-radius: 3px; padding: 2px 8px; cursor: pointer; }
.chip { position: relative; }
.chip input { position: absolute; opacity: 0; width: 1px; height: 1px; pointer-events: none; }
.chip:hover:not(.on) { border-color: var(--text-3); color: var(--text); }
.chip:has(input:focus-visible) { outline: 2px solid var(--focus); outline-offset: 1px; }
.chip.on { background: var(--ink); border-color: var(--ink); color: var(--on-ink); }
.newkey { display: flex; gap: 10px; align-items: center; background: var(--warning-soft); color: var(--warning); border-left: 2px solid var(--warning); padding: 10px 12px; border-radius: var(--radius-sm); font-size: 13px; }
.tabs { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 14px; border-bottom: 1px solid var(--border); }
.tabs button { border: 0; background: transparent; padding: 8px 12px; font: 500 13px var(--font); color: var(--text-2); cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px; }
.tabs button:hover:not(.active) { color: var(--text); }
.tabs button.active { color: var(--text); border-bottom-color: var(--primary); }
</style>
