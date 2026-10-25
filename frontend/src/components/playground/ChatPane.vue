<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { RotateCcw, X, Brain, ChevronRight, AlertTriangle, User, Square, Loader2, MessagesSquare, Code2, Image as ImageIcon, ImageOff, Lightbulb, Play, Scissors } from 'lucide-vue-next'
import BrandMark from '../BrandMark.vue'
import type { Pane, PgModel, Turn } from '../../playground'
import { fmtCost, fmtInt, fmtMs } from '../../format'
import MarkdownView from './MarkdownView.vue'
import ModelPicker from './ModelPicker.vue'
import CopyButton from '../CopyButton.vue'

const props = defineProps<{ pane: Pane; models: PgModel[]; compare?: boolean; removable?: boolean; index?: number; maxCap?: number; defaultMax?: number }>()
const emit = defineEmits<{ model: [v: string]; regenerate: []; remove: []; stop: []; suggest: [text: string]; continue: [t: Turn]; retry: [t: Turn] }>()
const isTrunc = (t: Turn) => !!t.metrics && (t.metrics.truncated || t.metrics.finish_reason === 'length' || t.metrics.finish_reason === 'max_tokens')
const usedMax = (t: Turn) => t.metrics?.max_tokens || 0
const canRaise = (t: Turn) => !props.maxCap || usedMax(t) < props.maxCap
/** must match PlaygroundView.retryMore: 2× the used budget, but at least the model default for empty replies */
const nextMax = (t: Turn) => Math.min(props.maxCap || Infinity, Math.max(usedMax(t) * 2, t.content ? 0 : props.defaultMax || 0))

const scroller = ref<HTMLElement | null>(null)
const busy = computed(() => !!props.pane.controller)
const lastAssistant = computed(() => [...props.pane.turns].reverse().find((t) => t.role === 'assistant'))
const lastMetrics = computed(() => lastAssistant.value?.metrics ?? null)
const isLast = (t: Turn) => props.pane.turns[props.pane.turns.length - 1] === t || props.pane.turns[props.pane.turns.length - 1]?.id === t.id
const openReasoning = ref<Record<number, boolean>>({})

let stick = true
function onScroll() {
  const el = scroller.value
  if (el) stick = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}
const sig = computed(() => props.pane.turns.map((t) => t.content.length + (t.reasoning?.length ?? 0) + (t.state ?? '')).join('|'))
watch(sig, () => nextTick(() => { const el = scroller.value; if (el && stick) el.scrollTop = el.scrollHeight }))
watch(() => props.pane.turns.length, (n, o) => { if (n > (o ?? 0)) stick = true })

const suggestions = [
  { icon: Lightbulb, text: 'Explain the difference between TCP and UDP in a short table.' },
  { icon: Code2, text: 'Write a Python function that retries an HTTP request with exponential backoff.' },
  { icon: MessagesSquare, text: 'Summarize the pros and cons of using an LLM gateway in 5 bullets.' },
  { icon: ImageIcon, text: 'Describe this image in detail.' },
]
const tps = (t: Turn) => t.metrics?.tokens_per_sec
const statusLabel = (t: Turn) => (t.state === 'stopped' ? 'Stopped' : t.metrics ? String(t.metrics.status) : t.state === 'error' ? 'Error' : '')
const providerLine = (t: Turn) => {
  const m = t.metrics
  if (!m) return ''
  const res = m.resolved_model && m.resolved_model !== m.model_group ? m.model_group + ' → ' + m.resolved_model : (m.resolved_model || m.model_group || '')
  return [res, m.provider].filter(Boolean).join(' · ')
}
</script>

<template>
  <section class="pane card" :class="{ compare }">
    <header v-if="compare" class="pane-h">
      <span class="idx">{{ (index ?? 0) + 1 }}</span>
      <ModelPicker :model-value="pane.model" :models="models" compact class="pk" @update:model-value="emit('model', $event)" />
      <button v-if="removable" class="btn btn-ghost btn-icon btn-sm" title="Remove column" aria-label="Remove column" :disabled="busy" @click="emit('remove')"><X /></button>
    </header>
    <div v-if="compare" class="pane-stats">
      <template v-if="lastMetrics">
        <span :class="lastMetrics.ok ? 'badge badge-success' : 'badge badge-danger'"><span class="dot" />{{ lastMetrics.status }}</span>
        <span class="st"><b>{{ fmtMs(lastMetrics.ttft_ms) }}</b> TTFT</span>
        <span class="st"><b>{{ fmtMs(lastMetrics.latency_ms) }}</b> total</span>
        <span class="st"><b>{{ lastMetrics.tokens_per_sec ?? '—' }}</b> tok/s</span>
        <span class="st"><b>{{ fmtCost(lastMetrics.cost) }}</b></span>
      </template>
      <span v-else-if="busy" class="muted"><Loader2 :size="14" class="spin" /> waiting for first token…</span>
      <span v-else class="muted">No response yet</span>
    </div>

    <div ref="scroller" class="msgs" @scroll="onScroll">
      <div v-if="!pane.turns.length" class="empty">
        <template v-if="!compare">
          <div class="hero-ic"><BrandMark :size="26" /></div>
          <h4>Test any model on your gateway</h4>
          <p>Requests go through LiteLLM with a virtual key, so they are logged, budgeted and rate-limited like real traffic (tagged <span class="mono">source:playground</span>).</p>
          <div class="sugg">
            <button v-for="s in suggestions" :key="s.text" class="sg" @click="emit('suggest', s.text)"><component :is="s.icon" :size="15" /><span>{{ s.text }}</span></button>
          </div>
        </template>
        <p v-else class="muted small">Responses from <span class="mono">{{ pane.model }}</span> appear here.</p>
      </div>

      <div v-for="t in pane.turns" :key="t.id" class="msg" :class="t.role">
        <div class="av" :class="t.role"><User v-if="t.role === 'user'" :size="14" :stroke-width="1.75" /><BrandMark v-else :size="15" /></div>
        <div class="bubble-wrap">
          <div v-if="t.role === 'user'" class="bubble">
            <div v-if="t.images?.length" class="imgs"><img v-for="(src, i) in t.images" :key="i" :src="src" alt="attachment" /></div>
            <div v-if="t.content" class="utext">{{ t.content }}</div>
            <div v-if="t.imagesStripped" class="strip-note"><ImageOff :size="12" /> Image not sent — <span class="mono">{{ pane.model }}</span> can't see images; the model was told so.</div>
          </div>
          <template v-else>
            <div class="who"><span class="mono">{{ t.model }}</span><span v-if="t.metrics?.resolved_model && t.metrics.resolved_model !== t.model" class="muted"> → {{ t.metrics.resolved_model }}</span></div>
            <div v-if="t.reasoning" class="reasoning" :class="{ open: openReasoning[t.id] ?? (t.state === 'streaming' && !t.content) }">
              <button class="r-h" @click="openReasoning[t.id] = !(openReasoning[t.id] ?? (t.state === 'streaming' && !t.content))">
                <ChevronRight :size="14" class="chev" /><Brain :size="14" />
                <span>{{ t.state === 'streaming' && !t.content ? 'Thinking…' : 'Reasoning' }}</span>
                <span class="muted">{{ fmtInt(t.reasoning.length) }} chars<template v-if="t.metrics?.reasoning_tokens"> · {{ fmtInt(t.metrics.reasoning_tokens) }} tokens</template></span>
              </button>
              <div class="r-body">{{ t.reasoning }}</div>
            </div>
            <div v-if="t.state === 'pending' || (t.state === 'streaming' && !t.content && !t.reasoning)" class="typing"><span /><span /><span /></div>
            <MarkdownView v-if="t.content" :source="t.content" :streaming="t.state === 'streaming'" />
            <div v-else-if="t.state === 'done' && !t.error && !isTrunc(t)" class="muted small empty-reply">(empty reply)</div>
            <div v-if="t.state === 'done' && !t.error && isTrunc(t)" class="trunc" :class="{ 'no-content': !t.content }">
              <Scissors :size="16" class="tr-ic" />
              <div class="tr-txt">
                <b>{{ t.content ? 'Reply cut off at the token limit' : 'Empty reply — the token budget ran out while reasoning' }}</b>
                <span v-if="t.content">The model stopped after max_tokens = {{ fmtInt(usedMax(t)) }} (finish_reason: {{ t.metrics?.finish_reason }}).</span>
                <span v-else>All {{ fmtInt(t.metrics?.tokens_out) }} output tokens<template v-if="t.metrics?.reasoning_tokens"> ({{ fmtInt(t.metrics.reasoning_tokens) }} reasoning)</template> were used for thinking, max_tokens = {{ fmtInt(usedMax(t)) }}.</span>
              </div>
              <div v-if="isLast(t) && !busy" class="tr-acts">
                <template v-if="t.content">
                  <button class="btn btn-sm" title="Ask the model to continue where it stopped (appends to this reply)" @click="emit('continue', t)"><Play /> Continue</button>
                  <button class="btn btn-sm btn-primary" :disabled="!canRaise(t)" @click="emit('retry', t)"><RotateCcw /> Retry with 2× max tokens<span class="tr-n">{{ fmtInt(nextMax(t)) }}</span></button>
                </template>
                <button v-else class="btn btn-sm btn-primary" :disabled="!canRaise(t)" @click="emit('retry', t)"><RotateCcw /> Retry with more tokens<span class="tr-n">{{ fmtInt(nextMax(t)) }}</span></button>
              </div>
            </div>
            <div v-if="t.error" class="err"><AlertTriangle :size="16" /><div><b>Request failed</b><div class="err-msg">{{ t.error }}</div></div></div>
            <div v-if="t.state === 'stopped'" class="muted small stopped"><Square :size="12" /> Stopped by user after {{ fmtMs(t.elapsedMs) }}</div>

            <div v-if="t.metrics || t.state === 'done' || t.state === 'error' || t.state === 'stopped'" class="meta">
              <span v-if="statusLabel(t)" :class="t.metrics?.ok && t.state !== 'stopped' ? 'badge badge-success' : t.state === 'stopped' ? 'badge badge-warning' : 'badge badge-danger'"><span class="dot" />{{ statusLabel(t) }}</span>
              <template v-if="t.metrics">
                <span class="m" title="Time to first token"><i>TTFT</i>{{ fmtMs(t.metrics.ttft_ms) }}</span>
                <span class="m" title="Total latency (server side)"><i>Latency</i>{{ fmtMs(t.metrics.latency_ms) }}</span>
                <span class="m" title="Prompt / completion tokens"><i>Tokens</i>{{ fmtInt(t.metrics.tokens_in) }} → {{ fmtInt(t.metrics.tokens_out) }}<template v-if="t.metrics.max_tokens"> / {{ fmtInt(t.metrics.max_tokens) }}</template></span>
                <span v-if="t.metrics.reasoning_tokens" class="m" title="Completion tokens spent on reasoning"><i>Reasoning</i>{{ fmtInt(t.metrics.reasoning_tokens) }}<template v-if="t.metrics.reasoning_effort"> · {{ t.metrics.reasoning_effort }}</template></span>
                <span v-else-if="t.metrics.reasoning_effort" class="m"><i>Reasoning</i>{{ t.metrics.reasoning_effort }}</span>
                <span v-if="t.continued" class="m" title="Continue requests merged into this reply (metrics are for the last part)"><i>Continued</i>×{{ t.continued }}</span>
                <span v-if="tps(t)" class="m" title="Output tokens per second (after first token)"><i>Speed</i>{{ tps(t) }} tok/s</span>
                <span class="m" :title="t.metrics.cost_source === 'litellm' ? 'Response cost reported by LiteLLM' : 'Estimated from per-model pricing'"><i>Cost</i>{{ fmtCost(t.metrics.cost) }}</span>
                <span class="m wide" :title="t.metrics.upstream_model || ''"><i>Route</i>{{ providerLine(t) }}</span>
                <span class="m"><i>Via</i>{{ t.metrics.api_format === 'anthropic' ? '/v1/messages' : '/v1/chat/completions' }} · {{ t.metrics.key_name }}</span>
              </template>
              <span class="spacer" />
              <span class="acts">
                <CopyButton v-if="t.content" :text="t.content" />
                <button v-if="isLast(t) && !busy" class="btn btn-sm btn-icon" title="Regenerate" aria-label="Regenerate" @click="emit('regenerate')"><RotateCcw /></button>
              </span>
            </div>
          </template>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.pane { display: flex; flex-direction: column; min-height: 0; min-width: 0; overflow: hidden; }
.pane:not(.compare) { border: 0; background: transparent; box-shadow: none; }
.pane-h { display: flex; align-items: center; gap: 8px; padding: 10px 10px 8px 12px; border-bottom: 1px solid var(--border); }
.idx { width: 20px; height: 20px; border-radius: 3px; border: 1px solid var(--border-strong); color: var(--text-2); display: grid; place-items: center; font: 500 11px var(--font); flex-shrink: 0; }
.pk { flex: 1; }
.pane-stats { display: flex; align-items: center; gap: 12px; padding: 8px 14px; border-bottom: 1px solid var(--border); background: var(--bg); font-size: 12px; color: var(--text-2); flex-wrap: wrap; min-height: 40px; }
.pane-stats .st b { color: var(--text); font: 500 12px var(--font); font-variant-numeric: tabular-nums; }
.pane-stats .muted { display: inline-flex; align-items: center; gap: 6px; }
.msgs { flex: 1; overflow-y: auto; padding: 18px 18px 8px; display: flex; flex-direction: column; gap: 18px; min-height: 0; }
.compare .msgs { padding: 14px 14px 8px; }
.empty { margin: auto; text-align: center; max-width: 620px; padding: 20px 8px; }
.hero-ic { margin: 0 auto 12px; display: flex; justify-content: center; }
.empty h4 { font-size: 18px; font-weight: 600; letter-spacing: -.02em; line-height: 1.3; }
.empty p { color: var(--text-2); font-size: 13px; margin: 6px auto 0; }
.small { font-size: 12.5px; }
.sugg { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 20px; text-align: left; }
.sg { display: flex; gap: 10px; align-items: flex-start; padding: 10px 12px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--bg-elev); color: var(--text-2); font: 13px var(--font); cursor: pointer; text-align: left; transition: border-color .12s var(--ease), color .12s var(--ease); }
.sg:hover { border-color: var(--border-strong); color: var(--text); }
.sg svg { color: var(--text-3); flex-shrink: 0; margin-top: 2px; }
.msg { display: flex; gap: 12px; align-items: flex-start; }
.msg.user { flex-direction: row-reverse; }
.av { width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center; flex-shrink: 0; margin-top: 1px; }
.av.user { background: var(--ink); color: var(--on-ink); }
.av.assistant { background: var(--bg-elev); border: 1px solid var(--border-strong); }
.bubble-wrap { min-width: 0; flex: 1; display: flex; flex-direction: column; }
.msg.user .bubble-wrap { align-items: flex-end; }
.bubble { background: var(--bg-subtle); border: 1px solid var(--border); padding: 8px 12px; border-radius: var(--radius); max-width: min(720px, 92%); }
.utext { white-space: pre-wrap; word-wrap: break-word; overflow-wrap: anywhere; font-size: 14px; }
.imgs { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 6px; }
.imgs img { max-height: 140px; max-width: 220px; border-radius: var(--radius-sm); border: 1px solid var(--border); object-fit: cover; }
.who { font: 500 11.5px var(--font); color: var(--text-3); margin: 5px 0 6px; }
.reasoning { border: 1px solid var(--border); border-radius: var(--radius-sm); margin-bottom: 10px; background: var(--bg-subtle); overflow: hidden; }
.r-h { display: flex; align-items: center; gap: 7px; width: 100%; border: 0; background: transparent; color: var(--text-2); font: 500 12.5px var(--font); padding: 7px 10px; cursor: pointer; text-align: left; }
.r-h:hover { color: var(--text); }
.r-h .muted { margin-left: auto; font-size: 11.5px; }
.chev { transition: transform .15s; }
.reasoning.open .chev { transform: rotate(90deg); }
.r-body { display: none; padding: 4px 12px 10px 32px; font-size: 12.5px; color: var(--text-3); white-space: pre-wrap; max-height: 260px; overflow-y: auto; line-height: 1.55; }
.reasoning.open .r-body { display: block; }
.typing { display: inline-flex; gap: 4px; padding: 8px 0; }
.typing span { width: 5px; height: 5px; border-radius: 50%; background: var(--text-3); animation: bounce 1.2s infinite ease-in-out; }
.typing span:nth-child(2) { animation-delay: .15s; } .typing span:nth-child(3) { animation-delay: .3s; }
@keyframes bounce { 0%, 80%, 100% { opacity: .3; transform: translateY(0); } 40% { opacity: 1; transform: translateY(-3px); } }
.err { display: flex; gap: 10px; align-items: flex-start; background: var(--danger-soft); color: var(--danger); border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent); padding: 10px 12px; border-radius: var(--radius-sm); font-size: 13px; margin-top: 4px; }
.err svg { flex-shrink: 0; margin-top: 2px; }
.err-msg { color: var(--text); opacity: .85; margin-top: 2px; word-break: break-word; font-family: var(--font); font-size: 12px; white-space: pre-wrap; }
.stopped { display: inline-flex; gap: 6px; align-items: center; margin-top: 6px; }
.empty-reply { margin-top: 2px; }
.strip-note { display: flex; align-items: center; gap: 5px; margin-top: 6px; font-size: 11.5px; color: var(--text-2); }
.trunc { display: flex; flex-wrap: wrap; gap: 8px 10px; align-items: flex-start; margin-top: 8px; padding: 9px 12px; border-radius: var(--radius-sm); font-size: 12.5px;
  background: var(--warning-soft); border: 1px solid color-mix(in srgb, var(--warning) 40%, transparent); }
.tr-ic { color: var(--warning); flex-shrink: 0; margin-top: 2px; }
.tr-txt { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 200px; }
.tr-txt span { color: var(--text-2); }
.tr-acts { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.tr-n { margin-left: 6px; opacity: .75; font-variant-numeric: tabular-nums; font-size: 11px; }
.meta { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 14px; margin-top: 10px; padding-top: 8px; border-top: 1px dashed var(--border); font: 12px var(--font); color: var(--text); font-variant-numeric: tabular-nums; }
.m i { font-style: normal; color: var(--text-3); margin-right: 5px; font: 400 12px var(--font); }
.m.wide { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.acts { display: inline-flex; gap: 6px; }
.compare .meta { gap: 4px 10px; }
@media (max-width: 700px) { .sugg { grid-template-columns: 1fr; } .msgs { padding: 14px 10px 8px; } }
</style>
