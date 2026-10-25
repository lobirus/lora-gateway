<script setup lang="ts">
import CopyButton from './CopyButton.vue'
defineProps<{ code: string; lang?: string; title?: string }>()
</script>

<template>
  <div class="code">
    <div class="bar">
      <span class="t">{{ title || lang }}</span>
      <CopyButton :text="code" dark />
    </div>
    <pre><code>{{ code }}</code></pre>
  </div>
</template>

<style scoped>
.code { color-scheme: dark; scrollbar-color: var(--code-border) transparent; background: var(--code-bg); border-radius: var(--radius); overflow: hidden; border: 1px solid var(--code-border); }
.bar { display: flex; justify-content: space-between; align-items: center; padding: 4px 6px 4px 14px; background: var(--code-bar); border-bottom: 1px solid var(--code-border); }
.t { font-size: 11px; color: var(--code-muted); font-family: var(--font-code); text-transform: lowercase; }
pre { margin: 0; padding: 14px 16px; color: var(--code-text); overflow-x: auto; line-height: 1.65; }
</style>
