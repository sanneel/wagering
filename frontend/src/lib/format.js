// Money can arrive as a JSON number or a Decimal-as-string from FastAPI.
export function money(value) {
  const n = typeof value === 'number' ? value : parseFloat(value)
  if (Number.isNaN(n)) return '$0.00'
  const sign = n < 0 ? '-' : ''
  return `${sign}$${Math.abs(n).toFixed(2)}`
}

// Signed money, e.g. "+$36.00" / "-$20.00".
export function signedMoney(value) {
  const n = typeof value === 'number' ? value : parseFloat(value)
  if (Number.isNaN(n)) return '$0.00'
  const sign = n >= 0 ? '+' : '-'
  return `${sign}$${Math.abs(n).toFixed(2)}`
}

export function formatDate(value) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

// Pull a human-readable message out of an axios error.
export function errMsg(error, fallback = 'Something went wrong.') {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length) {
    return detail.map((d) => d.msg || String(d)).join(', ')
  }
  if (error?.message) return error.message
  return fallback
}
