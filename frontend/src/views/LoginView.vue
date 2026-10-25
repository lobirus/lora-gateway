<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Loader2, Lock, User, Moon, Sun } from 'lucide-vue-next'
import BrandMark from '../components/BrandMark.vue'
import { api } from '../api'
import { setSession } from '../stores/auth'
import { theme, toggleTheme } from '../stores/theme'

const route = useRoute()
const router = useRouter()
const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref(route.query.expired ? 'Your session expired. Please sign in again.' : '')

const userEl = ref<HTMLInputElement>()
onMounted(() => userEl.value?.focus())

async function submit() {
  error.value = ''
  loading.value = true
  try {
    const r = await api.post<{ access_token: string; expires_at: number; user: { id: number; username: string; is_admin: boolean } }>('/api/auth/login', { username: username.value, password: password.value })
    setSession(r.access_token, r.user, r.expires_at)
    router.replace((route.query.next as string) || '/')
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login">
    <section class="hero">
      <div class="brand"><BrandMark :size="22" /> Lora Gateway</div>
      <div class="pitch">
        <h1>One endpoint for every model.</h1>
        <p>Route OpenAI- and Anthropic-compatible traffic across providers, manage keys and budgets, and see cost and latency in real time.</p>
        <ul>
          <li><span class="n">01</span> Unified OpenAI &amp; Anthropic APIs</li>
          <li><span class="n">02</span> Virtual keys with budgets &amp; rate limits</li>
          <li><span class="n">03</span> Spend, token and latency analytics</li>
        </ul>
      </div>
      <div class="foot">Self-hosted · Powered by LiteLLM</div>
    </section>
    <section class="panel">
      <button class="btn btn-ghost btn-icon theme" type="button" @click="toggleTheme" :aria-label="theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'"><Sun v-if="theme === 'dark'" /><Moon v-else /></button>
      <form class="form" @submit.prevent="submit">
        <div class="m-brand"><BrandMark :size="20" /> Lora Gateway</div>
        <h2>Welcome back</h2>
        <p class="muted">Sign in to the gateway console</p>
        <div v-if="error" class="alert" role="alert">{{ error }}</div>
        <div class="field">
          <label for="u">Username</label>
          <div class="ifield"><User :size="16" /><input id="u" ref="userEl" v-model="username" class="input" autocomplete="username" autofocus required /></div>
        </div>
        <div class="field">
          <label for="p">Password</label>
          <div class="ifield"><Lock :size="16" /><input id="p" v-model="password" type="password" class="input" autocomplete="current-password" required /></div>
        </div>
        <button class="btn btn-primary submit" :disabled="loading">
          <Loader2 v-if="loading" class="spin" /> {{ loading ? 'Signing in…' : 'Sign in' }}
        </button>
      </form>
    </section>
  </div>
</template>

<style scoped>
/* the hero is a fixed ink panel in both themes */
.login { display: grid; grid-template-columns: 1.05fr 1fr; min-height: 100vh; }
.hero { --h-bg: #0a0a0a; --h-text: #fafafa; --h-muted: #a1a1aa; --h-line: #27272a;
  background: var(--h-bg); color: var(--h-text); padding: 36px 56px; display: flex; flex-direction: column; justify-content: space-between; border-right: 1px solid var(--h-line); }
.brand { display: flex; align-items: center; gap: 9px; font-size: 15px; font-weight: 600; letter-spacing: -.02em; color: var(--h-text); }
.brand :deep(.moon) { color: var(--h-text); }
.pitch { max-width: 500px; }
.pitch h1 { font-weight: 600; font-size: 44px; line-height: 1.05; letter-spacing: -.04em; color: var(--h-text); }
.pitch p { color: var(--h-muted); max-width: 440px; font-size: 15px; line-height: 1.6; margin: 18px 0 30px; }
.pitch ul { list-style: none; padding: 0; margin: 0; border-top: 1px solid var(--h-line); }
.pitch li { display: flex; align-items: baseline; gap: 14px; color: var(--h-text); padding: 11px 0; border-bottom: 1px solid var(--h-line); font-size: 13.5px; }
.pitch .n { font-size: 12px; color: var(--h-muted); font-variant-numeric: tabular-nums; }
.foot { color: var(--h-muted); font-size: 12px; }
.panel { display: grid; place-items: center; padding: 40px 24px; position: relative; background: var(--bg-elev); }
.theme { position: absolute; top: 18px; right: 18px; }
.form { width: 100%; max-width: 340px; }
.form h2 { font-size: 24px; font-weight: 600; letter-spacing: -.03em; line-height: 1.2; }
.form > .muted { margin: 4px 0 24px; }
.ifield { position: relative; }
.ifield svg { position: absolute; left: 11px; top: 50%; transform: translateY(-50%); pointer-events: none; color: var(--text-3); }
.ifield .input { padding-left: 34px; height: var(--h-lg); }
.submit { width: 100%; height: var(--h-lg); margin-top: 8px; font-size: 13.5px; }
.alert { background: var(--danger-soft); color: var(--danger); border-left: 2px solid var(--danger); padding: 9px 12px; border-radius: var(--radius-sm); font-size: 13px; margin-bottom: 14px; }
.m-brand { display: none; align-items: center; gap: 8px; font-weight: 600; letter-spacing: -.02em; margin-bottom: 28px; }
@media (max-width: 900px) { .login { grid-template-columns: 1fr; } .hero { display: none; } .m-brand { display: flex; } }
</style>
