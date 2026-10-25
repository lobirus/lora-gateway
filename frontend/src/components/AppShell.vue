<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { LayoutDashboard, Server, Boxes, KeyRound, ScrollText, Plug, Settings, Moon, Sun, LogOut, Menu, X, FlaskConical } from 'lucide-vue-next'
import { auth, logout } from '../stores/auth'
import { theme, toggleTheme } from '../stores/theme'
import { api } from '../api'
import BrandMark from './BrandMark.vue'

const route = useRoute()
const open = ref(false)
watch(() => route.fullPath, () => (open.value = false))

const nav = [
  { section: 'Monitor', items: [
    { to: '/', name: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { to: '/logs', name: 'logs', label: 'Request logs', icon: ScrollText },
  ] },
  { section: 'Configure', items: [
    { to: '/providers', name: 'providers', label: 'Providers', icon: Server },
    { to: '/models', name: 'models', label: 'Models & aliases', icon: Boxes },
    { to: '/keys', name: 'keys', label: 'API keys', icon: KeyRound },
  ] },
  { section: 'Integrate', items: [
    { to: '/playground', name: 'playground', label: 'Playground', icon: FlaskConical },
    { to: '/connect', name: 'connect', label: 'Connect', icon: Plug },
    { to: '/settings', name: 'settings', label: 'Settings', icon: Settings },
  ] },
]
const title = computed(() => (route.meta.title as string) || '')
const healthy = ref<boolean | null>(null)
onMounted(async () => {
  try { healthy.value = (await api.get<{ ok: boolean }>('/api/health')).ok } catch { healthy.value = false }
})
const mainEl = ref<HTMLElement>()
const skip = () => { const h = mainEl.value?.querySelector<HTMLElement>('h1'); mainEl.value?.focus(); h?.scrollIntoView({ block: 'start' }) }
const initials = computed(() => (auth.user?.username || '?').slice(0, 2).toUpperCase())
</script>

<template>
  <a href="#main" class="skip-link" @click.prevent="skip">Skip to content</a>
  <div class="shell" :class="{ open }">
    <aside class="sidebar">
      <div class="brand">
        <BrandMark :size="22" />
        <div>
          <div class="brand-name">Lora Gateway</div>
          <div class="brand-sub">Control plane</div>
        </div>
        <button class="btn btn-ghost btn-icon close" @click="open = false" aria-label="Close menu"><X /></button>
      </div>
      <nav aria-label="Main">
        <div v-for="g in nav" :key="g.section" class="nav-group">
          <div class="nav-section">{{ g.section }}</div>
          <RouterLink v-for="i in g.items" :key="i.to" :to="i.to" class="nav-item" :class="{ active: route.name === i.name }" :aria-current="route.name === i.name ? 'page' : undefined">
            <component :is="i.icon" class="nav-icon" />
            <span>{{ i.label }}</span>
          </RouterLink>
        </div>
      </nav>
      <div class="sidebar-foot">
        <div class="status">
          <span class="led" :class="healthy === null ? '' : healthy ? 'ok' : 'bad'" />
          <span>Gateway</span>
          <span class="spacer" />
          <span class="pill" :class="healthy === null ? '' : healthy ? 'ok' : 'bad'">{{ healthy === null ? 'checking' : healthy ? 'Operational' : 'Degraded' }}</span>
        </div>
      </div>
    </aside>
    <div class="backdrop" @click="open = false" />
    <div class="main">
      <header class="topbar">
        <button class="btn btn-ghost btn-icon burger" @click="open = true" aria-label="Open menu"><Menu /></button>
        <div class="crumb">{{ title }}</div>
        <div class="spacer" />
        <button class="btn btn-ghost btn-icon" @click="toggleTheme" :title="theme === 'dark' ? 'Light mode' : 'Dark mode'" :aria-label="theme === 'dark' ? 'Light mode' : 'Dark mode'">
          <Sun v-if="theme === 'dark'" /><Moon v-else />
        </button>
        <div class="user">
          <div class="avatar" aria-hidden="true">{{ initials }}</div>
          <div class="user-meta"><div class="u-name">{{ auth.user?.username }}</div><div class="u-role">Administrator</div></div>
        </div>
        <button class="btn btn-ghost btn-icon" title="Sign out" aria-label="Sign out" @click="logout()"><LogOut /></button>
      </header>
      <main id="main" ref="mainEl" tabindex="-1"><RouterView /></main>
    </div>
  </div>
</template>

<style scoped>
.shell { display: flex; min-height: 100%; }
.sidebar {
  width: var(--sidebar-w); flex-shrink: 0; background: var(--sidebar-bg); color: var(--sidebar-text); display: flex; flex-direction: column;
  position: fixed; inset: 0 auto 0 0; z-index: 40; transition: transform .2s var(--ease); border-right: 1px solid var(--border);
}
.brand { display: flex; align-items: center; gap: 10px; padding: 0 18px; height: 56px; border-bottom: 1px solid var(--border); }
.brand-name { color: var(--text); font-size: 14.5px; font-weight: 600; line-height: 1.1; letter-spacing: -.02em; }
.brand-sub { font-size: 11.5px; color: var(--text-3); margin-top: 2px; }
.close { display: none; margin-left: auto; }
nav { flex: 1; padding: 14px 10px; overflow-y: auto; }
.nav-group { margin-bottom: 18px; }
.nav-section { font-size: 11.5px; color: var(--text-3); padding: 0 10px 6px; font-weight: 500; }
.nav-item { position: relative; display: flex; align-items: center; gap: 10px; padding: 6px 10px; border-radius: var(--radius-sm); color: var(--sidebar-text); font-weight: 500; font-size: 13px; margin-bottom: 1px; transition: background-color .12s var(--ease), color .12s var(--ease); }
.nav-item:hover { background: var(--bg-hover); color: var(--sidebar-active); text-decoration: none; }
.nav-item.active, .nav-item.active:hover { background: var(--ink); color: var(--on-ink); }
.nav-item.active .nav-icon { color: var(--on-ink); opacity: 1; }
.nav-item.active::before { content: ''; position: absolute; left: -10px; top: 6px; bottom: 6px; width: 2px; border-radius: 1px; background: var(--accent); }
main:focus { outline: none; }
.nav-icon { width: 16px; height: 16px; opacity: .8; stroke-width: 1.75; }
.sidebar-foot { padding: 12px 18px 16px; border-top: 1px solid var(--border); }
.status { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-2); }
.led { width: 6px; height: 6px; border-radius: 50%; background: var(--text-3); }
.led.ok { background: var(--success); }
.led.bad { background: var(--danger); }
.pill { font-size: 11px; font-family: var(--font); color: var(--text-3); }
.pill.ok { color: var(--success); }
.pill.bad { color: var(--danger); }
.main { flex: 1; margin-left: var(--sidebar-w); min-width: 0; display: flex; flex-direction: column; }
.topbar { position: sticky; top: 0; z-index: 30; height: 56px; display: flex; align-items: center; gap: 6px; padding: 0 20px 0 36px; background: var(--bg); border-bottom: 1px solid var(--border); }
.crumb { font-size: 12.5px; color: var(--text-3); font-weight: 500; }
.burger { display: none; }
.user { display: flex; align-items: center; gap: 9px; padding: 0 10px 0 12px; margin-left: 6px; border-left: 1px solid var(--border); }
.avatar { width: 28px; height: 28px; border-radius: 50%; background: var(--bg-elev); border: 1px solid var(--border-strong); color: var(--text); display: grid; place-items: center; font: 500 11px var(--font); }
.u-name { font-weight: 500; font-size: 12.5px; line-height: 1.2; }
.u-role { font-size: 11px; color: var(--text-3); }
.backdrop { display: none; }
@media (max-width: 960px) {
  .sidebar { transform: translateX(-100%); }
  .shell.open .sidebar { transform: none; box-shadow: var(--shadow-lg); }
  .shell.open .backdrop { display: block; position: fixed; inset: 0; background: var(--overlay); z-index: 35; }
  .main { margin-left: 0; }
  .burger, .close { display: inline-flex; }
  .topbar { padding: 0 12px; }
  .user-meta { display: none; }
}
</style>
