<script setup lang="ts">
defineProps<{ size?: number }>()
</script>

<template>
  <svg class="moon" :width="size || 20" :height="size || 20" viewBox="0 0 32 32" aria-hidden="true">
    <path d="M14.16 5.16A11 11 0 1 0 26.84 17.84A9 9 0 0 1 14.16 5.16Z" fill="currentColor" />
  </svg>
</template>

<style scoped>
.moon { color: var(--text); flex-shrink: 0; display: block; }
</style>
