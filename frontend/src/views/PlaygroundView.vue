<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Send, Square, Paperclip, X, Plus, Code2, SlidersHorizontal, Columns3, MessageSquare, RotateCcw, Trash2, Eye, AlertTriangle, KeyRound, RefreshCw, ImageOff } from 'lucide-vue-next'
import { api } from '../api'
import { CONTINUE_PROMPT, DEFAULT_PARAMS, EFFORT_LABELS, FALLBACK_MAX_TOKENS, buildCode, imageToDataUrl, runChat, sanitizeParams, uid } from '../playground'
import type { ChatRequest, Effort, EffortParam, Pane, PgMetrics, PgOptions, PgParams, Turn, WireMessage } from '../playground'
import NumInput from '../components/playground/NumInput.vue'
import { fmtCost, fmtInt } from '../format'
import { fail, toast } from '../stores/toast'
import ChatPane from '../components/playground/ChatPane.vue'
import ModelPicker from '../components/playground/ModelPicker.vue'
import Modal from '../components/Modal.vue'
import Toggle from '../components/Toggle.vue'
import CodeBlock from '../components/CodeBlock.vue'

const opts = ref<PgOptions | null>(null)
const loading = ref(true)
const params = reactive<PgParams>({ ...DEFAULT_PARAMS, ...sanitizeParams(JSON.parse(localStorage.getItem('gw-pg-params') || '{}') as Partial<PgParams>) })
watch(params, (p) => localStorage.setItem('gw-pg-params', JSON.stringify(p)), { deep: true })
const mode = ref<'chat' | 'compare'>((localStorage.getItem('gw-pg-mode') as 'chat' | 'compare') || 'chat')
watch(mode, (m) => localStorage.setItem('gw-pg-mode', m))
const savedModels: string[] = JSON.parse(localStorage.getItem('gw-pg-models') || '["default","fast","smart"]')
const panes = ref<Pane[]>([{ id: uid(), model: savedModels[0] || 'default', turns: [], controller: null }])
const compareModels = ref<string[]>(savedModels.slice(1, 3).length ? savedModels.slice(1, 3) : ['fast'])
const visiblePanes = computed(() => (mode.value === 'chat' ? panes.value.slice(0, 1) : panes.value))
watch(() => [mode.value, panes.value.map((p) => p.model)], () => {
  localStorage.setItem('gw-pg-models', JSON.stringify([...panes.value.map((p) => p.model), ...compareModels.value].slice(0, 3)))
}, { deep: true })

const input = ref('')
const attachments = ref<string[]>([])
const ta = ref<HTMLTextAreaElement | null>(null)
const fileEl = ref<HTMLInputElement | null>(null)
const showParams = ref(window.innerWidth > 1100)
const dragging = ref(false)

async function load() {
  loading.value = true
  try {
    opts.value = await api.get<PgOptions>('/api/playground/options')
    const live = new Set(opts.value.models.filter((m) => m.live).map((m) => m.name))
    const firstLive = opts.value.models.find((m) => m.live)?.name || 'default'
    for (const p of panes.value) if (!live.has(p.model)) p.model = firstLive
    if (params.key_id && !opts.value.keys.some((k) => k.id === params.key_id)) params.key_id = null
  } catch (e) { fail('Could not load playground options', e) } finally { loading.value = false }
}
onMounted(() => { load(); setMode(mode.value); nextTick(() => ta.value?.focus()) })
// the composer only renders once models are loaded: focus it then (unless the user already focused something)
watch(() => !!opts.value, (ready, was) => { if (ready && !was) nextTick(() => { if (!document.activeElement || document.activeElement === document.body) ta.value?.focus() }) })

const models = computed(() => opts.value?.models ?? [])
const modelInfo = (n: string) => models.value.find((m) => m.name === n)
const busy = computed(() => visiblePanes.value.some((p) => p.controller))
const hasTurns = computed(() => visiblePanes.value.some((p) => p.turns.length))
const selectedKey = computed(() => opts.value?.keys.find((k) => k.id === (params.key_id ?? opts.value?.default_key_id)))
const keyBlocked = computed(() => visiblePanes.value.filter((p) => selectedKey.value?.models.length && !selectedKey.value.models.includes(p.model)).map((p) => p.model))
const visionMissing = computed(() => (attachments.value.length ? visiblePanes.value.filter((p) => !modelInfo(p.model)?.vision).map((p) => p.model) : []))

// ---- per-model max_tokens defaults (model metadata) -------------------------------------------
const DEFAULT_CAP = 131072
const primary = computed(() => modelInfo(panes.value[0]?.model))
const capFor = (model: string) => modelInfo(model)?.max_output_tokens || DEFAULT_CAP
const defaultFor = (model: string) => Math.min(modelInfo(model)?.default_max_tokens || FALLBACK_MAX_TOKENS, capFor(model))
const maxCap = computed(() => capFor(panes.value[0]?.model))
/** follow the selected model's default until the user edits the value */
function applyModelDefault() { if (!params.max_tokens_edited && opts.value) params.max_tokens = defaultFor(panes.value[0].model) }
watch(() => [panes.value[0]?.model, opts.value], applyModelDefault)
function maxTokensFor(model: string) { return Math.min(params.max_tokens_edited ? params.max_tokens : defaultFor(model), capFor(model)) }
function markMaxEdited() { params.max_tokens_edited = true }
function useModelDefault() { params.max_tokens_edited = false; applyModelDefault() }
// log-scale slider 256 … cap
const maxSlider = computed({
  get: () => Math.log2(Math.max(256, params.max_tokens)),
  set: (v: number) => { params.max_tokens = Math.min(maxCap.value, Math.max(256, Math.round(2 ** v / 256) * 256)); markMaxEdited() },
})
const reasoningModels = computed(() => models.value.filter((m) => m.kind === 'model' && m.live && m.reasoning))

// ---- reasoning control (only levels the model honours) ----------------------------------------
const EFFORT_ORDER: Effort[] = ['off', 'low', 'medium', 'high']
const effortOptions = computed<EffortParam[]>(() => {
  const s = new Set(visiblePanes.value.flatMap((p) => modelInfo(p.model)?.reasoning_efforts ?? []))
  return s.size ? ['default', ...EFFORT_ORDER.filter((e) => s.has(e))] : []
})
function effortFor(model: string): EffortParam {
  const e = params.reasoning_effort
  return e !== 'default' && modelInfo(model)?.reasoning_efforts.includes(e) ? e : 'default'
}

// ---- images vs. non-vision models: ask before sending ----------------------------------------
interface PendingSend { action: 'send' | 'regen'; content: string; imgs: string[]; models: string[] }
const pendingSend = ref<PendingSend | null>(null)
const hasVisionModel = computed(() => models.value.some((m) => m.vision && m.live))
/** panes whose model cannot see images but would receive some (new attachments, or images earlier in the chat) */
function visionBlockers(newImgs: boolean) {
  return visiblePanes.value.filter((p) => !modelInfo(p.model)?.vision && (newImgs || (!p.stripImages && p.turns.some((t) => t.images?.length))))
}
const lastModel = new Map<number, string>()
watch(() => panes.value.map((p) => [p.id, p.model] as const), (list) => {
  for (const [id, m] of list) {
    const p = panes.value.find((x) => x.id === id)
    if (p && lastModel.has(id) && lastModel.get(id) !== m) { p.stripImages = false; pendingSend.value = null }
    lastModel.set(id, m)
  }
}, { immediate: true })
function resolveBlock(choice: 'vision' | 'strip' | 'cancel') {
  const ps = pendingSend.value
  if (!ps) return
  if (choice === 'cancel') { pendingSend.value = null; return }
  if (choice === 'vision') switchToVision()
  else for (const p of visionBlockers(ps.imgs.length > 0)) p.stripImages = true
  if (visionBlockers(false).length && choice === 'vision') return // no vision model available
  pendingSend.value = null
  if (ps.action === 'send') dispatch(ps.content, ps.imgs)
  else regenerateAll(true)
}

function setMode(m: 'chat' | 'compare') {
  mode.value = m
  if (m === 'compare' && panes.value.length < 2) {
    const base = panes.value[0]
    const extra = compareModels.value.length ? compareModels.value : ['fast']
    // new columns continue the same conversation (completed turns only)
    const copy = () => base.turns.filter((t) => t.role === 'user' || (t.state === 'done' && t.content)).map((t) => ({ ...t, id: uid(), images: t.images ? [...t.images] : undefined }))
    for (const model of extra.slice(0, 2)) panes.value.push({ id: uid(), model, turns: copy(), controller: null })
  } else if (m === 'chat' && panes.value.length > 1) {
    compareModels.value = panes.value.slice(1).map((p) => p.model)
    for (const p of panes.value.slice(1)) p.controller?.abort()
    panes.value = panes.value.slice(0, 1)
  }
}
function addPane() {
  if (panes.value.length >= 3) return
  const used = new Set(panes.value.map((p) => p.model))
  const next = models.value.find((m) => m.live && !used.has(m.name))?.name || 'default'
  panes.value.push({ id: uid(), model: next, turns: [], controller: null })
}
function removePane(i: number) {
  panes.value[i].controller?.abort()
  panes.value.splice(i, 1)
  if (panes.value.length < 2) mode.value = 'chat'
}

function history(p: Pane): WireMessage[] {
  return p.turns
    .filter((t) => t.role === 'user' || (t.state === 'done' && t.content))
    .map((t) => ({ role: t.role, content: t.content, images: t.images ?? [] }))
}
function buildRequest(model: string, messages: WireMessage[], compareId?: string, maxTokens?: number, strip = false): ChatRequest {
  const num = (v: unknown, d: number) => (typeof v === 'number' && Number.isFinite(v) ? v : d)
  return {
    model, messages, system: params.system || undefined,
    temperature: num(params.temperature, DEFAULT_PARAMS.temperature), top_p: num(params.top_p, DEFAULT_PARAMS.top_p),
    max_tokens: Math.round(maxTokens ?? maxTokensFor(model)), stream: params.stream, api_format: params.api_format, key_id: params.key_id,
    compare_id: compareId, reasoning_effort: effortFor(model), strip_images: strip || undefined,
  }
}

async function runPane(p: Pane, compareId?: string, opt: { target?: Turn; maxTokens?: number } = {}) {
  const strip = !modelInfo(p.model)?.vision && !!p.stripImages
  let msgs = history(p)
  let t: Turn
  if (opt.target) {
    // "Continue": keep the cut-off reply in the history, ask the model to go on, append to the same bubble
    t = opt.target
    msgs = [...msgs, { role: 'user', content: CONTINUE_PROMPT, images: [] }]
    t.state = 'pending'; t.error = null; t.continued = (t.continued || 0) + 1; t.startedAt = performance.now()
  } else {
    p.turns.push({ id: uid(), role: 'assistant', content: '', reasoning: '', state: 'pending', model: p.model, startedAt: performance.now() })
    t = p.turns[p.turns.length - 1] as Turn
  }
  const req = buildRequest(p.model, msgs, compareId, opt.maxTokens, strip)
  const ctrl = new AbortController()
  p.controller = ctrl
  let pend = ''
  let pendR = ''
  let raf = 0
  const flush = () => { raf = 0; if (pend) { t.content += pend; pend = '' } if (pendR) { t.reasoning = (t.reasoning || '') + pendR; pendR = '' } }
  const schedule = () => { if (!raf) raf = requestAnimationFrame(flush) }
  try {
    await runChat(req, {
      onMeta: () => { if (t.state === 'pending') t.state = 'streaming' },
      onDelta: (s) => { t.state = 'streaming'; pend += s; schedule() },
      onReasoning: (s) => { t.state = 'streaming'; pendR += s; schedule() },
      onDone: (m: PgMetrics | null) => { flush(); t.metrics = m; t.state = 'done' },
      onError: (msg, m) => { flush(); t.metrics = m; t.error = msg; t.state = 'error' },
    }, ctrl.signal)
  } catch (e) {
    flush()
    if ((e as Error).name === 'AbortError') { t.state = 'stopped'; t.elapsedMs = performance.now() - (t.startedAt || 0) }
    else { t.state = 'error'; t.error = (e as Error).message || String(e) }
  } finally {
    if (raf) cancelAnimationFrame(raf)
    flush()
    if (t.state === 'pending' || t.state === 'streaming') t.state = 'done'
    p.controller = null
  }
}

function send(text?: string) {
  const content = (text ?? input.value).trim()
  if ((!content && !attachments.value.length) || busy.value || !opts.value) return
  const imgs = [...attachments.value]
  nextTick(() => ta.value?.focus())
  const blockers = visionBlockers(imgs.length > 0)
  if (blockers.length) { pendingSend.value = { action: 'send', content, imgs, models: blockers.map((p) => p.model) }; return }
  dispatch(content, imgs)
}
function dispatch(content: string, imgs: string[]) {
  pendingSend.value = null
  input.value = ''
  attachments.value = []
  autosize()
  const cid = mode.value === 'compare' ? 'c' + Date.now().toString(36) : undefined
  for (const p of visiblePanes.value) {
    const stripped = imgs.length > 0 && !modelInfo(p.model)?.vision
    p.turns.push({ id: uid(), role: 'user', content, images: [...imgs], imagesStripped: stripped || undefined })
    runPane(p, cid)
  }
}
function regenerate(p: Pane, maxTokens?: number) {
  if (p.controller) return
  if (!modelInfo(p.model)?.vision && !p.stripImages && p.turns.some((t) => t.images?.length)) {
    pendingSend.value = { action: 'regen', content: '', imgs: [], models: [p.model] }
    return
  }
  while (p.turns.length && p.turns[p.turns.length - 1].role === 'assistant') p.turns.pop()
  if (p.turns.length) runPane(p, undefined, { maxTokens })
}
/** "Retry with 2× max tokens" / "Retry with more tokens" (empty reply): regenerate with a bigger budget */
function retryMore(p: Pane, t: Turn) {
  if (p.controller) return
  const used = t.metrics?.max_tokens || maxTokensFor(p.model)
  const next = Math.min(capFor(p.model), Math.max(used * 2, t.content ? 0 : defaultFor(p.model)))
  if (p === panes.value[0]) { params.max_tokens = next; params.max_tokens_edited = true }
  regenerate(p, next)
}
function continueReply(p: Pane, t: Turn) {
  if (p.controller) return
  runPane(p, undefined, { target: t, maxTokens: t.metrics?.max_tokens || undefined })
}
function regenerateAll(confirmed = false) {
  if (!confirmed) {
    const b = visionBlockers(false)
    if (b.length) { pendingSend.value = { action: 'regen', content: '', imgs: [], models: b.map((p) => p.model) }; return }
  }
  const cid = mode.value === 'compare' ? 'c' + Date.now().toString(36) : undefined
  for (const p of visiblePanes.value) {
    if (p.controller) continue
    while (p.turns.length && p.turns[p.turns.length - 1].role === 'assistant') p.turns.pop()
    if (p.turns.length) runPane(p, cid)
  }
}
function stop() { for (const p of panes.value) p.controller?.abort() }
function newChat() { stop(); for (const p of panes.value) p.turns = []; nextTick(() => ta.value?.focus()) }

function onKey(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send() }
  else if (e.key === 'Escape' && busy.value) { e.preventDefault(); stop() }
}
function autosize() {
  nextTick(() => { const el = ta.value; if (!el) return; el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 220) + 'px' })
}
watch(input, autosize)

async function addFiles(files: FileList | File[] | null) {
  if (!files) return
  for (const f of Array.from(files)) {
    if (!f.type.startsWith('image/')) { toast('error', 'Only images can be attached', f.name); continue }
    if (attachments.value.length >= 4) { toast('error', 'Up to 4 images per message'); break }
    try { attachments.value.push(await imageToDataUrl(f)) } catch (e) { fail('Could not read image', e) }
  }
  if (fileEl.value) fileEl.value.value = ''
}
function onPaste(e: ClipboardEvent) {
  const files = Array.from(e.clipboardData?.files || []).filter((f) => f.type.startsWith('image/'))
  if (files.length) { e.preventDefault(); addFiles(files) }
}
function onDrop(e: DragEvent) { dragging.value = false; addFiles(e.dataTransfer?.files || null) }
function switchToVision() {
  const v = models.value.find((m) => m.name === 'vision' && m.live) || models.value.find((m) => m.vision && m.live)
  if (!v) return
  for (const p of visiblePanes.value) if (!modelInfo(p.model)?.vision) p.model = v.name
}

// "View as code"
const showCode = ref(false)
const codeTab = ref<'curl' | 'python' | 'js'>('curl')
const codePane = ref(0)
const codeRequest = computed(() => {
  const p = visiblePanes.value[Math.min(codePane.value, visiblePanes.value.length - 1)]
  if (!p) return null
  const msgs = history(p)
  if (input.value.trim() || attachments.value.length) msgs.push({ role: 'user', content: input.value.trim(), images: attachments.value })
  else while (msgs.length && msgs[msgs.length - 1].role === 'assistant') msgs.pop() // reproduce the last request
  if (!msgs.length) msgs.push({ role: 'user', content: 'Hello!', images: [] })
  const r = buildRequest(p.model, msgs, undefined, undefined, !modelInfo(p.model)?.vision && (!!p.stripImages || msgs.some((m) => m.images.length)))
  delete r.key_id
  return r
})
const snippets = computed(() => (codeRequest.value && opts.value ? buildCode(codeRequest.value, { openai: opts.value.openai_base_url, anthropic: opts.value.anthropic_base_url }) : []))
const snippet = computed(() => snippets.value.find((s) => s.id === codeTab.value) ?? snippets.value[0])

// session totals
const totals = computed(() => {
  const ms = panes.value.flatMap((p) => p.turns).map((t) => t.metrics).filter((m): m is PgMetrics => !!m)
  return { requests: ms.length, tokens: ms.reduce((a, m) => a + m.tokens_in + m.tokens_out, 0), cost: ms.reduce((a, m) => a + (m.cost || 0), 0), errors: ms.filter((m) => !m.ok).length }
})
function resetParams() { const k = params.key_id; Object.assign(params, DEFAULT_PARAMS, { key_id: k }); applyModelDefault() }

const onResize = () => { if (window.innerWidth > 1100 && !showParams.value) showParams.value = true }
onMounted(() => window.addEventListener('resize', onResize))
onBeforeUnmount(() => { window.removeEventListener('resize', onResize); stop() })
</script>

<template>
  <div class="page pg">
    <div class="page-header">
      <div>
        <h1>Playground</h1>
        <p>Chat with any model or alias through the gateway, compare models side by side and copy the request as code.</p>
      </div>
      <div class="toolbar">
        <div class="segmented">
          <button :class="{ active: mode === 'chat' }" :aria-pressed="mode === 'chat'" @click="setMode('chat')"><MessageSquare :size="14" /> Chat</button>
          <button :class="{ active: mode === 'compare' }" :aria-pressed="mode === 'compare'" @click="setMode('compare')"><Columns3 :size="14" /> Compare</button>
        </div>
        <button class="btn" @click="showCode = true; codePane = 0"><Code2 /> View code</button>
        <button class="btn" :disabled="!hasTurns && !busy" @click="newChat"><Trash2 /> New chat</button>
        <button class="btn btn-icon params-btn" :class="{ on: showParams }" :aria-pressed="showParams" title="Parameters" aria-label="Parameters" @click="showParams = !showParams"><SlidersHorizontal /></button>
      </div>
    </div>

    <div class="pg-body" :class="{ 'with-side': showParams }">
      <div class="pg-main card" :class="{ dragging }" @dragover.prevent="dragging = true" @dragleave.self="dragging = false" @drop.prevent="onDrop">
        <div v-if="loading && !opts" class="loading"><div class="skeleton" style="height: 18px; width: 40%" /><div class="skeleton" style="height: 14px; width: 60%; margin-top: 10px" /></div>
        <template v-else>
          <div v-if="mode === 'chat'" class="chat-top">
            <ModelPicker v-model="panes[0].model" :models="models" class="main-picker" />
            <span class="muted hint-model" v-if="modelInfo(panes[0].model)?.upstream_id">{{ modelInfo(panes[0].model)?.upstream_id }}</span>
          </div>
          <div class="panes" :class="'n' + visiblePanes.length">
            <ChatPane v-for="(p, i) in visiblePanes" :key="p.id" :pane="p" :models="models" :compare="mode === 'compare'" :index="i" :removable="mode === 'compare' && panes.length > 2"
              :max-cap="capFor(p.model)" :default-max="defaultFor(p.model)"
              @model="p.model = $event" @regenerate="regenerate(p)" @remove="removePane(i)" @suggest="(s) => { input = s; ta?.focus() }"
              @continue="(t) => continueReply(p, t)" @retry="(t) => retryMore(p, t)" />
            <button v-if="mode === 'compare' && panes.length < 3" class="add-pane" @click="addPane"><Plus :size="18" /><span>Add model</span></button>
          </div>

          <div class="composer">
            <div v-if="pendingSend" class="block-card" role="alertdialog" aria-label="Model cannot see images">
              <div class="bc-h"><ImageOff :size="16" /><div>
                <b><span class="mono">{{ pendingSend.models.join(', ') }}</span> can't see images.</b>
                <span>{{ pendingSend.action === 'send' && pendingSend.imgs.length ? 'Your message has ' + pendingSend.imgs.length + ' image(s)' : 'This conversation contains images' }} — sending them would make the model answer without seeing them. Nothing was sent yet.</span>
              </div></div>
              <div class="bc-acts">
                <button class="btn btn-sm btn-primary" :disabled="!hasVisionModel" @click="resolveBlock('vision')"><Eye /> Switch to vision model</button>
                <button class="btn btn-sm" @click="resolveBlock('strip')"><ImageOff /> Send without image</button>
                <button class="btn btn-sm btn-ghost" @click="resolveBlock('cancel')">Cancel</button>
              </div>
            </div>
            <div v-if="(visionMissing.length && !pendingSend) || keyBlocked.length" class="warns">
              <div v-if="visionMissing.length && !pendingSend" class="warn"><AlertTriangle :size="14" /><span><b class="mono">{{ visionMissing.join(', ') }}</b> can't see images — you'll be asked before anything is sent.</span><button class="btn btn-sm" :disabled="!hasVisionModel" @click="switchToVision"><Eye /> Use vision model</button></div>
              <div v-if="keyBlocked.length" class="warn"><KeyRound :size="14" /><span>Key <b class="mono">{{ selectedKey?.name }}</b> is not allowed to use <b class="mono">{{ keyBlocked.join(', ') }}</b> — expect a 401.</span></div>
            </div>
            <div v-if="attachments.length" class="atts">
              <div v-for="(a, i) in attachments" :key="i" class="att"><img :src="a" alt="attachment" /><button class="rm" title="Remove" @click="attachments.splice(i, 1)"><X :size="12" /></button></div>
            </div>
            <div class="box">
              <button class="btn btn-ghost btn-icon" title="Attach image (or paste / drop)" aria-label="Attach image (or paste / drop)" @click="fileEl?.click()"><Paperclip /></button>
              <input ref="fileEl" type="file" accept="image/*" multiple hidden @change="addFiles(($event.target as HTMLInputElement).files)" />
              <textarea ref="ta" v-model="input" rows="1" class="ta" aria-label="Message" :placeholder="mode === 'compare' ? 'Send the same prompt to ' + visiblePanes.length + ' models…' : 'Message ' + panes[0].model + '…'" @keydown="onKey" @paste="onPaste" />
              <button v-if="hasTurns && !busy" class="btn btn-ghost btn-icon" title="Regenerate last response" aria-label="Regenerate last response" @click="regenerateAll()"><RotateCcw /></button>
              <button v-if="busy" class="btn btn-danger send" title="Stop (Esc)" @click="stop"><Square /> Stop</button>
              <button v-else class="btn btn-primary send" :disabled="!input.trim() && !attachments.length" title="Send (Enter)" @click="send()"><Send /> Send</button>
            </div>
            <div class="foot muted">
              <span><kbd>Enter</kbd> send · <kbd>Shift</kbd>+<kbd>Enter</kbd> newline · <kbd>Esc</kbd> stop</span>
              <span class="spacer" />
              <span class="chip">{{ params.api_format === 'anthropic' ? 'Anthropic /v1/messages' : 'OpenAI /v1/chat/completions' }}</span>
              <span class="chip">{{ params.stream ? 'streaming' : 'non-streaming' }}</span>
              <span class="chip"><KeyRound :size="12" /> {{ selectedKey?.name || 'playground' }}</span>
            </div>
          </div>
        </template>
        <div v-if="dragging" class="drop"><Paperclip :size="22" /> Drop images to attach</div>
      </div>

      <div v-if="showParams" class="side-backdrop" @click="showParams = false" />
      <aside v-if="showParams" class="pg-side card">
        <div class="card-header"><div><h3>Parameters</h3><div class="sub">Applied to the next request</div></div><button class="btn btn-ghost btn-sm" @click="resetParams">Reset</button></div>
        <div class="card-body side-body">
          <div class="field">
            <label>API key</label>
            <select v-model="params.key_id" class="input">
              <option :value="null">playground (internal)</option>
              <option v-for="k in opts?.keys.filter((k) => !k.internal)" :key="k.id" :value="k.id">{{ k.name }} · {{ k.key_prefix }}</option>
            </select>
            <span class="hint">Requests count against this virtual key's spend, budget and rate limits. The key never reaches the browser.</span>
          </div>
          <div class="field">
            <label>API format</label>
            <div class="segmented full">
              <button :class="{ active: params.api_format === 'openai' }" :aria-pressed="params.api_format === 'openai'" @click="params.api_format = 'openai'">OpenAI</button>
              <button :class="{ active: params.api_format === 'anthropic' }" :aria-pressed="params.api_format === 'anthropic'" @click="params.api_format = 'anthropic'">Anthropic</button>
            </div>
            <span class="hint mono">{{ params.api_format === 'anthropic' ? 'POST /v1/messages' : 'POST /v1/chat/completions' }}</span>
          </div>
          <div class="field row-field"><label id="lbl-stream">Stream tokens</label><Toggle v-model="params.stream" aria-labelledby="lbl-stream" /></div>
          <div class="field">
            <label>System prompt</label>
            <textarea v-model="params.system" class="input" rows="4" placeholder="You are a helpful assistant." />
          </div>
          <div class="field">
            <div class="lbl-row"><label>Temperature</label><NumInput v-model="params.temperature" :min="0" :max="2" :step="0.05" /></div>
            <input v-model.number="params.temperature" type="range" min="0" max="2" step="0.05" class="range" />
          </div>
          <div class="field">
            <div class="lbl-row"><label>Top P</label><NumInput v-model="params.top_p" :min="0" :max="1" :step="0.01" /></div>
            <input v-model.number="params.top_p" type="range" min="0" max="1" step="0.01" class="range" />
          </div>
          <div class="field">
            <div class="lbl-row"><label>Max tokens</label><NumInput v-model="params.max_tokens" integer :min="1" :max="maxCap" :step="1024" class="wide" @edited="markMaxEdited" /></div>
            <input v-model.number="maxSlider" type="range" :min="8" :max="Math.log2(maxCap)" step="0.01" class="range" aria-label="Max tokens (log scale)" />
            <div class="range-lbl muted"><span>256</span><span>{{ fmtInt(maxCap) }}</span></div>
            <span class="hint">
              <template v-if="params.max_tokens_edited">Custom value · <a href="#" @click.prevent="useModelDefault">use model default ({{ fmtInt(defaultFor(panes[0].model)) }})</a></template>
              <template v-else>Default for <span class="mono">{{ panes[0].model }}</span>{{ mode === 'compare' ? ' (each column uses its own model default)' : '' }}</template>
            </span>
            <span class="hint" :class="{ warnt: primary?.reasoning && params.max_tokens < 2048 }">
              <template v-if="reasoningModels.length">Reasoning models ({{ reasoningModels.map((m) => m.display_name).join(', ') }}) think before answering; thinking tokens count against max tokens{{ primary?.reasoning && params.max_tokens < 2048 ? ' — this value is likely too low.' : '.' }}</template>
              <template v-else>None of the live models is marked as a reasoning model.</template>
            </span>
          </div>
          <div v-if="effortOptions.length" class="field">
            <label>Reasoning</label>
            <div class="segmented full effort">
              <button v-for="e in effortOptions" :key="e" :class="{ active: params.reasoning_effort === e }" :aria-pressed="params.reasoning_effort === e" :disabled="params.api_format !== 'openai'" @click="params.reasoning_effort = e">{{ EFFORT_LABELS[e] }}</button>
            </div>
            <span class="hint">
              <template v-if="params.api_format !== 'openai'">Only available with the OpenAI API format.</template>
              <template v-else>Off disables thinking (<span class="mono">reasoning.enabled=false</span>); Low/Medium/High set <span class="mono">reasoning_effort</span>. Only levels the model honours are shown{{ mode === 'compare' ? '; columns whose model lacks a level use its default' : '' }}.</template>
            </span>
          </div>
          <div v-if="mode === 'compare'" class="field">
            <label>Compare columns</label>
            <span class="hint">Pick a model at the top of each column. The same prompt and parameters are sent to every column in parallel.</span>
            <button class="btn btn-sm" :disabled="panes.length >= 3" @click="addPane"><Plus /> Add model</button>
          </div>
          <div class="session">
            <div class="s-h"><span>This session</span><button class="btn btn-ghost btn-sm btn-icon" title="Reload models & keys" aria-label="Reload models & keys" @click="load"><RefreshCw :class="{ spin: loading }" /></button></div>
            <div class="s-grid">
              <div><b>{{ fmtInt(totals.requests) }}</b><span>requests</span></div>
              <div><b>{{ fmtInt(totals.tokens) }}</b><span>tokens</span></div>
              <div><b>{{ fmtCost(totals.cost) }}</b><span>cost</span></div>
            </div>
            <RouterLink to="/logs?source=playground" class="s-link">View playground requests in Logs →</RouterLink>
          </div>
        </div>
      </aside>
    </div>

    <Modal v-if="showCode" title="View as code" subtitle="Reproduce this request with your own virtual key (exported as $LORA_GATEWAY_API_KEY)" width="820px" @close="showCode = false">
      <div class="code-tools">
        <div class="segmented">
          <button v-for="s in snippets" :key="s.id" :class="{ active: codeTab === s.id }" :aria-pressed="codeTab === s.id" @click="codeTab = s.id">{{ s.title }}</button>
        </div>
        <select v-if="visiblePanes.length > 1" v-model.number="codePane" class="input pane-sel">
          <option v-for="(p, i) in visiblePanes" :key="p.id" :value="i">Column {{ i + 1 }} · {{ p.model }}</option>
        </select>
      </div>
      <CodeBlock v-if="snippet" :code="snippet.code" :lang="snippet.lang" :title="snippet.title" class="snip" />
      <p class="hint" style="margin: 12px 0 0">{{ input.trim() ? 'Includes the conversation plus your unsent message' : 'Reproduces the last request of this conversation' }}, with the current system prompt and parameters. Create a key under <RouterLink to="/keys">API keys</RouterLink>, then <span class="mono">export LORA_GATEWAY_API_KEY=sk-…</span></p>
    </Modal>
  </div>
</template>

<style scoped>
.pg { display: flex; flex-direction: column; height: calc(100vh - 60px); height: calc(100dvh - 60px); padding-bottom: 20px; max-width: none; }
.pg .page-header { margin-bottom: 16px; }
.segmented button { display: inline-flex; align-items: center; gap: 6px; }
.params-btn.on { background: var(--bg-subtle); color: var(--text); border-color: var(--border-strong); }
.pg-body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; position: relative; }
.pg-body.with-side { grid-template-columns: minmax(0, 1fr) 320px; }
.pg-main { display: flex; flex-direction: column; min-height: 0; overflow: hidden; position: relative; }
.loading { padding: 24px; }
.chat-top { display: flex; align-items: center; gap: 12px; padding: 12px 16px; border-bottom: 1px solid var(--border); }
.main-picker { width: min(460px, 100%); }
.hint-model { font-size: 11.5px; font-family: var(--font); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.panes { flex: 1; min-height: 0; display: grid; gap: 12px; }
.panes.n1 { grid-template-columns: minmax(0, 1fr); }
.panes.n2 { grid-template-columns: repeat(2, minmax(0, 1fr)) auto; padding: 12px 12px 0; }
.panes.n3 { grid-template-columns: repeat(3, minmax(0, 1fr)); padding: 12px 12px 0; }
.add-pane { width: 110px; border: 1px dashed var(--border-strong); border-radius: var(--radius); background: transparent; color: var(--text-3); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; cursor: pointer; font: 500 13px var(--font); }
.add-pane:hover { color: var(--text); border-color: var(--text-3); background: var(--bg-elev); }
.composer { padding: 10px 16px 12px; border-top: 1px solid var(--border); background: var(--bg-elev); }
.warns { display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px; }
.warn { display: flex; align-items: center; gap: 8px; font-size: 12.5px; background: var(--warning-soft); color: var(--text); padding: 6px 10px; border-radius: var(--radius-sm); }
.warn svg { color: var(--warning); flex-shrink: 0; }
.warn .btn { margin-left: auto; }
.atts { display: flex; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
.att { position: relative; }
.att img { width: 64px; height: 64px; object-fit: cover; border-radius: var(--radius-sm); border: 1px solid var(--border); display: block; }
.rm { position: absolute; top: -6px; right: -6px; width: 20px; height: 20px; border-radius: 50%; border: 0; background: var(--text); color: var(--bg-elev); display: grid; place-items: center; cursor: pointer; }
.box { display: flex; align-items: flex-end; gap: 6px; border: 1px solid var(--border-strong); border-radius: var(--radius); padding: 6px; background: var(--bg-elev); transition: border-color .15s, box-shadow .15s; }
.box:focus-within { border-color: var(--focus); box-shadow: 0 0 0 1px var(--focus); }
.ta { flex: 1; border: 0; outline: none; resize: none; background: transparent; color: var(--text); font: 14px/1.5 var(--font); padding: 7px 4px; max-height: 220px; min-height: 36px; }
.send { min-width: 92px; }
.foot { display: flex; align-items: center; gap: 8px; margin-top: 8px; font-size: 11.5px; flex-wrap: wrap; }
kbd { font: 10.5px var(--font); background: var(--bg-subtle); border: 1px solid var(--border); border-radius: 3px; padding: 0 4px; color: var(--text-2); }
.chip { display: inline-flex; align-items: center; gap: 4px; background: transparent; border: 1px solid var(--border); border-radius: 3px; padding: 0 6px; color: var(--text-2); font-family: var(--font); font-size: 11px; }
.drop { position: absolute; inset: 0; background: color-mix(in srgb, var(--bg-elev) 88%, transparent); border: 1px dashed var(--primary); border-radius: var(--radius); display: flex; align-items: center; justify-content: center; gap: 10px; color: var(--primary); font-weight: 600; pointer-events: none; z-index: 5; }
.pg-side { display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
.side-body { overflow-y: auto; flex: 1; }
.side-body .field { margin-bottom: 16px; }
.row-field { flex-direction: row; align-items: center; justify-content: space-between; }
.lbl-row { display: flex; align-items: center; justify-content: space-between; }
.lbl-row label { font-size: 12.5px; font-weight: 500; color: var(--text-2); }
.num { width: 72px; height: 28px; padding: 0 8px; text-align: right; font-family: var(--font); font-size: 12px; font-variant-numeric: tabular-nums; }
.num.wide { width: 96px; }
.range { width: 100%; accent-color: var(--ink); }
.segmented.full { display: flex; }
.segmented.full button { flex: 1; justify-content: center; }
.warnt { color: var(--warning); }
.segmented.effort button { padding-left: 4px; padding-right: 4px; min-width: 0; font-size: 12.5px; }
.range-lbl { display: flex; justify-content: space-between; font-size: 11px; margin-top: -2px; }
.block-card { border: 1px solid color-mix(in srgb, var(--warning) 45%, transparent); background: var(--warning-soft); border-radius: var(--radius-sm); padding: 10px 12px; margin-bottom: 8px; display: flex; flex-direction: column; gap: 8px; font-size: 13px; }
.bc-h { display: flex; gap: 10px; align-items: flex-start; }
.bc-h svg { color: var(--warning); flex-shrink: 0; margin-top: 2px; }
.bc-h > div { display: flex; flex-direction: column; gap: 2px; }
.bc-h span { color: var(--text-2); font-size: 12.5px; }
.bc-acts { display: flex; gap: 8px; flex-wrap: wrap; padding-left: 26px; }
.session { border-top: 1px solid var(--border); padding-top: 14px; margin-top: 4px; }
.s-h { display: flex; align-items: center; justify-content: space-between; font-size: 12.5px; font-weight: 500; color: var(--text-2); }
.s-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 8px 0 10px; }
.s-grid div { background: transparent; border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 7px 8px; display: flex; flex-direction: column; }
.s-grid b { font: 500 13.5px var(--font); font-variant-numeric: tabular-nums; }
.s-grid span { font-size: 11px; color: var(--text-3); }
.s-link { font-size: 12.5px; }
.side-backdrop { display: none; }
.code-tools { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
.pane-sel { width: auto; max-width: 100%; }
.code-tools .segmented { max-width: 100%; overflow-x: auto; }
.snip :deep(pre) { max-height: 52vh; }
@media (max-width: 1280px) { .panes.n3 { grid-template-columns: repeat(3, minmax(260px, 1fr)); overflow-x: auto; } }
@media (max-width: 1100px) {
  .pg-body.with-side { grid-template-columns: minmax(0, 1fr); }
  .pg-side { position: fixed; top: 60px; right: 0; bottom: 0; width: min(340px, 92vw); z-index: 45; border-radius: 0; box-shadow: var(--shadow-lg); }
  .side-backdrop { display: block; position: fixed; inset: 60px 0 0 0; background: var(--overlay); z-index: 44; }
}
@media (max-width: 900px) {
  .pg { height: auto; min-height: calc(100dvh - 60px); }
  .pg-main { min-height: calc(100dvh - 190px); }
  .panes.n2, .panes.n3 { grid-template-columns: minmax(0, 1fr); overflow: visible; }
  .panes.n2 :deep(.pane), .panes.n3 :deep(.pane) { min-height: 320px; max-height: 60vh; }
  .add-pane { width: 100%; height: 56px; flex-direction: row; }
  .hint-model { display: none; }
  .foot > span:first-child { display: none; }
}
</style>
