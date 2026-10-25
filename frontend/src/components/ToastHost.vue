<script setup lang="ts">
import { CheckCircle2, XCircle, Info, X } from 'lucide-vue-next'
import { toasts, dismiss } from '../stores/toast'
</script>

<template>
  <div class="toasts">
    <TransitionGroup name="toast">
      <div v-for="t in toasts" :key="t.id" class="toast" :class="t.kind">
        <CheckCircle2 v-if="t.kind === 'success'" class="ic" />
        <XCircle v-else-if="t.kind === 'error'" class="ic" />
        <Info v-else class="ic" />
        <div class="body">
          <div class="title">{{ t.title }}</div>
          <div v-if="t.message" class="msg">{{ t.message }}</div>
        </div>
        <button class="x" @click="dismiss(t.id)" aria-label="Dismiss"><X :size="14" /></button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toasts { position: fixed; right: 20px; bottom: 20px; z-index: 100; display: flex; flex-direction: column; gap: 8px; width: min(360px, calc(100vw - 40px)); }
.toast { display: flex; gap: 10px; align-items: flex-start; padding: 11px 12px 11px 14px; background: var(--bg-elev); border: 1px solid var(--border-strong); border-left: 2px solid var(--text-3); border-radius: var(--radius-sm); box-shadow: var(--shadow-lg); }
.toast.success { border-left-color: var(--success); }
.toast.error { border-left-color: var(--danger); }
.toast.info { border-left-color: var(--primary); }
.ic { width: 16px; height: 16px; flex-shrink: 0; margin-top: 2px; stroke-width: 1.75; }
.success .ic { color: var(--success); }
.error .ic { color: var(--danger); }
.info .ic { color: var(--primary); }
.body { flex: 1; min-width: 0; }
.title { font-weight: 600; font-size: 13px; }
.msg { color: var(--text-2); font-size: 12.5px; margin-top: 2px; word-break: break-word; }
.x { border: 0; background: none; color: var(--text-3); cursor: pointer; padding: 2px; border-radius: 3px; }
.x:hover { color: var(--text); }
.toast-enter-active, .toast-leave-active { transition: opacity .16s var(--ease), transform .16s var(--ease); }
.toast-enter-from { opacity: 0; transform: translateY(6px); }
.toast-leave-to { opacity: 0; }
</style>
