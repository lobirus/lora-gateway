import { reactive } from 'vue'
import { router } from '../router'

interface User { id: number; username: string; is_admin: boolean }

const saved = (() => {
  try { return JSON.parse(localStorage.getItem('gw-auth') || 'null') } catch { return null }
})() as { token: string; user: User; expires_at: number } | null

export const auth = reactive({
  token: saved && saved.expires_at * 1000 > Date.now() ? saved.token : '',
  user: (saved?.user ?? null) as User | null,
  expiresAt: saved?.expires_at ?? 0,
})

export function setSession(token: string, user: User, expires_at: number) {
  auth.token = token
  auth.user = user
  auth.expiresAt = expires_at
  localStorage.setItem('gw-auth', JSON.stringify({ token, user, expires_at }))
}

export function logout(expired = false) {
  auth.token = ''
  auth.user = null
  localStorage.removeItem('gw-auth')
  const cur = router.currentRoute.value
  if (cur.name !== 'login') router.push({ name: 'login', query: expired ? { expired: '1', next: cur.fullPath } : {} })
}

export const isAuthed = () => !!auth.token && auth.expiresAt * 1000 > Date.now()
