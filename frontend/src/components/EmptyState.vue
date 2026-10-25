<script setup lang="ts">
defineProps<{ title: string; description?: string; icon?: unknown }>()
</script>

<template>
  <div class="empty">
    <div class="ic"><component :is="icon" v-if="icon" :size="20" :stroke-width="1.5" /></div>
    <h4>{{ title }}</h4>
    <p v-if="description">{{ description }}</p>
    <div class="actions"><slot /></div>
  </div>
</template>

<style scoped>
.empty { text-align: center; padding: 44px 20px; }
.ic { margin: 0 auto 12px; color: var(--text-3); display: flex; justify-content: center; }
.ic:empty { display: none; }
h4 { font-weight: 600; font-size: 15px; letter-spacing: -.01em; }
p { color: var(--text-2); margin: 6px auto 0; max-width: 420px; font-size: 13px; }
.actions { margin-top: 18px; display: flex; gap: 8px; justify-content: center; }
.actions:empty { display: none; }
</style>
