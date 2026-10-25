import { auth, logout } from './stores/auth'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`
  const res = await fetch(path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined })
  if (res.status === 401 && !path.startsWith('/api/auth/login')) {
    logout(true)
    throw new ApiError(401, 'Session expired, please sign in again')
  }
  const text = await res.text()
  let data: unknown = null
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!res.ok) {
    const d = data as { detail?: unknown } | null
    let msg = typeof d?.detail === 'string' ? d.detail : Array.isArray(d?.detail) ? (d!.detail as { msg: string }[]).map((x) => x.msg).join(', ') : `HTTP ${res.status}`
    if (!msg) msg = `HTTP ${res.status}`
    throw new ApiError(res.status, msg)
  }
  return data as T
}

export const api = {
  get: <T>(p: string) => request<T>('GET', p),
  post: <T>(p: string, b?: unknown) => request<T>('POST', p, b ?? {}),
  patch: <T>(p: string, b: unknown) => request<T>('PATCH', p, b),
  del: <T>(p: string) => request<T>('DELETE', p),
}

export function qs(params: Record<string, string | number | undefined | null>): string {
  const u = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') u.set(k, String(v))
  const s = u.toString()
  return s ? `?${s}` : ''
}
