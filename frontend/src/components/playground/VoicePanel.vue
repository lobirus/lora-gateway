<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Mic, Square, Upload, Volume2, Download, Headphones, PhoneOff, Loader2, AlertTriangle, Languages, Copy, Radio, Hand } from 'lucide-vue-next'
import type { PgModel } from '../../playground'
import { Recorder, RealtimeClient, extFor, micAvailable, pickDefault, synthesize, transcribe } from '../../voice'
import type { RtTurn, SttResult, TtsResult } from '../../voice'
import { fmtCost, fmtMs } from '../../format'
import { fail, ok } from '../../stores/toast'
import EmptyState from '../EmptyState.vue'

const props = defineProps<{ models: PgModel[]; keyId: number | null }>()
const tab = ref<'stt' | 'tts' | 'talk'>((localStorage.getItem('gw-voice-tab') as 'stt' | 'tts' | 'talk') || 'stt')
watch(tab, (t) => localStorage.setItem('gw-voice-tab', t))
const LANGS = [['', 'Auto-detect'], ['en', 'English'], ['hu', 'Hungarian'], ['de', 'German'], ['fr', 'French'], ['es', 'Spanish'], ['it', 'Italian'], ['nl', 'Dutch'], ['pl', 'Polish'], ['pt', 'Portuguese'], ['ro', 'Romanian'], ['cs', 'Czech'], ['sk', 'Slovak'], ['uk', 'Ukrainian'], ['ja', 'Japanese'], ['zh', 'Chinese']]
const saved = JSON.parse(localStorage.getItem('gw-voice') || '{}')
const st = reactive({ sttModel: saved.sttModel || '', language: saved.language || '', task: 'transcribe' as 'transcribe' | 'translate',
  ttsModel: saved.ttsModel || '', voice: saved.voice || '', format: saved.format || 'mp3', text: saved.text || 'Hello! This is your Lora gateway speaking, with an open-weight voice.',
  talkModel: saved.talkModel || '', talkVoice: saved.talkVoice || '', talkMode: (saved.talkMode || 'vad') as 'vad' | 'ptt', talkLang: saved.talkLang || '', instructions: saved.instructions || '' })
watch(st, (v) => localStorage.setItem('gw-voice', JSON.stringify({ ...v, task: undefined })), { deep: true })

const sttModels = computed(() => props.models.filter((m) => m.audio === 'transcription'))
const ttsModels = computed(() => props.models.filter((m) => m.audio === 'speech'))
const rtModels = computed(() => props.models.filter((m) => m.audio === 'realtime'))
const info = (n: string) => props.models.find((m) => m.name === n)
function ensureDefaults() {
  if (!info(st.sttModel)?.live) st.sttModel = pickDefault(props.models, 'transcription', 'stt')
  if (!info(st.ttsModel)?.live) st.ttsModel = pickDefault(props.models, 'speech', 'tts')
  if (!info(st.talkModel)?.live) st.talkModel = pickDefault(props.models, 'realtime', 'talk')
}
watch(() => props.models, ensureDefaults, { immediate: true })
const voices = computed(() => info(st.ttsModel)?.voices || [])
watch(() => st.ttsModel, () => { if (!voices.value.includes(st.voice)) st.voice = info(st.ttsModel)?.default_voice || voices.value[0] || '' }, { immediate: true })
const talkVoices = computed(() => info(st.talkModel)?.voices || [])
watch(() => st.talkModel, () => { if (!talkVoices.value.includes(st.talkVoice)) st.talkVoice = info(st.talkModel)?.default_voice || talkVoices.value[0] || '' }, { immediate: true })
const label = (m: PgModel) => m.kind === 'alias' ? m.name + ' → ' + (m.target || '?') : m.name

const micErr = micAvailable()

// ------------------------------------------------------------------ speech to text
const rec = ref<Recorder | null>(null)
const recMs = ref(0)
const level = ref(0)
let recTimer = 0
const sttBusy = ref(false)
const sttResults = ref<(SttResult & { name: string; at: number; ms?: number })[]>([])
const fileEl = ref<HTMLInputElement | null>(null)
const recBtn = ref<HTMLButtonElement | null>(null)
async function toggleRecord() {
  if (rec.value) return finishRecord()
  try {
    const r = new Recorder()
    await r.start((v) => (level.value = v))
    rec.value = r
    recTimer = window.setInterval(() => (recMs.value = r.elapsed()), 200)
  } catch (e) { fail('Microphone unavailable', e) }
}
async function finishRecord() {
  const r = rec.value
  if (!r) return
  clearInterval(recTimer); rec.value = null
  const out = await r.stop()
  recMs.value = 0
  await runStt(out.blob, 'recording.' + extFor(out.mime), out.ms)
}
function cancelRecord() { rec.value?.cancel(); rec.value = null; clearInterval(recTimer); recMs.value = 0; nextTick(() => recBtn.value?.focus()) }
async function runStt(blob: Blob, name: string, ms?: number) {
  if (!st.sttModel) return
  sttBusy.value = true
  try {
    const r = await transcribe(blob, name, { model: st.sttModel, language: st.language || undefined, task: st.task, key_id: props.keyId })
    sttResults.value.unshift({ ...r, name, at: Date.now(), ms })
    sttResults.value = sttResults.value.slice(0, 6)
  } catch (e) { fail('Transcription failed', e) } finally { sttBusy.value = false }
}
function onFile(f: File | undefined | null) {
  if (!f) return
  if (f.size > 25 * 1024 * 1024) return fail('File too large', 'Audio files are limited to 25 MB')
  runStt(f, f.name)
  if (fileEl.value) fileEl.value.value = ''
}
const dragging = ref(false)
function copy(t: string) { navigator.clipboard.writeText(t).then(() => ok('Copied')) }

// ------------------------------------------------------------------ text to speech
const ttsBusy = ref(false)
const tts = ref<TtsResult | null>(null)
const ttsErr = ref('')
const player = ref<HTMLAudioElement | null>(null)
async function speakText() {
  if (!st.text.trim() || !st.ttsModel || ttsBusy.value) return
  ttsBusy.value = true; ttsErr.value = ''
  try {
    if (tts.value) URL.revokeObjectURL(tts.value.url)
    tts.value = await synthesize({ model: st.ttsModel, input: st.text.trim(), voice: st.voice || null, format: st.format, key_id: props.keyId })
    await nextTick()
    player.value?.play().catch(() => {})
  } catch (e) { ttsErr.value = (e as Error).message } finally { ttsBusy.value = false }
}
const ttsName = computed(() => 'speech-' + (st.voice || 'voice').replace(/\W+/g, '-') + '.' + (st.format === 'opus' ? 'ogg' : st.format))

// ------------------------------------------------------------------ talk (realtime)
const rt = ref<RealtimeClient | null>(null)
const rtStatus = ref<'idle' | 'connecting' | 'connected' | 'listening' | 'thinking' | 'speaking' | 'closed' | 'error'>('idle')
const rtDetail = ref('')
const rtTurns = ref<RtTurn[]>([])
const rtInfo = reactive<{ engine: string; pipeline?: { stt: string; llm: string; tts: string }; connect_ms?: number; key_name?: string }>({ engine: '' })
const rtUsage = ref({ input_tokens: 0, output_tokens: 0, audio_in: 0, audio_out: 0 })
const rtStarted = ref(0)
const now = ref(Date.now())
let clock = 0
const talkText = ref('')
const pttDown = ref(false)
const pttBtn = ref<HTMLButtonElement | null>(null)
const transcriptEl = ref<HTMLElement | null>(null)
const live = computed(() => !!rt.value && !['idle', 'closed', 'error'].includes(rtStatus.value) || rtStatus.value === 'error' && !!rt.value)
async function startTalk() {
  if (rt.value) return
  rtTurns.value = []; rtDetail.value = ''; rtUsage.value = { input_tokens: 0, output_tokens: 0, audio_in: 0, audio_out: 0 }
  const c = new RealtimeClient({
    onStatus: (s, d) => { rtStatus.value = s; if (d) rtDetail.value = d; if (s === 'closed') endTalk(false) },
    onTurns: (t) => { rtTurns.value = t; nextTick(() => { const el = transcriptEl.value; if (el) el.scrollTop = el.scrollHeight }) },
    onLevel: (v) => (level.value = v),
    onInfo: (i) => { if (i.engine) Object.assign(rtInfo, i) },
    onUsage: (u) => (rtUsage.value = u),
  })
  rt.value = c
  try {
    await c.connect({ model: st.talkModel, voice: st.talkVoice || null, key_id: props.keyId, mode: st.talkMode, instructions: st.instructions || undefined, language: st.talkLang || undefined })
    rtStarted.value = Date.now()
    clock = window.setInterval(() => (now.value = Date.now()), 500)
    rtStatus.value = st.talkMode === 'vad' ? 'listening' : 'connected'
    nextTick(() => (st.talkMode === 'ptt' ? pttBtn.value?.focus() : null))
  } catch (e) {
    rtDetail.value = (e as Error).message
    rtStatus.value = 'error'
    c.close(); rt.value = null
  }
}
function endTalk(close = true) {
  if (close) rt.value?.close()
  rt.value = null
  clearInterval(clock)
  if (rtStatus.value !== 'error') rtStatus.value = 'idle'
}
watch(() => st.talkMode, (m) => rt.value?.setMode(m, st.talkVoice))
function pttDownFn() { if (!rt.value || pttDown.value) return; pttDown.value = true; rt.value.pressTalk() }
function pttUpFn() { if (!pttDown.value) return; pttDown.value = false; rt.value?.releaseTalk() }
function sendTalkText() { const t = talkText.value.trim(); if (!t || !rt.value) return; rt.value.sendText(t); talkText.value = '' }
const elapsed = computed(() => (rtStarted.value && rt.value ? Math.round((now.value - rtStarted.value) / 1000) : 0))
const fmtClock = (s: number) => Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0')
const lat = computed(() => rtTurns.value.filter((t) => t.role === 'assistant' && t.latency_ms != null).map((t) => t.latency_ms as number))
const avgLat = computed(() => (lat.value.length ? lat.value.reduce((a, b) => a + b, 0) / lat.value.length : null))
const rtCost = computed(() => {
  const m = info(st.talkModel)
  if (!m || rtInfo.engine === 'pipeline') return null
  const u = rtUsage.value
  const textIn = u.input_tokens - u.audio_in, textOut = u.output_tokens - u.audio_out
  return (textIn * (m.input_price_per_m || 0) + textOut * (m.output_price_per_m || 0) + u.audio_in * (m.audio_input_price_per_m || 0) + u.audio_out * (m.audio_output_price_per_m || 0)) / 1e6
})
const statusText: Record<string, string> = { idle: 'Not connected', connecting: 'Connecting…', connected: 'Connected', listening: 'Listening', thinking: 'Thinking', speaking: 'Speaking', closed: 'Disconnected', error: 'Error' }

// ------------------------------------------------------------------ keyboard
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    if (rec.value) { e.preventDefault(); cancelRecord() }
    else if (rt.value && tab.value === 'talk') { e.preventDefault(); endTalk() }
  }
}
function onPttKey(e: KeyboardEvent, down: boolean) {
  if (e.key !== ' ' && e.key !== 'Enter') return
  e.preventDefault()
  if (e.repeat) return
  if (down) pttDownFn(); else pttUpFn()
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => { document.removeEventListener('keydown', onKey); cancelRecord(); endTalk(); if (tts.value) URL.revokeObjectURL(tts.value.url) })
defineExpose({ focusFirst: () => nextTick(() => (document.querySelector('.vp-tabs button.active') as HTMLElement | null)?.focus()) })
</script>

<template>
  <div class="vp">
    <div class="vp-head">
      <div class="segmented vp-tabs" role="tablist" aria-label="Voice tools">
        <button role="tab" :aria-selected="tab === 'stt'" :class="{ active: tab === 'stt' }" @click="tab = 'stt'"><Mic :size="14" /> Speech to text</button>
        <button role="tab" :aria-selected="tab === 'tts'" :class="{ active: tab === 'tts' }" @click="tab = 'tts'"><Volume2 :size="14" /> Text to speech</button>
        <button role="tab" :aria-selected="tab === 'talk'" :class="{ active: tab === 'talk' }" @click="tab = 'talk'"><Headphones :size="14" /> Talk</button>
      </div>
      <span class="muted small">Requests use the API key chosen under Parameters and appear in Logs as <span class="mono">source:playground</span>.</span>
    </div>

    <!-- speech to text -->
    <section v-if="tab === 'stt'" class="vp-body" aria-label="Speech to text">
      <EmptyState v-if="!sttModels.some((m) => m.live)" :icon="Mic" title="No transcription model is enabled" description="Enable a transcription model (e.g. Whisper on Together) under Models, or add a provider key." />
      <template v-else>
        <div class="controls">
          <div class="field"><label>Model</label>
            <select v-model="st.sttModel" class="input"><option v-for="m in sttModels" :key="m.name" :value="m.name" :disabled="!m.live">{{ label(m) }}{{ m.live ? '' : ' (off)' }}</option></select>
            <span class="hint" v-if="info(st.sttModel)?.price_per_minute">{{ fmtCost(info(st.sttModel)?.price_per_minute) }} per audio minute</span>
          </div>
          <div class="field"><label>Language</label>
            <select v-model="st.language" class="input" :disabled="st.task === 'translate'"><option v-for="[c, n] in LANGS" :key="c" :value="c">{{ n }}</option></select>
          </div>
          <div class="field"><label>Task</label>
            <div class="segmented full"><button :class="{ active: st.task === 'transcribe' }" :aria-pressed="st.task === 'transcribe'" @click="st.task = 'transcribe'">Transcribe</button><button :class="{ active: st.task === 'translate' }" :aria-pressed="st.task === 'translate'" @click="st.task = 'translate'"><Languages :size="13" /> To English</button></div>
          </div>
        </div>
        <div class="drop" :class="{ over: dragging, rec: !!rec }" @dragover.prevent="dragging = true" @dragleave="dragging = false" @drop.prevent="dragging = false; onFile($event.dataTransfer?.files?.[0])">
          <template v-if="rec">
            <span class="rec-dot" aria-hidden="true" /><b class="tnum">{{ fmtClock(Math.floor(recMs / 1000)) }}</b>
            <span class="meter" aria-hidden="true"><span :style="{ width: Math.round(level * 100) + '%' }" /></span>
            <button ref="recBtn" class="btn btn-primary" autofocus @click="finishRecord"><Square /> Stop and transcribe</button>
            <button class="btn btn-ghost" @click="cancelRecord">Cancel <kbd>Esc</kbd></button>
          </template>
          <template v-else>
            <button ref="recBtn" class="btn btn-primary" :disabled="!!micErr || sttBusy" :title="micErr || 'Record from the microphone'" @click="toggleRecord"><Mic /> Record</button>
            <button class="btn" :disabled="sttBusy" @click="fileEl?.click()"><Upload /> Upload audio</button>
            <input ref="fileEl" type="file" accept="audio/*,video/webm,.m4a,.mp3,.wav,.ogg,.flac,.webm" hidden @change="onFile(($event.target as HTMLInputElement).files?.[0])" />
            <span class="muted small">or drop a file (≤ 25 MB: mp3, wav, m4a, ogg, webm, flac)</span>
            <span v-if="sttBusy" class="muted small busy"><Loader2 :size="14" class="spin" /> Transcribing…</span>
          </template>
        </div>
        <p v-if="micErr" class="hint warnt"><AlertTriangle :size="13" /> {{ micErr }}</p>
        <div class="results" aria-live="polite">
          <div v-for="r in sttResults" :key="r.at" class="result card">
            <div v-if="r.ok" class="rtext">{{ r.text || '(no speech detected)' }}</div>
            <div v-else class="err"><AlertTriangle :size="14" /> {{ r.error }}</div>
            <div class="meta">
              <span class="m"><i>File</i>{{ r.name }}</span>
              <span v-if="r.metrics" class="m"><i>Latency</i>{{ fmtMs(r.metrics.latency_ms) }}</span>
              <span v-if="r.metrics?.audio_seconds" class="m"><i>Audio</i>{{ r.metrics.audio_seconds.toFixed(1) }} s</span>
              <span v-else-if="r.ms" class="m"><i>Audio</i>{{ (r.ms / 1000).toFixed(1) }} s</span>
              <span v-if="r.metrics" class="m"><i>Cost</i>{{ fmtCost(r.metrics.cost) }}</span>
              <span v-if="r.language" class="m"><i>Language</i>{{ r.language }}</span>
              <span v-if="r.metrics" class="m"><i>Route</i>{{ r.metrics.model }}<template v-if="r.metrics.resolved_model && r.metrics.resolved_model !== r.metrics.model"> → {{ r.metrics.resolved_model }}</template> · {{ r.metrics.key_name }}</span>
              <span class="spacer" />
              <button v-if="r.ok && r.text" class="btn btn-sm btn-icon" title="Copy text" aria-label="Copy text" @click="copy(r.text)"><Copy /></button>
            </div>
          </div>
        </div>
      </template>
    </section>

    <!-- text to speech -->
    <section v-else-if="tab === 'tts'" class="vp-body" aria-label="Text to speech">
      <EmptyState v-if="!ttsModels.some((m) => m.live)" :icon="Volume2" title="No speech model is enabled" description="Enable a speech model (e.g. Kokoro on Together) under Models, or add a provider key." />
      <template v-else>
        <div class="field">
          <div class="lbl-row"><label>Text</label><span class="muted small tnum">{{ st.text.length }} / 4096</span></div>
          <textarea v-model="st.text" class="input" rows="5" maxlength="4096" autofocus @keydown.ctrl.enter.prevent="speakText" @keydown.meta.enter.prevent="speakText" />
        </div>
        <div class="controls four">
          <div class="field"><label>Model</label><select v-model="st.ttsModel" class="input"><option v-for="m in ttsModels" :key="m.name" :value="m.name" :disabled="!m.live">{{ label(m) }}{{ m.live ? '' : ' (off)' }}</option></select>
            <span class="hint" v-if="info(st.ttsModel)?.price_per_m_chars">{{ fmtCost(info(st.ttsModel)?.price_per_m_chars) }} per 1M characters</span></div>
          <div class="field"><label>Voice</label>
            <select v-if="voices.length" v-model="st.voice" class="input"><option v-for="v in voices" :key="v" :value="v">{{ v }}</option></select>
            <input v-else v-model="st.voice" class="input" placeholder="voice name" />
          </div>
          <div class="field"><label>Format</label><select v-model="st.format" class="input"><option value="mp3">MP3</option><option value="wav">WAV</option><option value="opus">Opus</option><option value="flac">FLAC</option></select></div>
          <div class="field act"><button class="btn btn-primary" :disabled="ttsBusy || !st.text.trim()" title="Speak (Ctrl+Enter)" @click="speakText"><Loader2 v-if="ttsBusy" class="spin" /><Volume2 v-else /> Speak</button></div>
        </div>
        <div v-if="ttsErr" class="err"><AlertTriangle :size="14" /> {{ ttsErr }}</div>
        <div v-if="tts" class="result card">
          <audio ref="player" :src="tts.url" controls class="player" aria-label="Generated speech" />
          <div class="meta">
            <span class="m"><i>First byte</i>{{ fmtMs(tts.ttfb_ms) }}</span>
            <span class="m"><i>Total</i>{{ fmtMs(tts.total_ms) }}</span>
            <span class="m"><i>Characters</i>{{ tts.chars }}</span>
            <span class="m"><i>Cost</i>{{ fmtCost(tts.cost) }}</span>
            <span class="m"><i>Voice</i>{{ tts.voice }}</span>
            <span class="m"><i>Size</i>{{ Math.round(tts.blob.size / 1024) }} KB · {{ tts.mime }}</span>
            <span class="spacer" />
            <a class="btn btn-sm" :href="tts.url" :download="ttsName"><Download /> Download</a>
          </div>
        </div>
      </template>
    </section>

    <!-- talk -->
    <section v-else class="vp-body talk" aria-label="Talk">
      <EmptyState v-if="!rtModels.some((m) => m.live)" :icon="Headphones" title="No realtime-capable model is enabled"
        description="Talk needs a realtime model: enable the open-weight pipeline model lora-talk (Lora voice pipeline provider), or add an OpenAI key and enable gpt-realtime." />
      <template v-else>
        <div class="controls four">
          <div class="field"><label>Model</label><select v-model="st.talkModel" class="input" :disabled="!!rt"><option v-for="m in rtModels" :key="m.name" :value="m.name" :disabled="!m.live">{{ label(m) }}{{ m.live ? '' : ' (off)' }}</option></select></div>
          <div class="field"><label>Voice</label>
            <select v-if="talkVoices.length" v-model="st.talkVoice" class="input" :disabled="!!rt"><option v-for="v in talkVoices" :key="v" :value="v">{{ v }}</option></select>
            <input v-else v-model="st.talkVoice" class="input" :disabled="!!rt" placeholder="default" />
          </div>
          <div class="field"><label>Mode</label>
            <div class="segmented full">
              <button :class="{ active: st.talkMode === 'vad' }" :aria-pressed="st.talkMode === 'vad'" @click="st.talkMode = 'vad'"><Radio :size="13" /> Hands-free</button>
              <button :class="{ active: st.talkMode === 'ptt' }" :aria-pressed="st.talkMode === 'ptt'" @click="st.talkMode = 'ptt'"><Hand :size="13" /> Push-to-talk</button>
            </div>
          </div>
          <div class="field act">
            <button v-if="!rt" class="btn btn-primary" :disabled="!!micErr || rtStatus === 'connecting'" @click="startTalk"><Headphones /> Start session</button>
            <button v-else class="btn btn-danger" @click="endTalk()"><PhoneOff /> End <kbd>Esc</kbd></button>
          </div>
        </div>
        <details class="more"><summary>Instructions and language</summary>
          <div class="grid-2">
            <div class="field"><label>Instructions</label><textarea v-model="st.instructions" class="input" rows="2" :disabled="!!rt" placeholder="You are a helpful voice assistant. Keep answers short." /></div>
            <div class="field"><label>Spoken language</label><select v-model="st.talkLang" class="input" :disabled="!!rt"><option v-for="[c, n] in LANGS" :key="c" :value="c">{{ n }}</option></select><span class="hint">Helps the speech-to-text step; auto-detect otherwise.</span></div>
          </div>
        </details>
        <div class="stage card">
          <div class="stage-h">
            <span class="status" :class="rtStatus"><span class="sdot" />{{ statusText[rtStatus] }}</span>
            <span class="meter" aria-hidden="true"><span :style="{ width: Math.round(level * 100) + '%' }" /></span>
            <span class="muted small" v-if="rtInfo.engine === 'pipeline' && rtInfo.pipeline">pipeline: {{ rtInfo.pipeline.stt }} → {{ rtInfo.pipeline.llm }} → {{ rtInfo.pipeline.tts }}</span>
            <span class="muted small" v-else-if="rtInfo.engine === 'relay'">provider realtime via LiteLLM</span>
            <span class="spacer" />
            <span class="m"><i>Session</i>{{ fmtClock(elapsed) }}</span>
            <span class="m"><i>Avg latency</i>{{ fmtMs(avgLat) }}</span>
            <span class="m" title="Tokens in / out (audio tokens in brackets)"><i>Tokens</i>{{ rtUsage.input_tokens }} / {{ rtUsage.output_tokens }}<template v-if="rtUsage.audio_in || rtUsage.audio_out"> ({{ rtUsage.audio_in }} / {{ rtUsage.audio_out }} audio)</template></span>
            <span class="m" :title="rtInfo.engine === 'pipeline' ? 'Each step is logged with its own cost in Logs' : 'Estimated from the model\'s audio-token prices'"><i>Cost</i>{{ rtCost == null ? 'see Logs' : fmtCost(rtCost) }}</span>
          </div>
          <div v-if="rtStatus === 'error' && rtDetail" class="err" role="alert"><AlertTriangle :size="14" /> {{ rtDetail }}</div>
          <div ref="transcriptEl" class="transcript" aria-live="polite">
            <p v-if="!rtTurns.length" class="muted small empty-t">{{ rt ? (st.talkMode === 'vad' ? 'Start speaking — the model answers when you pause.' : 'Hold the button (or Space) while you speak, release to send.') : 'Start a session and talk. Transcripts and per-turn latency appear here.' }}</p>
            <div v-for="t in rtTurns" :key="t.id" class="turn" :class="t.role">
              <span class="who">{{ t.role === 'user' ? 'You' : 'Assistant' }}</span>
              <span class="txt">{{ t.text }}<span v-if="t.state === 'cancelled'" class="muted"> (interrupted)</span></span>
              <span v-if="t.role === 'assistant' && t.latency_ms != null" class="lat tnum" title="From end of your speech to first audio">{{ fmtMs(t.latency_ms) }}<template v-if="t.stt_ms != null"> · STT {{ fmtMs(t.stt_ms) }}</template><template v-if="t.llm_ms != null"> · LLM {{ fmtMs(t.llm_ms) }}</template></span>
            </div>
          </div>
          <div class="stage-f">
            <button v-if="st.talkMode === 'ptt'" ref="pttBtn" class="btn ptt" :class="{ down: pttDown }" :disabled="!rt" aria-label="Hold to talk (Space)"
              @pointerdown.prevent="pttDownFn" @pointerup="pttUpFn" @pointerleave="pttUpFn" @keydown="onPttKey($event, true)" @keyup="onPttKey($event, false)"><Mic /> {{ pttDown ? 'Release to send' : 'Hold to talk' }} <kbd>Space</kbd></button>
            <form class="typebox" @submit.prevent="sendTalkText">
              <input v-model="talkText" class="input" :disabled="!rt" placeholder="…or type a message" aria-label="Type a message to the voice model" />
              <button class="btn" :disabled="!rt || !talkText.trim()">Send</button>
            </form>
          </div>
        </div>
      </template>
    </section>
  </div>
</template>

<style scoped>
.vp { display: flex; flex-direction: column; min-height: 0; flex: 1; overflow: hidden; }
.vp-head { display: flex; align-items: center; gap: 14px; padding: 12px 16px; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
.vp-tabs button { display: inline-flex; align-items: center; gap: 6px; }
.small { font-size: 12px; }
.vp-body { padding: 16px; overflow-y: auto; flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 14px; }
.controls { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; align-items: end; }
.controls.four { grid-template-columns: minmax(0, 1.2fr) minmax(0, .9fr) minmax(230px, 1.2fr) auto; }
.controls .field { margin: 0; }
.field.act { justify-content: flex-end; }
.segmented.full { display: flex; }
.segmented.full button { flex: 1; justify-content: center; display: inline-flex; align-items: center; gap: 5px; }
.lbl-row { display: flex; justify-content: space-between; align-items: center; }
.drop { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 16px; border: 1px dashed var(--border-strong); border-radius: var(--radius); background: var(--bg); }
.drop.over { border-color: var(--focus); background: var(--bg-subtle); }
.drop.rec { border-style: solid; border-color: color-mix(in srgb, var(--danger) 45%, transparent); }
.rec-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--danger); animation: pulse 1.2s infinite; }
@keyframes pulse { 50% { opacity: .35; } }
.meter { width: 120px; height: 4px; background: var(--bg-subtle); border-radius: 2px; overflow: hidden; display: inline-block; }
.meter span { display: block; height: 100%; background: var(--text-3); transition: width .08s linear; }
.busy { display: inline-flex; gap: 6px; align-items: center; }
kbd { font: 10.5px var(--font); background: var(--bg-subtle); border: 1px solid var(--border); border-radius: 3px; padding: 0 4px; color: var(--text-2); margin-left: 4px; }
.btn kbd { background: transparent; }
.results { display: flex; flex-direction: column; gap: 10px; }
.result { padding: 12px 14px; }
.rtext { white-space: pre-wrap; font-size: 14px; line-height: 1.55; }
.err { display: flex; gap: 8px; align-items: flex-start; color: var(--danger); background: var(--danger-soft); border-radius: var(--radius-sm); padding: 8px 10px; font-size: 13px; }
.err svg { flex-shrink: 0; margin-top: 2px; }
.meta { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 14px; margin-top: 10px; padding-top: 8px; border-top: 1px dashed var(--border); font-size: 12px; font-variant-numeric: tabular-nums; }
.m i { font-style: normal; color: var(--text-3); margin-right: 5px; }
.player { width: 100%; height: 40px; }
.warnt { color: var(--warning); display: flex; gap: 6px; align-items: center; }
.more summary { cursor: pointer; font-size: 12.5px; color: var(--text-2); }
.more summary:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; border-radius: 3px; }
.more .grid-2 { margin-top: 10px; }
.stage { display: flex; flex-direction: column; min-height: 320px; flex: 1; }
.stage-h { display: flex; align-items: center; gap: 12px; padding: 10px 14px; border-bottom: 1px solid var(--border); flex-wrap: wrap; font-size: 12px; }
.status { display: inline-flex; align-items: center; gap: 7px; font-weight: 500; font-size: 12.5px; min-width: 110px; }
.sdot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-3); }
.status.listening .sdot { background: var(--success); animation: pulse 1.2s infinite; }
.status.thinking .sdot { background: var(--warning); }
.status.speaking .sdot { background: var(--accent); }
.status.connected .sdot { background: var(--success); }
.status.error .sdot { background: var(--danger); }
.stage > .err { margin: 10px 14px 0; }
.transcript { flex: 1; overflow-y: auto; padding: 14px; display: flex; flex-direction: column; gap: 10px; min-height: 160px; }
.empty-t { margin: auto; text-align: center; }
.turn { display: grid; grid-template-columns: 76px 1fr auto; gap: 10px; align-items: baseline; font-size: 14px; }
.turn .who { font-size: 11.5px; color: var(--text-3); font-weight: 500; }
.turn.user .txt { color: var(--text-2); }
.turn .lat { font-size: 11.5px; color: var(--text-3); white-space: nowrap; }
.stage-f { display: flex; gap: 10px; padding: 10px 14px; border-top: 1px solid var(--border); align-items: center; flex-wrap: wrap; }
.ptt { min-width: 190px; justify-content: center; }
.ptt.down { background: var(--ink); color: var(--on-ink); border-color: var(--ink); }
.typebox { display: flex; gap: 8px; flex: 1; min-width: 220px; }
@media (max-width: 900px) { .controls, .controls.four { grid-template-columns: minmax(0, 1fr); } .turn { grid-template-columns: 1fr; gap: 2px; } }
</style>
