import { ref, watch } from 'vue'

export type Theme = 'light' | 'dark'
export const theme = ref<Theme>((document.documentElement.dataset.theme as Theme) || 'light')
watch(theme, (t) => {
  document.documentElement.dataset.theme = t
  localStorage.setItem('gw-theme', t)
})
export const toggleTheme = () => (theme.value = theme.value === 'dark' ? 'light' : 'dark')
