import { auth, logout } from './stores/auth'

export interface PgModel {
  name: string; kind: 'model' | 'alias'; display_name: string; target: string | null; upstream_id: string | null
  provider_slug: string | null; provider_name: string | null; provider_enabled: boolean; enabled: boolean; live: boolean
  vision: boolean; input_price_per_m: number; output_price_per_m: number; context_window: number | null
  /** model metadata (Models page / catalog): thinks before answering */
  reasoning: boolean
  max_output_tokens: number; default_max_tokens: number
  /** reasoning levels the model honours ([] = no control) */
  reasoning_efforts: Effort[]
}
export type Effort = 'off' | 'low' | 'medium' | 'high'
export type EffortParam = 'default' | Effort
export const EFFORT_LABELS: Record<EffortParam, string> = { default: 'Default', off: 'Off', low: 'Low', medium: 'Medium', high: 'High' }
export interface PgKey { id: number; name: string; key_prefix: string; models: string[]; internal: boolean; max_budget: number | null; rpm_limit: number | null }
export interface PgOptions { models: PgModel[]; keys: PgKey[]; default_key_id: number; openai_base_url: string; anthropic_base_url: string; source_tag: string }
export interface PgMetrics {
  request_id: string | null; deployment_id: string | null; model_group: string | null; resolved_model: string | null
  upstream_model: string | null; provider: string | null; provider_slug: string | null; status: number; ok: boolean
  latency_ms: number; ttft_ms: number | null; tokens_in: number; tokens_out: number; reasoning_tokens: number | null
  tokens_per_sec: number | null; cost: number | null; cost_source: 'litellm' | 'pricing' | null; finish_reason: string | null
  api_format: ApiFormat; stream: boolean; key_name: string
  truncated?: boolean; max_tokens?: number | null; reasoning_effort?: Effort | null; images_removed?: number
}
export type ApiFormat = 'openai' | 'anthropic'
export interface PgParams {
  system: string; temperature: number; top_p: number; max_tokens: number; stream: boolean; api_format: ApiFormat; key_id: number | null
  /** false = follow the selected model's default_max_tokens; true = the user typed/slid a value */
  max_tokens_edited: boolean
  reasoning_effort: EffortParam
}
export const FALLBACK_MAX_TOKENS = 8192
export const DEFAULT_PARAMS: PgParams = { system: '', temperature: 0.7, top_p: 1, max_tokens: FALLBACK_MAX_TOKENS, stream: true, api_format: 'openai', key_id: null, max_tokens_edited: false, reasoning_effort: 'default' }

/** Parse a user-typed number; accepts "0,7" and "0.7" (locale-independent). Returns null if not a number. */
export function parseNum(s: string | number | null | undefined, o: { min?: number; max?: number; integer?: boolean } = {}): number | null {
  if (typeof s === 'number') return Number.isFinite(s) ? clampNum(s, o) : null
  const t = String(s ?? '').trim().replace(/\s/g, '').replace(',', '.')
  if (!/^[-+]?(\d+\.?\d*|\.\d+)$/.test(t)) return null
  return clampNum(Number(t), o)
}
function clampNum(v: number, o: { min?: number; max?: number; integer?: boolean }): number {
  if (o.integer) v = Math.round(v)
  if (o.min !== undefined) v = Math.max(o.min, v)
  if (o.max !== undefined) v = Math.min(o.max, v)
  return v
}
/** Sanitise persisted params (older versions / locales may have stored strings like "0,7"). */
export function sanitizeParams(p: Partial<PgParams>): Partial<PgParams> {
  const out: Partial<PgParams> = { ...p }
  const t = parseNum(p.temperature as number | string | undefined, { min: 0, max: 2 }); if (t === null) delete out.temperature; else out.temperature = t
  const tp = parseNum(p.top_p as number | string | undefined, { min: 0, max: 1 }); if (tp === null) delete out.top_p; else out.top_p = tp
  const mt = parseNum(p.max_tokens as number | string | undefined, { min: 1, integer: true }); if (mt === null) delete out.max_tokens; else out.max_tokens = mt
  if (out.max_tokens_edited !== true) out.max_tokens_edited = false
  if (!out.reasoning_effort || !(out.reasoning_effort in EFFORT_LABELS)) out.reasoning_effort = 'default'
  return out
}

export const CONTINUE_PROMPT = 'Your previous reply was cut off by the token limit. Continue exactly where it stopped, without repeating anything or adding a preamble.'

export type TurnState = 'pending' | 'streaming' | 'done' | 'error' | 'stopped'
export interface Turn {
  id: number; role: 'user' | 'assistant'; content: string; images?: string[]; reasoning?: string
  metrics?: PgMetrics | null; error?: string | null; state?: TurnState; model?: string; startedAt?: number; elapsedMs?: number
  /** user turn: images were not sent to this pane's model (no vision) */
  imagesStripped?: boolean
  /** assistant turn: number of "Continue" follow-ups merged into this reply */
  continued?: number
}
/** stripImages: the user chose "Send without image" for this pane's (non-vision) model */
export interface Pane { id: number; model: string; turns: Turn[]; controller: AbortController | null; stripImages?: boolean }

export interface WireMessage { role: 'user' | 'assistant'; content: string; images: string[] }
export interface ChatRequest {
  model: string; messages: WireMessage[]; system?: string; temperature?: number; top_p?: number; max_tokens: number
  stream: boolean; api_format: ApiFormat; key_id?: number | null; compare_id?: string
  reasoning_effort?: EffortParam; strip_images?: boolean
}

export interface ChatHandlers {
  onMeta?: (m: Partial<PgMetrics>) => void
  onDelta: (t: string) => void
  onReasoning: (t: string) => void
  onDone: (m: PgMetrics | null) => void
  onError: (message: string, m: PgMetrics | null) => void
}

let seq = 1
export const uid = () => seq++

/** POST /api/playground/chat and dispatch SSE (or JSON for stream=false) events. Throws AbortError on stop. */
export async function runChat(req: ChatRequest, h: ChatHandlers, signal: AbortSignal): Promise<void> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json', Accept: req.stream ? 'text/event-stream' : 'application/json' }
  if (auth.token) headers.Authorization = 'Bearer ' + auth.token
  const res = await fetch('/api/playground/chat', { method: 'POST', headers, body: JSON.stringify(req), signal })
  if (res.status === 401) { logout(true); throw new Error('Session expired, please sign in again') }
  const ctype = res.headers.get('content-type') || ''
  if (!res.ok) {
    let msg = 'HTTP ' + res.status
    try {
      const j = await res.json()
      msg = typeof j.detail === 'string' ? j.detail : Array.isArray(j.detail) ? j.detail.map((d: { loc?: string[]; msg: string }) => (d.loc ? d.loc.slice(1).join('.') + ': ' : '') + d.msg).join('; ') : msg
    } catch { /* not JSON */ }
    h.onError('HTTP ' + res.status + ': ' + msg.replace(/^HTTP \d+: /, ''), null)
    return
  }
  if (!ctype.includes('text/event-stream')) {
    const j = await res.json()
    if (j.ok) {
      if (j.reasoning) h.onReasoning(j.reasoning)
      if (j.content) h.onDelta(j.content)
      h.onDone(j.metrics)
    } else h.onError(j.error || 'Request failed', j.metrics)
    return
  }
  const reader = res.body!.getReader()
  const dec = new TextDecoder()
  let buf = ''
  let finished = false
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    let i: number
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, i)
      buf = buf.slice(i + 2)
      const data = block.split('\n').filter((l) => l.startsWith('data:')).map((l) => l.slice(5).trimStart()).join('\n')
      if (!data) continue
      let ev: { type: string; text?: string; message?: string; metrics?: PgMetrics | null } & Partial<PgMetrics>
      try { ev = JSON.parse(data) } catch { continue }
      if (ev.type === 'delta') h.onDelta(ev.text || '')
      else if (ev.type === 'reasoning') h.onReasoning(ev.text || '')
      else if (ev.type === 'meta') h.onMeta?.(ev)
      else if (ev.type === 'done') { finished = true; h.onDone(ev.metrics ?? null) }
      else if (ev.type === 'error') { finished = true; h.onError(ev.message || 'Request failed', ev.metrics ?? null) }
    }
  }
  if (!finished) h.onError('The stream ended unexpectedly (connection closed before the response completed)', null)
}

/** Downscale an image file to a JPEG/PNG data URL (keeps requests small; vision models do not need more). */
export async function imageToDataUrl(file: File, max = 1280): Promise<string> {
  if (file.type === 'image/gif' && file.size < 3_000_000) return readAsDataUrl(file)
  const bmp = await createImageBitmap(file)
  const scale = Math.min(1, max / Math.max(bmp.width, bmp.height))
  const w = Math.max(1, Math.round(bmp.width * scale))
  const hgt = Math.max(1, Math.round(bmp.height * scale))
  const canvas = document.createElement('canvas')
  canvas.width = w; canvas.height = hgt
  const ctx = canvas.getContext('2d')!
  ctx.drawImage(bmp, 0, 0, w, hgt)
  bmp.close()
  const png = file.type === 'image/png' && file.size < 400_000 && scale === 1
  return canvas.toDataURL(png ? 'image/png' : 'image/jpeg', 0.86)
}
function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(r.result as string)
    r.onerror = () => reject(r.error)
    r.readAsDataURL(file)
  })
}

// ------------------------------------------------------------------ "View as code"
const IMG_PLACEHOLDER = '<BASE64_IMAGE_DATA>'
function shortImg(url: string): { media: string; data: string; url: string } {
  const m = /^data:([^;]+);base64,/.exec(url)
  const media = m ? m[1] : 'image/jpeg'
  return { media, data: IMG_PLACEHOLDER, url: 'data:' + media + ';base64,' + IMG_PLACEHOLDER }
}

/** The exact JSON body the gateway receives (images shortened to a placeholder). */
export function wirePayload(r: ChatRequest): Record<string, unknown> {
  const msgs = r.messages.filter((m) => m.content.trim() || m.images.length)
    .map((m) => (r.strip_images && m.images.length ? { ...m, images: [], content: (m.content ? m.content + '\n\n' : '') + '[image removed: this model cannot view images]' } : m))
  const p: Record<string, unknown> = { model: r.model }
  if (r.api_format === 'openai') {
    const out: unknown[] = []
    if (r.system?.trim()) out.push({ role: 'system', content: r.system })
    for (const m of msgs) {
      if (m.images.length && m.role === 'user') {
        out.push({ role: m.role, content: [...(m.content ? [{ type: 'text', text: m.content }] : []), ...m.images.map((u) => ({ type: 'image_url', image_url: { url: shortImg(u).url } }))] })
      } else out.push({ role: m.role, content: m.content })
    }
    p.messages = out
  } else {
    if (r.system?.trim()) p.system = r.system
    p.messages = msgs.map((m) => m.images.length && m.role === 'user'
      ? { role: m.role, content: [...m.images.map((u) => { const s = shortImg(u); return { type: 'image', source: { type: 'base64', media_type: s.media, data: s.data } } }), ...(m.content ? [{ type: 'text', text: m.content }] : [])] }
      : { role: m.role, content: m.content })
  }
  p.max_tokens = r.max_tokens
  if (r.temperature !== undefined) p.temperature = r.temperature
  if (r.top_p !== undefined) p.top_p = r.top_p
  if (r.reasoning_effort === 'off') p.reasoning = { enabled: false }
  else if (r.reasoning_effort && r.reasoning_effort !== 'default') { p.reasoning_effort = r.reasoning_effort; p.allowed_openai_params = ['reasoning_effort'] }
  if (r.stream) p.stream = true
  return p
}
const EXTRA_KEYS = ['reasoning', 'reasoning_effort', 'allowed_openai_params']
const pyExtra = (p: Record<string, unknown>) => {
  const e = Object.fromEntries(EXTRA_KEYS.filter((k) => p[k] !== undefined).map((k) => [k, p[k]]))
  return Object.keys(e).length ? '\n    extra_body=' + JSON.stringify(e).replace(/\bfalse\b/g, 'False').replace(/\btrue\b/g, 'True') + ',' : ''
}

const indent = (s: string, n: number) => s.split('\n').map((l, i) => (i ? ' '.repeat(n) + l : l)).join('\n')
const shq = (s: string) => "'" + s.replace(/'/g, "'\\''") + "'"
const pyKw = (p: Record<string, unknown>, keys: string[]) => keys.filter((k) => p[k] !== undefined).map((k) => '    ' + k + '=' + (typeof p[k] === 'boolean' ? (p[k] ? 'True' : 'False') : JSON.stringify(p[k])) + ',').join('\n')
const jsKw = (p: Record<string, unknown>, keys: string[]) => keys.filter((k) => p[k] !== undefined).map((k) => '  ' + k + ': ' + JSON.stringify(p[k]) + ',').join('\n')

export interface CodeSnippet { id: 'curl' | 'python' | 'js'; title: string; lang: string; code: string }

export function buildCode(r: ChatRequest, base: { openai: string; anthropic: string }): CodeSnippet[] {
  const p = wirePayload(r)
  const hasImg = r.messages.some((m) => m.images.length)
  const imgNote = hasImg ? 'Replace ' + IMG_PLACEHOLDER + ' with your base64-encoded image.' : ''
  const msgsPy = indent(JSON.stringify(p.messages, null, 4), 4)
  const msgsJs = indent(JSON.stringify(p.messages, null, 2), 2)
  if (r.api_format === 'openai') {
    const kw = ['temperature', 'top_p', 'max_tokens']
    const jkw = [...kw, ...EXTRA_KEYS]
    return [
      { id: 'curl', title: 'curl', lang: 'bash', code: (imgNote ? '# ' + imgNote + '\n' : '') + 'curl ' + base.openai + '/chat/completions \\\n  -H "Authorization: Bearer $LORA_GATEWAY_API_KEY" \\\n  -H "Content-Type: application/json" \\\n' + (r.stream ? '  -N \\\n' : '') + '  -d ' + shq(JSON.stringify(p, null, 2)) },
      { id: 'python', title: 'Python (openai SDK)', lang: 'python', code:
'import os\nfrom openai import OpenAI\n\nclient = OpenAI(\n    base_url="' + base.openai + '",\n    api_key=os.environ["LORA_GATEWAY_API_KEY"],\n)\n' + (imgNote ? '# ' + imgNote + '\n' : '') +
'resp = client.chat.completions.create(\n    model=' + JSON.stringify(r.model) + ',\n    messages=' + msgsPy + ',\n' + pyKw(p, kw) + pyExtra(p) + (r.stream ? '\n    stream=True,' : '') + '\n)\n' +
(r.stream ? 'for chunk in resp:\n    if chunk.choices and chunk.choices[0].delta.content:\n        print(chunk.choices[0].delta.content, end="", flush=True)\nprint()' : 'print(resp.choices[0].message.content)\nprint(resp.usage)') },
      { id: 'js', title: 'JavaScript (openai SDK)', lang: 'js', code:
"import OpenAI from 'openai'\n\nconst client = new OpenAI({\n  baseURL: '" + base.openai + "',\n  apiKey: process.env.LORA_GATEWAY_API_KEY,\n})\n" + (imgNote ? '// ' + imgNote + '\n' : '') +
'const resp = await client.chat.completions.create({\n  model: ' + JSON.stringify(r.model) + ',\n  messages: ' + msgsJs + ',\n' + jsKw(p, jkw) + (r.stream ? '\n  stream: true,' : '') + '\n})\n' +
(r.stream ? "for await (const chunk of resp) process.stdout.write(chunk.choices[0]?.delta?.content ?? '')" : 'console.log(resp.choices[0].message.content)') },
    ]
  }
  const kw = ['max_tokens', 'temperature', 'top_p']
  for (const k of EXTRA_KEYS) delete p[k] // reasoning controls are only sent on the OpenAI path
  const sys = p.system !== undefined ? '    system=' + JSON.stringify(p.system) + ',\n' : ''
  const sysJs = p.system !== undefined ? '  system: ' + JSON.stringify(p.system) + ',\n' : ''
  return [
    { id: 'curl', title: 'curl', lang: 'bash', code: (imgNote ? '# ' + imgNote + '\n' : '') + 'curl ' + base.anthropic + '/v1/messages \\\n  -H "x-api-key: $LORA_GATEWAY_API_KEY" \\\n  -H "anthropic-version: 2023-06-01" \\\n  -H "Content-Type: application/json" \\\n' + (r.stream ? '  -N \\\n' : '') + '  -d ' + shq(JSON.stringify(p, null, 2)) },
    { id: 'python', title: 'Python (anthropic SDK)', lang: 'python', code:
'import os\nimport anthropic\n\nclient = anthropic.Anthropic(\n    base_url="' + base.anthropic + '",\n    api_key=os.environ["LORA_GATEWAY_API_KEY"],\n)\n' + (imgNote ? '# ' + imgNote + '\n' : '') +
(r.stream
  ? 'with client.messages.stream(\n    model=' + JSON.stringify(r.model) + ',\n' + sys + '    messages=' + msgsPy + ',\n' + pyKw(p, kw) + '\n) as stream:\n    for text in stream.text_stream:\n        print(text, end="", flush=True)\nprint()'
  : 'msg = client.messages.create(\n    model=' + JSON.stringify(r.model) + ',\n' + sys + '    messages=' + msgsPy + ',\n' + pyKw(p, kw) + '\n)\nprint("".join(b.text for b in msg.content if b.type == "text"))\nprint(msg.usage)') },
    { id: 'js', title: 'JavaScript (anthropic SDK)', lang: 'js', code:
"import Anthropic from '@anthropic-ai/sdk'\n\nconst client = new Anthropic({\n  baseURL: '" + base.anthropic + "',\n  apiKey: process.env.LORA_GATEWAY_API_KEY,\n})\n" + (imgNote ? '// ' + imgNote + '\n' : '') +
(r.stream
  ? 'const stream = client.messages.stream({\n  model: ' + JSON.stringify(r.model) + ',\n' + sysJs + '  messages: ' + msgsJs + ',\n' + jsKw(p, kw) + "\n})\nstream.on('text', (t) => process.stdout.write(t))\nawait stream.finalMessage()"
  : 'const msg = await client.messages.create({\n  model: ' + JSON.stringify(r.model) + ',\n' + sysJs + '  messages: ' + msgsJs + ',\n' + jsKw(p, kw) + "\n})\nconsole.log(msg.content.filter((b) => b.type === 'text').map((b) => b.text).join(''))") },
  ]
}
