export const fmtInt = (n: number | null | undefined) => (n == null ? '—' : Math.round(n).toLocaleString('en-US'))
export function fmtCompact(n: number | null | undefined): string {
  if (n == null) return '—'
  return Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(n)
}
export function fmtCost(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n === 0) return '$0.00'
  if (Math.abs(n) < 0.01) return '$' + n.toFixed(5)
  if (Math.abs(n) < 1) return '$' + n.toFixed(4)
  return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
export function fmtMs(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n >= 10000) return (n / 1000).toFixed(1) + ' s'
  if (n >= 1000) return (n / 1000).toFixed(2) + ' s'
  return Math.round(n) + ' ms'
}
export const fmtPct = (n: number | null | undefined, d = 1) => (n == null ? '—' : (n * 100).toFixed(d) + '%')
export function fmtPrice(n: number | null | undefined): string {
  if (n == null) return '—'
  return '$' + (n < 1 ? n.toFixed(3).replace(/0$/, '') : n.toFixed(2))
}
export function fmtDate(s: string | null | undefined, withTime = true): string {
  if (!s) return '—'
  const d = new Date(s)
  return withTime ? d.toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
}
export function timeAgo(s: string | null | undefined): string {
  if (!s) return 'never'
  const diff = (Date.now() - new Date(s).getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return Math.floor(diff / 60) + 'm ago'
  if (diff < 86400) return Math.floor(diff / 3600) + 'h ago'
  return Math.floor(diff / 86400) + 'd ago'
}
export function fmtCtx(n: number | null | undefined): string {
  if (!n) return '—'
  if (n >= 1_000_000) return (n / 1_048_576 >= 0.99 ? Math.round(n / 1_048_576) : (n / 1e6).toFixed(1)) + 'M'
  return Math.round(n / 1024) + 'K'
}
export function delta(cur: number | null | undefined, prev: number | null | undefined): number | null {
  if (cur == null || prev == null || prev === 0) return null
  return (cur - prev) / prev
}
