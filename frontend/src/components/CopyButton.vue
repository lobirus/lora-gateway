<script setup lang="ts">
import { ref } from 'vue'
import { Copy, Check } from 'lucide-vue-next'
import { ok, fail } from '../stores/toast'

const props = defineProps<{ text: string | (() => Promise<string>); label?: string; dark?: boolean }>()
const done = ref(false)

async function copy() {
  try {
    const t = typeof props.text === 'function' ? await props.text() : props.text
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(t)
    else {
      const ta = document.createElement('textarea')
      ta.value = t
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      ta.remove()
    }
    done.value = true
    setTimeout(() => (done.value = false), 1600)
    if (props.label) ok('Copied to clipboard')
  } catch (e) {
    fail('Copy failed', e)
  }
}
</script>

<template>
  <button class="btn btn-sm" :class="[label ? '' : 'btn-icon', dark ? 'dark' : '']" @click="copy" :title="label || 'Copy'" :aria-label="label || 'Copy'">
    <Check v-if="done" /><Copy v-else />
    <span v-if="label">{{ done ? 'Copied' : label }}</span>
  </button>
</template>

<style scoped>
.dark { background: transparent; border-color: var(--code-border); color: var(--code-muted); }
.dark:hover:not(:disabled) { background: rgba(236, 230, 220, .06); color: var(--code-text); }
</style>
