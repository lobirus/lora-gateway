<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { RefreshCw, ScrollText, ChevronLeft, ChevronRight, Search, X } from 'lucide-vue-next'
import { api, qs } from '../api'
import type { LogRow } from '../types'
import { TYPE_LABELS } from '../types'
import { fmtCost, fmtDate, fmtInt, fmtMs } from '../format'
import { fail } from '../stores/toast'
import EmptyState from '../components/EmptyState.vue'
import Modal from '../components/Modal.vue'
import Toggle from '../components/Toggle.vue'

const rows = ref<LogRow[]>([])
const total = ref(0)
const loading = ref(true)
const route = useRoute()
const f = reactive({ hours: 168, model: '', provider: '', key: '', status: '', source: (route.query.source as string) || '', type: (route.query.type as string) || '', q: '' })
const sourceLabel: Record<string, string> = { playground: 'Playground', test: 'Model test', api: 'API' }
const page = ref(0)
const size = 50
const opts = ref<{ model: string[]; provider: string[]; key: string[] }>({ model: [], provider: [], key: [] })
const live = ref(true)
let timer: number | undefined

async function load() {
  loading.value = true
  try {
    const r = await api.get<{ items: LogRow[]; total: number }>('/api/logs' + qs({ ...f, limit: size, offset: page.value * size }))
    rows.value = r.items; total.value = r.total
  } catch (e) { fail('Could not load logs', e) } finally { loading.value = false }
}
async function loadOpts() { try { opts.value = await api.get('/api/analytics/filters' + qs({ hours: f.hours })) } catch { /* ignore */ } }
onMounted(() => { load(); loadOpts(); timer = window.setInterval(() => live.value && page.value === 0 && load(), 10000) })
onBeforeUnmount(() => clearInterval(timer))
let deb: number | undefined
watch(() => ({ ...f }), () => { page.value = 0; clearTimeout(deb); deb = window.setTimeout(load, 250) })
watch(page, load)
const pages = computed(() => Math.max(1, Math.ceil(total.value / size)))
const hasFilters = computed(() => f.model || f.provider || f.key || f.status || f.source || f.type || f.q)
function clear() { Object.assign(f, { model: '', provider: '', key: '', status: '', source: '', type: '', q: '' }) }
/** usage cells: tokens for chat; audio seconds / characters for audio requests */
function usageIn(r: LogRow) { return r.type === 'transcription' ? (r.audio_seconds != null ? r.audio_seconds.toFixed(1) + ' s' : '—') : r.type === 'speech' ? (r.characters != null ? fmtInt(r.characters) + ' ch' : '—') : fmtInt(r.tokens_in) }
function usageOut(r: LogRow) { return r.type === 'transcription' || r.type === 'speech' ? '' : fmtInt(r.tokens_out) }
const sel = ref<LogRow | null>(null)
const latClass = (ms: number | null) => (ms == null ? '' : ms > 15000 ? 'slow' : ms > 5000 ? 'mid' : 'fast')
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1>Request logs</h1>
        <p>Every request routed through the gateway, with latency, tokens and cost. Prompts are not stored.</p>
      </div>
      <div class="toolbar">
        <label class="row muted" style="gap: 8px; font-size: 13px"><Toggle v-model="live" /> Auto-refresh</label>
        <button class="btn btn-icon" @click="load" title="Refresh" aria-label="Refresh"><RefreshCw :class="{ spin: loading }" /></button>
      </div>
    </div>

    <div class="card">
      <div class="filters">
        <div class="search"><Search :size="14" /><input v-model="f.q" class="input" placeholder="Search request ID or model" /></div>
        <select v-model.number="f.hours" class="input"><option :value="1">Last hour</option><option :value="24">Last 24h</option><option :value="168">Last 7 days</option><option :value="720">Last 30 days</option><option :value="2160">Last 90 days</option></select>
        <select v-model="f.model" class="input"><option value="">All models</option><option v-for="m in opts.model" :key="m" :value="m">{{ m }}</option></select>
        <select v-model="f.provider" class="input"><option value="">All providers</option><option v-for="m in opts.provider" :key="m" :value="m">{{ m }}</option></select>
        <select v-model="f.key" class="input"><option value="">All keys</option><option v-for="m in opts.key" :key="m" :value="m">{{ m }}</option></select>
        <select v-model="f.status" class="input"><option value="">Any status</option><option value="success">Success</option><option value="error">Errors</option></select>
        <select v-model="f.type" class="input" aria-label="Request type"><option value="">Any type</option><option value="chat">Chat</option><option value="audio">Audio (all)</option><option value="transcription">Transcription</option><option value="speech">Speech</option><option value="realtime">Realtime</option><option value="embedding">Embedding</option></select>
        <select v-model="f.source" class="input"><option value="">Any source</option><option value="api">API clients</option><option value="playground">Playground</option><option value="test">Model tests</option></select>
        <button v-if="hasFilters" class="btn btn-ghost btn-sm" @click="clear"><X /> Clear</button>
      </div>
      <EmptyState v-if="!loading && !rows.length" :icon="ScrollText" title="No requests found" :description="hasFilters ? 'No requests match these filters.' : 'Requests will appear here a few seconds after they complete.'" />
      <div v-else class="table-wrap">
        <table class="table">
          <thead><tr><th>Time</th><th>Status</th><th>Type</th><th>Model</th><th>Provider</th><th>Key</th><th>Source</th><th class="num" title="Tokens in; audio seconds for transcription; characters for speech">In</th><th class="num">Out</th><th class="num">Latency</th><th class="num">TTFT</th><th class="num">Cost</th></tr></thead>
          <tbody>
            <tr v-for="r in rows" :key="r.request_id" class="clickable" tabindex="0" :aria-label="'Request details ' + r.request_id" @click="sel = r" @keydown.enter.prevent="sel = r" @keydown.space.prevent="sel = r">
              <td class="muted" style="white-space: nowrap">{{ fmtDate(r.start_time) }}</td>
              <td><span v-if="r.status === 'success'" class="st-ok mono"><span class="dot" />200</span><span v-else class="badge badge-danger" :title="r.error_message || ''"><span class="dot" />{{ r.error_code || 'error' }}</span></td>
              <td><span class="type" :class="r.type">{{ TYPE_LABELS[r.type] || r.type }}</span></td>
              <td class="trunc" :title="r.model"><span class="mono">{{ r.model }}</span></td>
              <td class="trunc" :title="r.provider">{{ r.provider }}</td>
              <td class="mono muted trunc" :title="r.key_name">{{ r.key_name }}</td>
              <td><span class="src">{{ sourceLabel[r.source] || r.source }}</span></td>
              <td class="num">{{ usageIn(r) }}</td>
              <td class="num">{{ usageOut(r) }}</td>
              <td class="num"><span class="lat" :class="r.type === 'realtime' ? 'session' : latClass(r.latency_ms)" :title="r.type === 'realtime' ? 'Realtime session duration' : ''">{{ fmtMs(r.latency_ms) }}</span></td>
              <td class="num muted">{{ fmtMs(r.ttft_ms) }}</td>
              <td class="num">{{ fmtCost(r.cost) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="pager">
        <span class="muted">{{ fmtInt(total) }} requests</span>
        <span class="spacer" />
        <span class="muted">Page {{ page + 1 }} of {{ pages }}</span>
        <button class="btn btn-sm btn-icon" :disabled="page === 0" aria-label="Previous page" @click="page--"><ChevronLeft /></button>
        <button class="btn btn-sm btn-icon" :disabled="page + 1 >= pages" aria-label="Next page" @click="page++"><ChevronRight /></button>
      </div>
    </div>

    <Modal v-if="sel" title="Request details" :subtitle="sel.request_id" width="620px" @close="sel = null">
      <dl class="dl">
        <dt>Started</dt><dd>{{ fmtDate(sel.start_time) }}</dd>
        <dt>Status</dt><dd>{{ sel.status }}</dd>
        <dt>Model (alias)</dt><dd class="mono">{{ sel.model }}</dd>
        <dt>Upstream model</dt><dd class="mono">{{ sel.upstream_model }}</dd>
        <dt>Provider</dt><dd>{{ sel.provider }}</dd>
        <dt>API key</dt><dd class="mono">{{ sel.key_name }}</dd>
        <dt>Call type</dt><dd class="mono">{{ sel.call_type }}</dd>
        <dt>Source</dt><dd>{{ sourceLabel[sel.source] || sel.source }}</dd>
        <template v-if="sel.tags?.length"><dt>Tags</dt><dd class="tags"><span v-for="t in sel.tags" :key="t" class="badge">{{ t }}</span></dd></template>
        <dt>Type</dt><dd>{{ TYPE_LABELS[sel.type] || sel.type }}</dd>
        <template v-if="sel.audio_seconds != null"><dt>Audio</dt><dd>{{ sel.audio_seconds.toFixed(1) }} s{{ sel.type === 'realtime' ? ' session' : ' transcribed' }}</dd></template>
        <template v-if="sel.characters != null"><dt>Characters</dt><dd>{{ fmtInt(sel.characters) }} spoken (derived from cost)</dd></template>
        <dt>Tokens</dt><dd>{{ fmtInt(sel.tokens_in) }} in · {{ fmtInt(sel.tokens_out) }} out</dd>
        <dt>Latency</dt><dd>{{ fmtMs(sel.latency_ms) }} <span class="muted">(TTFT {{ fmtMs(sel.ttft_ms) }})</span></dd>
        <dt>Cost</dt><dd>{{ fmtCost(sel.cost) }}</dd>
        <dt>Client IP</dt><dd class="mono">{{ sel.ip || '—' }}</dd>
        <template v-if="sel.error_message"><dt>Error</dt><dd class="err">{{ sel.error_message }}</dd></template>
      </dl>
    </Modal>
  </div>
</template>

<style scoped>
.filters { display: flex; flex-wrap: wrap; gap: 10px; padding: 14px 16px; border-bottom: 1px solid var(--border); align-items: center; }
.filters select.input { flex: 0 1 auto; width: auto; min-width: 118px; max-width: 200px; }
.search { position: relative; flex: 1 1 200px; min-width: 180px; }
.search svg { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); pointer-events: none; color: var(--text-3); }
.search .input { padding-left: 32px; }
.clickable { cursor: pointer; }
.lat { font-variant-numeric: tabular-nums; }
.lat.fast { color: var(--text); }
.lat.mid { color: var(--warning); }
.lat.slow { color: var(--danger); }
.lat.session { color: var(--text-2); }
.pager { display: flex; align-items: center; gap: 8px; padding: 12px 16px; border-top: 1px solid var(--border); font-size: 13px; }
.dl { display: grid; grid-template-columns: 140px 1fr; gap: 10px 14px; margin: 0; font-size: 13px; }
.dl dt { color: var(--text-3); }
.dl dd { margin: 0; word-break: break-all; }
.err { color: var(--danger); }
.st-ok { display: inline-flex; align-items: center; gap: 6px; color: var(--success); font-size: 12px; }
.st-ok .dot { width: 5px; height: 5px; border-radius: 50%; background: currentColor; }
.src { color: var(--text-2); font-size: 12.5px; }
.type { font-size: 12px; color: var(--text-2); white-space: nowrap; }
.type.transcription, .type.speech, .type.realtime { color: var(--text); font-weight: 500; }
@media (max-width: 640px) {
  .filters select.input { flex: 1 1 calc(50% - 5px); max-width: none; min-width: 0; }
  .search { flex-basis: 100%; }
}
.tags { display: flex; flex-wrap: wrap; gap: 5px; word-break: normal; }
</style>
