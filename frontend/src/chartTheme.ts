import * as echarts from 'echarts'

// ECharts theme for Lora Gateway. Mirrors the tokens in styles.css.
// Neutral greys carry the data; the green accent highlights one series at a time.
export interface ChartTokens {
  ink: string; accent: string; grey: string; light: string; danger: string
  text: string; axis: string; grid: string; surface: string; border: string
  palette: string[]
}

const light: ChartTokens = {
  ink: '#18181b', accent: '#16a34a', grey: '#71717a', light: '#d4d4d8', danger: '#dc2626',
  text: '#0a0a0a', axis: '#71717a', grid: '#f4f4f5', surface: '#ffffff', border: '#e4e4e7',
  palette: ['#18181b', '#16a34a', '#71717a', '#a1a1aa', '#52525b', '#d4d4d8', '#3f3f46'],
}
const dark: ChartTokens = {
  ink: '#fafafa', accent: '#22c55e', grey: '#a1a1aa', light: '#3f3f46', danger: '#f87171',
  text: '#fafafa', axis: '#a1a1aa', grid: '#18181b', surface: '#111111', border: '#3f3f46',
  palette: ['#fafafa', '#22c55e', '#a1a1aa', '#52525b', '#d4d4d8', '#3f3f46', '#71717a'],
}

export const chartTokens = (mode: string): ChartTokens => (mode === 'dark' ? dark : light)
export const chartThemeName = (mode: string) => (mode === 'dark' ? 'lora-dark' : 'lora-light')

const FONT = "'Geist Sans', ui-sans-serif, system-ui, sans-serif"

function build(t: ChartTokens) {
  const axis = {
    axisLine: { show: true, lineStyle: { color: t.border } },
    axisTick: { show: false },
    axisLabel: { color: t.axis, fontFamily: FONT, fontSize: 11 },
    splitLine: { show: true, lineStyle: { color: t.grid, width: 1 } },
    splitArea: { show: false },
  }
  return {
    color: t.palette,
    backgroundColor: 'transparent',
    textStyle: { fontFamily: FONT, color: t.text },
    title: { textStyle: { color: t.text, fontFamily: FONT } },
    legend: { textStyle: { color: t.axis, fontFamily: FONT, fontSize: 12 }, icon: 'rect', itemWidth: 10, itemHeight: 2, itemGap: 14 },
    tooltip: {
      backgroundColor: t.surface, borderColor: t.border, borderWidth: 1, padding: [6, 10],
      textStyle: { color: t.text, fontFamily: FONT, fontSize: 12 },
      extraCssText: 'box-shadow: none; border-radius: 6px;',
      axisPointer: { lineStyle: { color: t.border }, crossStyle: { color: t.border }, shadowStyle: { color: 'rgba(128,128,128,0.08)' } },
    },
    categoryAxis: { ...axis, splitLine: { show: false } },
    valueAxis: { ...axis, axisLine: { show: false } },
    line: { symbol: 'circle', symbolSize: 5, smooth: false, lineStyle: { width: 1.5 } },
    bar: { itemStyle: { borderRadius: 0 } },
    pie: { itemStyle: { borderColor: t.surface, borderWidth: 2 } },
  }
}
echarts.registerTheme('lora-light', build(light))
echarts.registerTheme('lora-dark', build(dark))
