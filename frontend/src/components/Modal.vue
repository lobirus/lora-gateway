<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { X } from 'lucide-vue-next'

defineProps<{ title: string; subtitle?: string; width?: string }>()
const emit = defineEmits<{ close: [] }>()
const box = ref<HTMLElement>()
const titleId = 'm-' + Math.random().toString(36).slice(2, 8)
let opener: HTMLElement | null = null
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
const focusables = () => [...(box.value?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])].filter((el) => el.offsetParent !== null || el === document.activeElement)

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') { e.preventDefault(); emit('close'); return }
  if (e.key !== 'Tab') return
  const els = focusables()
  if (!els.length) { e.preventDefault(); return }
  const first = els[0], last = els[els.length - 1]
  const inside = box.value?.contains(document.activeElement)
  if (e.shiftKey && (document.activeElement === first || !inside)) { e.preventDefault(); last.focus() }
  else if (!e.shiftKey && (document.activeElement === last || !inside)) { e.preventDefault(); first.focus() }
}
onMounted(() => {
  opener = document.activeElement as HTMLElement | null
  document.addEventListener('keydown', onKey)
  nextTick(() => {
    // first form field if there is one, otherwise the first control after the close button, otherwise the dialog itself
    const field = box.value?.querySelector<HTMLElement>('.content input:not([type="hidden"]):not([disabled]):not([type="checkbox"]), .content select:not([disabled]), .content textarea:not([disabled])')
    const els = focusables()
    ;(field || els.find((el) => !el.classList.contains('x-close')) || box.value)?.focus()
  })
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKey)
  if (opener && document.contains(opener)) opener.focus()
})
</script>

<template>
  <Teleport to="body">
    <div class="overlay" @mousedown.self="emit('close')">
      <div ref="box" class="modal" :style="{ maxWidth: width || '560px' }" role="dialog" aria-modal="true" :aria-labelledby="titleId" tabindex="-1">
        <div class="head">
          <div>
            <h3 :id="titleId">{{ title }}</h3>
            <p v-if="subtitle">{{ subtitle }}</p>
          </div>
          <button class="btn btn-ghost btn-icon btn-sm x-close" @click="emit('close')" aria-label="Close dialog"><X /></button>
        </div>
        <div class="content"><slot /></div>
        <div v-if="$slots.footer" class="foot"><slot name="footer" /></div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.overlay { position: fixed; inset: 0; background: var(--overlay); display: grid; place-items: center; z-index: 80; padding: 20px; animation: fade .12s ease; }
.modal { width: 100%; background: var(--bg-elev); border: 1px solid var(--border-strong); border-radius: var(--radius); box-shadow: var(--shadow-lg); max-height: calc(100vh - 40px); display: flex; flex-direction: column; animation: pop .14s var(--ease); }
.head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; padding: 16px 18px 14px; border-bottom: 1px solid var(--border); }
.head h3 { font-size: 15px; font-weight: 600; line-height: 1.3; }
.head p { margin: 3px 0 0; color: var(--text-3); font-size: 12.5px; }
.modal:focus { outline: none; }
.content { padding: 18px; overflow-y: auto; }
.foot { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 18px; border-top: 1px solid var(--border); background: var(--bg); border-radius: 0 0 var(--radius) var(--radius); }
@keyframes fade { from { opacity: 0; } }
@keyframes pop { from { opacity: 0; transform: translateY(4px); } }
</style>
