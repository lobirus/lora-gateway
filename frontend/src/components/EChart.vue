<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { theme } from '../stores/theme'
import { chartThemeName } from '../chartTheme'

const props = defineProps<{ option: echarts.EChartsOption; height?: string }>()
const el = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null
let ro: ResizeObserver | null = null

function render() {
  if (!el.value) return
  chart?.dispose()
  chart = echarts.init(el.value, chartThemeName(theme.value), { renderer: 'canvas' })
  chart.setOption({ backgroundColor: 'transparent', ...props.option }, true)
}
onMounted(() => {
  // fonts load async; re-render once they are ready so canvas text uses Geist
  render()
  document.fonts?.ready.then(() => chart && render())
  ro = new ResizeObserver(() => chart?.resize())
  if (el.value) ro.observe(el.value)
})
watch(() => props.option, () => chart?.setOption({ backgroundColor: 'transparent', ...props.option }, true), { deep: true })
watch(theme, render)
onBeforeUnmount(() => { ro?.disconnect(); chart?.dispose() })
</script>

<template>
  <div ref="el" :style="{ height: height || '280px', width: '100%' }" />
</template>
