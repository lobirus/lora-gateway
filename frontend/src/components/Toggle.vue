<script setup lang="ts">
defineProps<{ modelValue: boolean; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [v: boolean] }>()
</script>

<template>
  <button type="button" class="toggle" :class="{ on: modelValue }" :disabled="disabled" role="switch" :aria-checked="modelValue" @click="emit('update:modelValue', !modelValue)">
    <span class="knob" />
  </button>
</template>

<style scoped>
.toggle { width: 30px; height: 17px; border-radius: 999px; border: 1px solid var(--border-strong); background: var(--bg-subtle); position: relative; cursor: pointer; transition: background-color .12s var(--ease), border-color .12s var(--ease); flex-shrink: 0; padding: 0; }
.toggle.on { background: var(--ink); border-color: var(--ink); }
.toggle:disabled { opacity: .5; cursor: not-allowed; }
.knob { position: absolute; top: 2px; left: 2px; width: 11px; height: 11px; border-radius: 50%; background: var(--text-3); transition: transform .14s var(--ease), background-color .12s; }
.on .knob { transform: translateX(13px); background: var(--on-ink); }
</style>
