<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { RefreshCw } from 'lucide-vue-next'
import type { EChartsOption } from 'echarts'
import { api, qs } from '../api'
import type { BreakdownRow, Point, Summary } from '../types'
import { delta, fmtCompact, fmtCost, fmtInt, fmtMs, fmtPct } from '../format'
import { fail } from '../stores/toast'
import { theme } from '../stores/theme'
import { chartTokens } from '../chartTheme'
import StatCard from '../components/StatCard.vue'
import EChart from '../components/EChart.vue'
import EmptyState from '../components/EmptyState.vue'

const ranges = [
  { label: '24h', hours: 24 },
  { label: '7d', hours: 168 },
  { label: '30d', hours: 720 },
  { label: '90d', hours: 2160 },
]
const hours = ref(Number(localStorage.getItem('gw-range') || 168))
watch(hours, (h) => localStorage.setItem('gw-range', String(h)))
const source = ref(localStorage.getItem('gw-source') || '')
watch(source, (s) => localStorage.setItem('gw-source', s))
const summary = ref<Summary | null>(null)
const points = ref<Point[]>([])
const byModel = ref<BreakdownRow[]>([])
const byProvider = ref<BreakdownRow[]>([])
const byKey = ref<BreakdownRow[]>([])
const bySource = ref<BreakdownRow[]>([])
const sourceLabel: Record<string, string> = { playground: 'Playground', test: 'Model tests', api: 'API clients' }
const loading = ref(true)
let timer: number | undefined

async function load() {
  loading.value = true
  try {
    const q = qs({ hours: hours.value, source: source.value })
    const [s, ts, m, p, k, src] = await Promise.all([
      api.get<Summary>('/api/analytics/summary' + q),
      api.get<{ points: Point[] }>('/api/analytics/timeseries' + q),
      api.get<BreakdownRow[]>('/api/analytics/breakdown' + qs({ hours: hours.value, by: 'model', source: source.value })),
      api.get<BreakdownRow[]>('/api/analytics/breakdown' + qs({ hours: hours.value, by: 'provider', source: source.value })),
      api.get<BreakdownRow[]>('/api/analytics/breakdown' + qs({ hours: hours.value, by: 'key', source: source.value })),
      api.get<BreakdownRow[]>('/api/analytics/breakdown' + qs({ hours: hours.value, by: 'source', source: source.value })),
    ])
    summary.value = s
    points.value = ts.points
    byModel.value = m
    byProvider.value = p
    byKey.value = k
    bySource.value = src
  } catch (e) {
    fail('Could not load analytics', e)
  } finally {
    loading.value = false
  }
}
onMounted(() => { load(); timer = window.setInterval(load, 30000) })
onBeforeUnmount(() => clearInterval(timer))
watch([hours, source], load)

const tk = computed(() => chartTokens(theme.value))
const palette = computed(() => tk.value.palette)
const axisColor = computed(() => tk.value.axis)
const gridColor = computed(() => tk.value.grid)
const label = (t: string) => {
  const d = new Date(t)
  return hours.value <= 72 ? d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) + (hours.value > 24 ? ' ' + d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }) : '') : d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })
}
const baseAxis = () => ({
  grid: { left: 8, right: 12, top: 36, bottom: 6, containLabel: true },
  tooltip: { trigger: 'axis' as const },
  legend: { top: 0, right: 0, icon: 'rect', itemWidth: 10, itemHeight: 3 },
  xAxis: { type: 'category' as const, data: points.value.map((p) => label(p.t)), axisLine: { lineStyle: { color: tk.value.border } }, axisTick: { show: false }, axisLabel: { color: axisColor.value, fontSize: 10.5 } },
})
const sparse = computed(() => points.value.filter((p) => p.requests > 0).length < 4)
const yAxis = (fmt: (v: number) => string) => ({ type: 'value' as const, splitNumber: 4, splitLine: { lineStyle: { color: gridColor.value } }, axisLabel: { color: axisColor.value, fontSize: 10.5, formatter: fmt } })

const reqOption = computed<EChartsOption>(() => ({
  ...baseAxis(),
  color: [tk.value.ink, tk.value.danger],
  yAxis: yAxis((v) => fmtCompact(v)),
  series: [
    { name: 'Requests', type: 'bar', stack: 'r', barMaxWidth: 14, data: points.value.map((p) => p.requests - p.errors) },
    { name: 'Errors', type: 'bar', stack: 'r', barMaxWidth: 14, data: points.value.map((p) => p.errors) },
  ],
}))
const costOption = computed<EChartsOption>(() => ({
  ...baseAxis(),
  color: [tk.value.accent],
  yAxis: yAxis((v) => '$' + (v < 1 ? v.toFixed(3) : v.toFixed(2))),
  tooltip: { ...baseAxis().tooltip, valueFormatter: (v) => fmtCost(v as number) },
  series: [{ name: 'Cost', type: 'line', showSymbol: sparse.value, symbolSize: 5, lineStyle: { width: 1.5 }, data: points.value.map((p) => +p.cost.toFixed(6)) }],
}))
const latOption = computed<EChartsOption>(() => ({
  ...baseAxis(),
  color: [tk.value.ink, tk.value.grey, tk.value.accent],
  yAxis: yAxis((v) => fmtMs(v)),
  tooltip: { ...baseAxis().tooltip, valueFormatter: (v) => fmtMs(v as number) },
  series: [
    { name: 'p50', type: 'line', showSymbol: sparse.value, symbolSize: 5, lineStyle: { width: 1.5 }, connectNulls: true, data: points.value.map((p) => p.latency_p50) },
    { name: 'p95', type: 'line', showSymbol: sparse.value, symbolSize: 5, connectNulls: true, lineStyle: { width: 1.5, type: [4, 3] }, data: points.value.map((p) => p.latency_p95) },
    { name: 'TTFT p50', type: 'line', showSymbol: sparse.value, symbolSize: 5, lineStyle: { width: 1.5 }, connectNulls: true, data: points.value.map((p) => p.ttft_p50) },
  ],
}))
const tokOption = computed<EChartsOption>(() => ({
  ...baseAxis(),
  color: [tk.value.ink, tk.value.light],
  yAxis: yAxis((v) => fmtCompact(v)),
  series: [
    { name: 'Input', type: 'bar', stack: 't', barMaxWidth: 14, data: points.value.map((p) => p.tokens_in) },
    { name: 'Output', type: 'bar', stack: 't', barMaxWidth: 14, data: points.value.map((p) => p.tokens_out) },
  ],
}))
const donut = computed<EChartsOption>(() => ({
  color: palette.value,
  tooltip: { trigger: 'item', valueFormatter: (v) => fmtCost(v as number) },
  series: [{
    type: 'pie', radius: ['62%', '80%'], center: ['50%', '50%'], avoidLabelOverlap: true, itemStyle: { borderColor: tk.value.surface, borderWidth: 2 },
    label: { show: false },
    data: byModel.value.map((m, i) => ({ name: m.name, value: +m.cost.toFixed(6), itemStyle: { color: palette.value[i % palette.value.length] } })).filter((d) => d.value > 0),
  }],
}))
const maxReq = computed(() => Math.max(1, ...byModel.value.map((m) => m.requests)))
const hasData = computed(() => (summary.value?.requests ?? 0) > 0)
const rangeLabel = computed(() => ranges.find((r) => r.hours === hours.value)?.label ?? '')
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1>Dashboard</h1>
        <p>Traffic, spend and performance across all providers · last {{ rangeLabel }}<template v-if="source"> · {{ sourceLabel[source] }} only</template></p>
      </div>
      <div class="toolbar">
        <select v-model="source" class="input source-sel" title="Traffic source">
          <option value="">All traffic</option><option value="api">API clients</option><option value="playground">Playground</option><option value="test">Model tests</option>
        </select>
        <div class="segmented">
          <button v-for="r in ranges" :key="r.hours" :class="{ active: hours === r.hours }" :aria-pressed="hours === r.hours" @click="hours = r.hours">{{ r.label }}</button>
        </div>
        <button class="btn btn-icon" @click="load" title="Refresh" aria-label="Refresh"><RefreshCw :class="{ spin: loading }" /></button>
      </div>
    </div>

    <div class="stats">
      <StatCard label="Requests" :value="fmtInt(summary?.requests)" :delta="delta(summary?.requests, summary?.previous.requests)" hint="vs prev. period" :loading="loading && !summary" />
      <StatCard label="Total cost" :value="fmtCost(summary?.cost)" :delta="delta(summary?.cost, summary?.previous.cost)" invert hint="vs prev. period" :loading="loading && !summary" />
      <StatCard label="Tokens" :value="fmtCompact((summary?.tokens_in ?? 0) + (summary?.tokens_out ?? 0))" :hint="`${fmtCompact(summary?.tokens_in)} in · ${fmtCompact(summary?.tokens_out)} out`" :loading="loading && !summary" />
      <StatCard label="Avg latency" :value="fmtMs(summary?.latency_avg)" :hint="`p50 ${fmtMs(summary?.latency_p50)} · p95 ${fmtMs(summary?.latency_p95)}`" :loading="loading && !summary" />
      <StatCard label="Time to first token" :value="fmtMs(summary?.ttft_p50)" hint="p50, streaming requests" :loading="loading && !summary" />
      <StatCard label="Error rate" :value="fmtPct(summary?.error_rate)" :hint="`${fmtInt(summary?.errors)} failed requests`" :loading="loading && !summary" />
    </div>

    <div v-if="!loading && !hasData" class="card" style="margin-top: 18px">
      <EmptyState title="No traffic yet" description="Send your first request through the gateway and analytics will appear here within a few seconds.">
        <RouterLink to="/connect" class="btn btn-primary">Connect a client</RouterLink>
        <RouterLink to="/playground" class="btn">Open Playground</RouterLink>
      </EmptyState>
    </div>

    <template v-else>
      <div class="charts">
        <div class="card"><div class="card-header"><div><h3>Requests</h3><div class="sub">Successful vs failed</div></div></div><div class="card-body"><EChart :option="reqOption" /></div></div>
        <div class="card"><div class="card-header"><div><h3>Spend</h3><div class="sub">USD, from per-model pricing</div></div><strong class="mono total">{{ fmtCost(summary?.cost) }}</strong></div><div class="card-body"><EChart :option="costOption" /></div></div>
        <div class="card"><div class="card-header"><div><h3>Latency</h3><div class="sub">End-to-end p50 / p95 and time-to-first-token</div></div></div><div class="card-body"><EChart :option="latOption" /></div></div>
        <div class="card"><div class="card-header"><div><h3>Tokens</h3><div class="sub">Input vs output</div></div></div><div class="card-body"><EChart :option="tokOption" /></div></div>
      </div>

      <div class="bottom">
        <div class="card">
          <div class="card-header"><div><h3>Top models</h3><div class="sub">By request volume</div></div><RouterLink to="/logs" class="btn btn-sm">View logs</RouterLink></div>
          <div class="table-wrap">
            <table class="table">
              <thead><tr><th>Model</th><th>Requests</th><th class="num">Tokens</th><th class="num">Cost</th><th class="num">p50</th><th class="num">p95</th><th class="num">Errors</th></tr></thead>
              <tbody>
                <tr v-for="(m, i) in byModel" :key="m.name">
                  <td><span class="swatch" :style="{ background: palette[i % palette.length] }" /><span class="mono">{{ m.name }}</span></td>
                  <td style="min-width: 140px"><div class="bar-cell"><div class="bar" :style="{ width: (m.requests / maxReq) * 100 + '%' }" /><span class="mono n">{{ fmtInt(m.requests) }}</span></div></td>
                  <td class="num">{{ fmtCompact(m.tokens_in + m.tokens_out) }}</td>
                  <td class="num">{{ fmtCost(m.cost) }}</td>
                  <td class="num">{{ fmtMs(m.latency_p50) }}</td>
                  <td class="num">{{ fmtMs(m.latency_p95) }}</td>
                  <td class="num"><span :class="m.errors ? 'errc' : 'muted'">{{ m.errors ? fmtPct(m.error_rate) : '0' }}</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div class="side">
          <div class="card">
            <div class="card-header"><h3>Cost by model</h3></div>
            <div class="card-body donut"><EChart :option="donut" height="200px" /></div>
          </div>
          <div class="card">
            <div class="card-header"><h3>By provider</h3></div>
            <div class="list">
              <div v-for="p in byProvider" :key="p.name" class="li"><span class="pname">{{ p.name }}</span><span class="spacer" /><span class="muted mono n">{{ fmtInt(p.requests) }} req</span><span class="mono n cost">{{ fmtCost(p.cost) }}</span></div>
            </div>
          </div>
          <div class="card">
            <div class="card-header"><h3>By source</h3></div>
            <div class="list">
              <div v-for="s in bySource" :key="s.name" class="li"><span class="pname">{{ sourceLabel[s.name] || s.name }}</span><span class="spacer" /><span class="muted mono n">{{ fmtInt(s.requests) }} req</span><span class="mono n cost">{{ fmtCost(s.cost) }}</span></div>
            </div>
          </div>
          <div class="card">
            <div class="card-header"><h3>By API key</h3></div>
            <div class="list">
              <div v-for="k in byKey" :key="k.name" class="li"><span class="mono">{{ k.name }}</span><span class="spacer" /><span class="muted mono n">{{ fmtInt(k.requests) }} req</span><span class="mono n cost">{{ fmtCost(k.cost) }}</span></div>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.stats { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 0; border: 1px solid var(--border); border-radius: var(--radius); background: var(--bg-elev); overflow: hidden; }
.stats > :deep(.stat) { border: 0; border-radius: 0; background: transparent; }
.stats > :deep(.stat + .stat) { border-left: 1px solid var(--border); }
.charts { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 16px; }
.charts .card-body { padding: 8px 14px 12px; }
.total { font-size: 14px; font-weight: 500; }
.bottom { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 16px; margin-top: 16px; align-items: start; }
.side { display: flex; flex-direction: column; gap: 16px; }
.swatch { display: inline-block; width: 8px; height: 8px; border-radius: 1px; margin-right: 9px; vertical-align: middle; }
.bar-cell { display: flex; align-items: center; gap: 10px; }
.bar { height: 4px; border-radius: 0; background: var(--text-3); opacity: .55; min-width: 2px; max-width: 90px; flex-shrink: 0; }
.n { font-size: 12px; font-variant-numeric: tabular-nums; }
.errc { color: var(--danger); }
.list { padding: 2px 0; }
.li { display: flex; align-items: center; gap: 12px; padding: 8px 16px; font-size: 13px; }
.li + .li { border-top: 1px solid var(--border); }
.li .cost { min-width: 64px; text-align: right; color: var(--text); }
.pname { font-weight: 500; }
.donut { padding: 6px; }
.source-sel { width: auto; height: 32px; }
@media (max-width: 1400px) {
  .stats { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .stats > :deep(.stat:nth-child(3n + 1)) { border-left: 0; }
  .stats > :deep(.stat:nth-child(n + 4)) { border-top: 1px solid var(--border); }
}
@media (max-width: 1100px) { .charts, .bottom { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 640px) {
  .stats { grid-template-columns: 1fr 1fr; }
  .stats > :deep(.stat) { border-left: 0 !important; border-top: 1px solid var(--border); }
  .stats > :deep(.stat:nth-child(2n)) { border-left: 1px solid var(--border) !important; }
  .stats > :deep(.stat:nth-child(-n + 2)) { border-top: 0; }
}
</style>
