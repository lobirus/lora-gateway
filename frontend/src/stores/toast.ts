import { reactive } from 'vue'

export interface Toast { id: number; kind: 'success' | 'error' | 'info'; title: string; message?: string }
export const toasts = reactive<Toast[]>([])
let seq = 1

export function toast(kind: Toast['kind'], title: string, message?: string, ms = 4200) {
  const id = seq++
  toasts.push({ id, kind, title, message })
  setTimeout(() => dismiss(id), kind === 'error' ? ms * 1.6 : ms)
}
export function dismiss(id: number) {
  const i = toasts.findIndex((t) => t.id === id)
  if (i >= 0) toasts.splice(i, 1)
}
export const ok = (t: string, m?: string) => toast('success', t, m)
export const fail = (t: string, e?: unknown) => toast('error', t, e instanceof Error ? e.message : (e as string | undefined))
