import { auth, logout } from './stores/auth'
import type { PgModel } from './playground'

// ---------------------------------------------------------------- model helpers
export const isLive = (m: PgModel) => m.live
export const byAudio = (models: PgModel[], kind: PgModel['audio']) => models.filter((m) => m.audio === kind && m.live)
/** preferred alias first (e.g. "stt"), then aliases, then models */
export function pickDefault(models: PgModel[], kind: PgModel['audio'], preferred: string): string {
  const live = byAudio(models, kind)
  return (live.find((m) => m.name === preferred) || live.find((m) => m.kind === 'alias') || live[0])?.name || ''
}

// ---------------------------------------------------------------- recorder
export interface Recording { blob: Blob; ms: number; mime: string }
const MIMES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
export function micAvailable(): string | null {
  if (!window.isSecureContext) return 'The microphone needs HTTPS (or localhost).'
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') return 'This browser cannot record audio.'
  return null
}
export class Recorder {
  private rec: MediaRecorder | null = null
  private stream: MediaStream | null = null
  private chunks: Blob[] = []
  private started = 0
  level = 0
  private ctx: AudioContext | null = null
  private raf = 0
  async start(onLevel?: (v: number) => void) {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
    const mime = MIMES.find((m) => MediaRecorder.isTypeSupported(m)) || ''
    this.rec = new MediaRecorder(this.stream, mime ? { mimeType: mime } : undefined)
    this.chunks = []
    this.rec.ondataavailable = (e) => { if (e.data.size) this.chunks.push(e.data) }
    this.rec.start(250)
    this.started = performance.now()
    if (onLevel) {
      this.ctx = new AudioContext()
      const an = this.ctx.createAnalyser()
      an.fftSize = 512
      this.ctx.createMediaStreamSource(this.stream).connect(an)
      const buf = new Uint8Array(an.fftSize)
      const tick = () => {
        an.getByteTimeDomainData(buf)
        let s = 0
        for (const v of buf) s += ((v - 128) / 128) ** 2
        this.level = Math.min(1, Math.sqrt(s / buf.length) * 4)
        onLevel(this.level)
        this.raf = requestAnimationFrame(tick)
      }
      tick()
    }
  }
  elapsed() { return this.started ? performance.now() - this.started : 0 }
  stop(): Promise<Recording> {
    return new Promise((resolve) => {
      const rec = this.rec!
      const mime = rec.mimeType || 'audio/webm'
      rec.onstop = () => { const ms = this.elapsed(); this.cleanup(); resolve({ blob: new Blob(this.chunks, { type: mime }), ms, mime }) }
      rec.stop()
    })
  }
  cancel() { try { this.rec?.stop() } catch { /* ignore */ } this.cleanup() }
  private cleanup() {
    cancelAnimationFrame(this.raf)
    this.stream?.getTracks().forEach((t) => t.stop())
    this.ctx?.close().catch(() => {})
    this.ctx = null; this.stream = null; this.started = 0
  }
}
export const extFor = (mime: string) => (mime.includes('ogg') ? 'ogg' : mime.includes('mp4') ? 'm4a' : mime.includes('wav') ? 'wav' : mime.includes('mpeg') ? 'mp3' : 'webm')

// ---------------------------------------------------------------- API calls
function authHeaders(): Record<string, string> { return auth.token ? { Authorization: 'Bearer ' + auth.token } : {} }
async function errorText(res: Response): Promise<string> {
  try {
    const j = await res.json()
    const d = j.detail ?? j.error
    return typeof d === 'string' ? d : Array.isArray(d) ? d.map((x: { msg: string }) => x.msg).join('; ') : 'HTTP ' + res.status
  } catch { return 'HTTP ' + res.status }
}

export interface SttMetrics { latency_ms: number; status: number; model: string; resolved_model: string | null; request_id: string | null; key_name: string; bytes: number; cost: number | null; audio_seconds: number | null; task: string }
export interface SttResult { ok: boolean; text?: string; language?: string | null; error?: string; metrics?: SttMetrics }
export async function transcribe(file: Blob, name: string, o: { model: string; language?: string; prompt?: string; task?: 'transcribe' | 'translate'; key_id?: number | null }, signal?: AbortSignal): Promise<SttResult> {
  const fd = new FormData()
  fd.append('file', file, name)
  fd.append('model', o.model)
  if (o.language) fd.append('language', o.language)
  if (o.prompt) fd.append('prompt', o.prompt)
  fd.append('task', o.task || 'transcribe')
  if (o.key_id) fd.append('key_id', String(o.key_id))
  const t0 = performance.now()
  const res = await fetch('/api/playground/transcribe', { method: 'POST', headers: authHeaders(), body: fd, signal })
  if (res.status === 401) { logout(true); throw new Error('Session expired, please sign in again') }
  if (!res.ok && !(res.headers.get('content-type') || '').includes('json')) return { ok: false, error: 'HTTP ' + res.status }
  const j = await res.json().catch(() => null)
  if (!j) return { ok: false, error: 'HTTP ' + res.status }
  if (j.detail) return { ok: false, error: typeof j.detail === 'string' ? j.detail : 'HTTP ' + res.status }
  if (j.metrics && !j.metrics.latency_ms) j.metrics.latency_ms = performance.now() - t0
  return j
}

export interface TtsResult { blob: Blob; url: string; ttfb_ms: number; total_ms: number; cost: number | null; voice: string; chars: number; request_id: string | null; model: string | null; mime: string }
export async function synthesize(o: { model: string; input: string; voice?: string | null; format?: string; speed?: number; instructions?: string; key_id?: number | null }, signal?: AbortSignal): Promise<TtsResult> {
  const t0 = performance.now()
  const res = await fetch('/api/playground/speech', {
    method: 'POST', signal, headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: o.model, input: o.input, voice: o.voice || undefined, response_format: o.format || 'mp3', speed: o.speed, instructions: o.instructions || undefined, key_id: o.key_id || undefined }),
  })
  if (res.status === 401) { logout(true); throw new Error('Session expired, please sign in again') }
  if (!res.ok) throw new Error(await errorText(res))
  const ttfb = performance.now() - t0
  const blob = await res.blob()
  const h = (k: string) => res.headers.get(k)
  return { blob, url: URL.createObjectURL(blob), ttfb_ms: ttfb, total_ms: performance.now() - t0, cost: h('x-gw-cost') ? Number(h('x-gw-cost')) : null,
    voice: decodeURIComponent(h('x-gw-voice') || o.voice || ''), chars: Number(h('x-gw-chars') || o.input.length), request_id: h('x-gw-request-id'), model: h('x-gw-model'), mime: blob.type || 'audio/mpeg' }
}

// ---------------------------------------------------------------- reading replies aloud
let current: { audio: HTMLAudioElement; ctrl: AbortController; id: string; url?: string } | null = null
export const speaking = { id: '' as string }
type Listener = (id: string, state: 'loading' | 'playing' | 'idle', err?: string) => void
const listeners = new Set<Listener>()
export function onSpeak(l: Listener) { listeners.add(l); return () => listeners.delete(l) }
const notify: Listener = (id, s, e) => listeners.forEach((l) => l(id, s, e))
export function stopSpeaking() {
  if (!current) return
  const c = current
  current = null
  c.ctrl.abort(); c.audio.pause()
  if (c.url) URL.revokeObjectURL(c.url)
  notify(c.id, 'idle')
}
export async function speak(id: string, text: string, o: { model: string; voice?: string | null; key_id?: number | null }) {
  stopSpeaking()
  const ctrl = new AbortController()
  const audio = new Audio()
  current = { audio, ctrl, id }
  notify(id, 'loading')
  try {
    const r = await synthesize({ model: o.model, input: plainText(text).slice(0, 4096), voice: o.voice, key_id: o.key_id }, ctrl.signal)
    if (current?.id !== id) { URL.revokeObjectURL(r.url); return }
    current.url = r.url
    audio.src = r.url
    audio.onended = () => { if (current?.id === id) stopSpeaking() }
    await audio.play()
    notify(id, 'playing')
  } catch (e) {
    if ((e as Error).name === 'AbortError') return
    if (current?.id === id) current = null
    notify(id, 'idle', (e as Error).message)
  }
}
/** markdown -> text worth reading aloud */
export function plainText(md: string): string {
  return md.replace(/\x60{3}[\s\S]*?\x60{3}/g, ' (code omitted) ').replace(/\x60([^\x60]+)\x60/g, '$1').replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').replace(/^#{1,6}\s+/gm, '').replace(/[*_~>|]+/g, '').replace(/^\s*[-+]\s+/gm, '').replace(/\n{2,}/g, '\n').trim()
}

// ---------------------------------------------------------------- realtime (Talk)
export interface RtTurn { id: string; role: 'user' | 'assistant'; text: string; state: 'live' | 'done' | 'cancelled' | 'error'; latency_ms?: number | null; stt_ms?: number | null; llm_ms?: number | null; cost?: number | null }
export interface RtHandlers {
  onStatus: (s: 'connecting' | 'connected' | 'listening' | 'thinking' | 'speaking' | 'closed' | 'error', detail?: string) => void
  onTurns: (turns: RtTurn[]) => void
  onLevel?: (v: number) => void
  onInfo?: (info: Record<string, unknown>) => void
  onUsage?: (u: { input_tokens: number; output_tokens: number; audio_in: number; audio_out: number }) => void
}
const WORKLET = 'class P extends AudioWorkletProcessor{process(i){const c=i[0]&&i[0][0];if(c)this.port.postMessage(c.slice(0));return true}}registerProcessor("pcm-tap",P)'

function b64FromInt16(a: Int16Array): string {
  const u = new Uint8Array(a.buffer, a.byteOffset, a.byteLength)
  let s = ''
  for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode(...u.subarray(i, i + 0x8000))
  return btoa(s)
}
function int16FromB64(b: string): Int16Array {
  const s = atob(b)
  const u = new Uint8Array(s.length)
  for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i)
  return new Int16Array(u.buffer, 0, u.length >> 1)
}

export class RealtimeClient {
  ws: WebSocket | null = null
  private ctx: AudioContext | null = null
  private stream: MediaStream | null = null
  private node: AudioWorkletNode | null = null
  private playAt = 0
  private sources: AudioBufferSourceNode[] = []
  turns: RtTurn[] = []
  private open = false
  mode: 'ptt' | 'vad' = 'vad'
  private talking = false
  private speechEndAt = 0
  private firstAudio = new Set<string>()
  private engine = ''
  private responding = false
  private lastResponseAt = 0
  usage = { input_tokens: 0, output_tokens: 0, audio_in: 0, audio_out: 0 }
  constructor(private h: RtHandlers) {}

  async connect(o: { model: string; voice?: string | null; key_id?: number | null; mode: 'ptt' | 'vad'; instructions?: string; language?: string }) {
    this.mode = o.mode
    this.h.onStatus('connecting')
    const tr = await fetch('/api/playground/realtime/ticket', { method: 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify({ model: o.model, key_id: o.key_id || undefined }) })
    if (tr.status === 401) { logout(true); throw new Error('Session expired') }
    if (!tr.ok) throw new Error(await errorText(tr))
    const { path } = await tr.json()
    this.ctx = new AudioContext({ sampleRate: 24000 })
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } })
    const url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }))
    await this.ctx.audioWorklet.addModule(url)
    URL.revokeObjectURL(url)
    const src = this.ctx.createMediaStreamSource(this.stream)
    this.node = new AudioWorkletNode(this.ctx, 'pcm-tap')
    let pending: Float32Array[] = []
    let n = 0
    this.node.port.onmessage = (e: MessageEvent<Float32Array>) => {
      const f = e.data
      let s = 0
      for (let i = 0; i < f.length; i++) s += f[i] * f[i]
      this.h.onLevel?.(Math.min(1, Math.sqrt(s / f.length) * 5))
      if (!this.open || (this.mode === 'ptt' && !this.talking)) return
      pending.push(f); n += f.length
      if (n >= 2400) { // 100 ms
        const out = new Int16Array(n)
        let o2 = 0
        for (const c of pending) for (let i = 0; i < c.length; i++) out[o2++] = Math.max(-32768, Math.min(32767, c[i] * 32767))
        pending = []; n = 0
        this.send({ type: 'input_audio_buffer.append', audio: b64FromInt16(out) })
      }
    }
    src.connect(this.node)
    // a worklet only runs while it is pulled by the destination: route it through a muted gain
    const mute = this.ctx.createGain()
    mute.gain.value = 0
    this.node.connect(mute).connect(this.ctx.destination)
    if (this.ctx.state === 'suspended') await this.ctx.resume()
    const proto = location.protocol === 'https:' ? 'wss://' : 'ws://'
    const ws = new WebSocket(proto + location.host + path)
    this.ws = ws
    await new Promise<void>((resolve, reject) => {
      const to = setTimeout(() => reject(new Error('Timed out connecting')), 25000)
      ws.onmessage = (ev) => this.onEvent(JSON.parse(ev.data), o, () => { clearTimeout(to); resolve() }, (m) => { clearTimeout(to); reject(new Error(m)) })
      ws.onerror = () => { clearTimeout(to); reject(new Error('WebSocket error')) }
      ws.onclose = (e) => { clearTimeout(to); this.open = false; if (e.code === 4401) reject(new Error('Ticket rejected')); this.h.onStatus('closed', e.reason || undefined) }
    })
  }
  private send(o: unknown) { if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(o)) }
  private sessionUpdate(o: { voice?: string | null; mode: 'ptt' | 'vad'; instructions?: string; language?: string }) {
    const td = o.mode === 'vad' ? { type: 'server_vad', threshold: 0.5, prefix_padding_ms: 300, silence_duration_ms: 600, create_response: true, interrupt_response: true } : null
    const transcription: Record<string, string> = { model: 'gpt-4o-mini-transcribe' }
    if (o.language) transcription.language = o.language
    const session: Record<string, unknown> = { type: 'realtime', audio: { input: { format: { type: 'audio/pcm', rate: 24000 }, turn_detection: td, transcription }, output: { format: { type: 'audio/pcm', rate: 24000 }, ...(o.voice ? { voice: o.voice } : {}) } } }
    if (o.instructions) session.instructions = o.instructions
    this.send({ type: 'session.update', session })
  }
  setMode(m: 'ptt' | 'vad', voice?: string | null) { this.mode = m; this.sessionUpdate({ mode: m, voice }) }
  private turn(id: string, role: RtTurn['role']): RtTurn {
    let t = this.turns.find((x) => x.id === id)
    if (!t) { t = { id, role, text: '', state: 'live' }; this.turns.push(t) }
    return t
  }
  private emitTurns() { this.h.onTurns([...this.turns.map((t) => ({ ...t }))]) }
  private onEvent(ev: Record<string, any>, o: { voice?: string | null; mode: 'ptt' | 'vad'; instructions?: string; language?: string }, ready: () => void, fail: (m: string) => void) { // eslint-disable-line @typescript-eslint/no-explicit-any
    const t: string = ev.type
    if (t === 'gateway.connected') { this.engine = ev.engine; this.h.onInfo?.(ev) }
    else if (t === 'session.created') { this.open = true; this.sessionUpdate(o); this.h.onStatus('connected'); ready() }
    else if (t === 'session.updated') { this.h.onInfo?.({ session: ev.session }) }
    else if (t === 'error') {
      const msg = ev.error?.message || 'Realtime error'
      const benign = ['conversation_already_has_active_response', 'response_cancel_not_active', 'input_audio_buffer_commit_empty'].includes(ev.error?.code)
      if (!this.open) fail(msg)
      else if (!benign) this.h.onStatus('error', msg)
    }
    else if (t === 'response.created') { this.responding = true; this.lastResponseAt = performance.now() }
    else if (t === 'input_audio_buffer.speech_started') { this.h.onStatus('listening'); this.interrupt() }
    else if (t === 'input_audio_buffer.speech_stopped' || t === 'input_audio_buffer.committed') { this.speechEndAt = performance.now(); this.h.onStatus('thinking') }
    else if (t === 'conversation.item.created' && ev.item?.role === 'user' && ev.item?.content?.[0]?.type === 'input_audio') { this.turn(ev.item.id, 'user').text = '…'; this.emitTurns() }
    else if (t === 'conversation.item.input_audio_transcription.completed') { const u = this.turn(ev.item_id, 'user'); u.text = ev.transcript || '(nothing heard)'; u.state = 'done'; this.emitTurns() }
    else if (t === 'conversation.item.input_audio_transcription.delta') { const u = this.turn(ev.item_id, 'user'); u.text = (u.text === '…' ? '' : u.text) + (ev.delta || ''); this.emitTurns() }
    else if (t === 'response.output_audio_transcript.delta' || t === 'response.audio_transcript.delta' || t === 'response.output_text.delta' || t === 'response.text.delta') { const a = this.turn(ev.item_id, 'assistant'); a.text += ev.delta || ''; this.emitTurns() }
    else if (t === 'response.output_audio.delta' || t === 'response.audio.delta') {
      if (!this.firstAudio.has(ev.item_id)) {
        this.firstAudio.add(ev.item_id)
        const a = this.turn(ev.item_id, 'assistant')
        a.latency_ms = this.speechEndAt ? Math.round(performance.now() - this.speechEndAt) : null
        this.emitTurns()
      }
      this.h.onStatus('speaking')
      this.play(int16FromB64(ev.delta))
    }
    else if (t === 'response.done') {
      this.responding = false
      const r = ev.response || {}
      const out = (r.output || [])[0]
      if (out?.id) {
        const a = this.turn(out.id, 'assistant')
        a.state = r.status === 'completed' ? 'done' : r.status === 'cancelled' ? 'cancelled' : 'error'
        const gm = r.gateway_metrics
        if (gm) { a.stt_ms = gm.stt_ms ?? null; a.llm_ms = gm.llm_ttft_ms ?? null; if (gm.first_audio_ms != null) a.latency_ms = gm.first_audio_ms }
        if (!a.text && out.content?.[0]?.transcript) a.text = out.content[0].transcript
        this.emitTurns()
      }
      const u = r.usage || {}
      this.usage.input_tokens += u.input_tokens || 0
      this.usage.output_tokens += u.output_tokens || 0
      this.usage.audio_in += u.input_token_details?.audio_tokens || 0
      this.usage.audio_out += u.output_token_details?.audio_tokens || 0
      this.h.onUsage?.({ ...this.usage })
      const left = this.ctx ? Math.max(0, this.playAt - this.ctx.currentTime) : 0
      setTimeout(() => { if (this.open) this.h.onStatus(this.mode === 'vad' ? 'listening' : 'connected') }, left * 1000)
    }
  }
  private play(pcm: Int16Array) {
    if (!this.ctx) return
    const buf = this.ctx.createBuffer(1, pcm.length, 24000)
    const ch = buf.getChannelData(0)
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 32768
    const s = this.ctx.createBufferSource()
    s.buffer = buf
    s.connect(this.ctx.destination)
    const at = Math.max(this.ctx.currentTime + 0.03, this.playAt)
    s.start(at)
    this.playAt = at + buf.duration
    this.sources.push(s)
    s.onended = () => { this.sources = this.sources.filter((x) => x !== s) }
  }
  interrupt() { for (const s of this.sources) { try { s.stop() } catch { /* already stopped */ } } this.sources = []; this.playAt = 0 }
  /** push-to-talk */
  pressTalk() {
    if (!this.open || this.mode !== 'ptt') return
    this.interrupt()
    if (this.responding) this.send({ type: 'response.cancel' })
    this.send({ type: 'input_audio_buffer.clear' })
    this.talking = true
    this.h.onStatus('listening')
  }
  releaseTalk() {
    if (!this.talking) return
    this.talking = false
    setTimeout(() => {
      this.send({ type: 'input_audio_buffer.commit' })
      this.speechEndAt = performance.now()
      this.h.onStatus('thinking')
      // ask for the reply unless the server already started one (some servers keep VAD on)
      setTimeout(() => { if (!this.responding && this.lastResponseAt < this.speechEndAt) this.send({ type: 'response.create' }) }, 350)
    }, 150)
  }
  sendText(text: string) {
    this.send({ type: 'conversation.item.create', item: { type: 'message', role: 'user', content: [{ type: 'input_text', text }] } })
    this.turns.push({ id: 'txt' + Date.now(), role: 'user', text, state: 'done' })
    this.emitTurns()
    this.speechEndAt = performance.now()
    this.send({ type: 'response.create' })
    this.h.onStatus('thinking')
  }
  get engineName() { return this.engine }
  close() {
    this.open = false
    this.interrupt()
    try { this.ws?.close() } catch { /* ignore */ }
    this.node?.disconnect()
    this.stream?.getTracks().forEach((t) => t.stop())
    this.ctx?.close().catch(() => {})
    this.ws = null; this.ctx = null; this.stream = null
  }
}
