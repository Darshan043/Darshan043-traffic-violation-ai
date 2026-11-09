export function formatDate(value, options = {}) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short', ...options }).format(date)
}

export function formatPercent(value) {
  if (value === null || value === undefined || value === '') return '-'
  const number = Number(value)
  return Number.isFinite(number) ? `${number.toFixed(1)}%` : '-'
}

export function displayValue(value) {
  return value === null || value === undefined || value === '' ? '-' : value
}
