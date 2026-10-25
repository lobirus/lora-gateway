<script setup lang="ts">
// Locale-proof number field: accepts "0,7" and "0.7", always emits a real number (never a string / NaN).
import { ref, watch } from 'vue'
import { parseNum } from '../../playground'

const props = defineProps<{ modelValue: number; min?: number; max?: number; integer?: boolean; step?: number }>()
const emit = defineEmits<{ 'update:modelValue': [v: number]; edited: [] }>()
const fmt = (v: number) => (Number.isFinite(v) ? String(v) : '')
const text = ref(fmt(props.modelValue))
const invalid = ref(false)
watch(() => props.modelValue, (v) => { if (parseNum(text.value) !== v) { text.value = fmt(v); invalid.value = false } })

function commit(v: number) {
  if (v !== props.modelValue) { emit('update:modelValue', v); emit('edited') }
}
function onInput(e: Event) {
  text.value = (e.target as HTMLInputElement).value
  const v = parseNum(text.value, props)
  invalid.value = v === null
  if (v !== null) commit(v)
}
function onBlur() { text.value = fmt(props.modelValue); invalid.value = false }
function bump(dir: 1 | -1) {
  const step = props.step ?? (props.integer ? 1 : 0.1)
  const v = parseNum(Math.round(((props.modelValue || 0) + dir * step) * 1e6) / 1e6, props)
  if (v !== null) { commit(v); text.value = fmt(v) }
}
</script>

<template>
  <input :value="text" type="text" inputmode="decimal" autocomplete="off" spellcheck="false" class="input num" :class="{ invalid }"
    :title="invalid ? 'Enter a number (0.7 or 0,7)' : undefined" @input="onInput" @blur="onBlur"
    @keydown.up.prevent="bump(1)" @keydown.down.prevent="bump(-1)" />
</template>

<style scoped>
.invalid { border-color: var(--danger) !important; box-shadow: 0 0 0 1px var(--danger) !important; }
</style>
