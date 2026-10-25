<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Loader2, RefreshCw, Database, Server, Cpu, CheckCircle2, XCircle, Lock } from 'lucide-vue-next'
import { api } from '../api'
import { auth } from '../stores/auth'
import { theme } from '../stores/theme'
import { ok, fail } from '../stores/toast'

interface Health { ok: boolean; [k: string]: unknown }
const health = ref<Health | null>(null)
const overview = ref<Record<string, unknown> | null>(null)
const syncing = ref(false)
async function load() {
  try { [health.value, overview.value] = await Promise.all([api.get<Health>('/api/health'), api.get<Record<string, unknown>>('/api/overview')]) } catch (e) { fail('Could not load status', e) }
}
onMounted(load)
async function sync() {
  syncing.value = true
  try {
    const r = await api.post<{ ok: boolean; added?: string[]; removed?: string[]; unchanged?: number; error?: string }>('/api/sync')
    if (r.ok) ok('Routing table synced', `${r.added?.length ?? 0} added · ${r.removed?.length ?? 0} removed · ${r.unchanged} unchanged`)
    else fail('Sync failed', r.error)
    await load()
  } catch (e) { fail('Sync failed', e) } finally { syncing.value = false }
}
const pw = reactive({ current_password: '', new_password: '', confirm: '' })
const saving = ref(false)
async function changePw() {
  if (pw.new_password !== pw.confirm) return fail('Passwords do not match')
  saving.value = true
  try { await api.post('/api/auth/password', { current_password: pw.current_password, new_password: pw.new_password }); ok('Password changed'); Object.assign(pw, { current_password: '', new_password: '', confirm: '' }) } catch (e) { fail('Could not change password', e) } finally { saving.value = false }
}
const comps = [
  { k: 'backend', label: 'Control plane API', icon: Server },
  { k: 'litellm', label: 'LiteLLM routing engine', icon: Cpu },
  { k: 'gateway_db', label: 'Gateway database', icon: Database },
  { k: 'litellm_db', label: 'Usage / spend database', icon: Database },
]
const comp = (k: string) => (health.value?.[k] || {}) as { ok?: boolean; latency_ms?: number; version?: string; error?: string }
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div><h1>Settings</h1><p>System health, routing sync and account.</p></div>
      <button class="btn" @click="load"><RefreshCw /> Refresh</button>
    </div>
    <div class="grid">
      <div class="card">
        <div class="card-header"><div><h3>System health</h3><div class="sub">Live status of gateway components</div></div><span v-if="health" class="badge" :class="health.ok ? 'badge-success' : 'badge-danger'"><span class="dot" />{{ health.ok ? 'All systems operational' : 'Degraded' }}</span></div>
        <div class="list">
          <div v-for="c in comps" :key="c.k" class="li">
            <component :is="c.icon" :size="16" class="muted" />
            <span>{{ c.label }}</span>
            <span v-if="comp(c.k).version" class="badge mono">v{{ comp(c.k).version }}</span>
            <span class="spacer" />
            <span class="muted" v-if="comp(c.k).latency_ms != null">{{ comp(c.k).latency_ms }} ms</span>
            <CheckCircle2 v-if="comp(c.k).ok" :size="16" class="okc" /><XCircle v-else-if="health" :size="16" class="badc" :title="comp(c.k).error" />
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-header"><div><h3>Routing table</h3><div class="sub">Providers, models and aliases pushed to LiteLLM</div></div><button class="btn btn-sm" :disabled="syncing" @click="sync"><Loader2 v-if="syncing" class="spin" /><RefreshCw v-else /> Force sync</button></div>
        <div v-if="overview" class="card-body kv">
          <div><span class="muted">Active providers</span><strong>{{ overview.providers_active }} / {{ overview.providers_total }}</strong></div>
          <div><span class="muted">Live models</span><strong>{{ overview.models_live }} / {{ overview.models_total }}</strong></div>
          <div><span class="muted">Aliases</span><strong>{{ overview.aliases }}</strong></div>
          <div><span class="muted">Active API keys</span><strong>{{ overview.keys_active }}</strong></div>
          <div style="grid-column: 1 / -1"><span class="muted">Model names served</span><div class="names"><span v-for="n in (overview.litellm_model_names as string[])" :key="n" class="badge mono">{{ n }}</span></div></div>
        </div>
      </div>
      <div class="card">
        <div class="card-header"><div><h3>Account</h3><div class="sub">Signed in as {{ auth.user?.username }}</div></div><Lock :size="16" class="muted" /></div>
        <form class="card-body" @submit.prevent="changePw">
          <div class="field"><label>Current password</label><input v-model="pw.current_password" type="password" class="input" autocomplete="current-password" required /></div>
          <div class="field"><label>New password</label><input v-model="pw.new_password" type="password" class="input" minlength="10" autocomplete="new-password" required /></div>
          <div class="field"><label>Confirm new password</label><input v-model="pw.confirm" type="password" class="input" autocomplete="new-password" required /></div>
          <button class="btn btn-primary" :disabled="saving"><Loader2 v-if="saving" class="spin" /> Change password</button>
        </form>
      </div>
      <div class="card">
        <div class="card-header"><h3>Appearance</h3></div>
        <div class="card-body">
          <div class="segmented"><button :class="{ active: theme === 'light' }" :aria-pressed="theme === 'light'" @click="theme = 'light'">Light</button><button :class="{ active: theme === 'dark' }" :aria-pressed="theme === 'dark'" @click="theme = 'dark'">Dark</button></div>
          <p class="muted" style="font-size: 12.5px; margin-top: 14px">API docs for the control plane are at <a href="/api/docs" target="_blank">/api/docs</a>.</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; }
.list { padding: 4px 0; }
.li { display: flex; align-items: center; gap: 10px; padding: 12px 18px; font-size: 13.5px; }
.li + .li { border-top: 1px solid var(--border); }
.okc { color: var(--success); }
.badc { color: var(--danger); }
.kv { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.kv > div { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.kv strong { font: 600 20px var(--font); letter-spacing: -.02em; font-variant-numeric: tabular-nums; }
.names { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
@media (max-width: 1000px) { .grid { grid-template-columns: 1fr; } }
</style>
