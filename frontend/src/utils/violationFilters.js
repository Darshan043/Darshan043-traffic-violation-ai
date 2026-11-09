export const VIOLATION_FILTER_KEYS = ['type', 'result', 'camera', 'date_from', 'date_to', 'review_status', 'track_id', 'page', 'event_id']

export function readViolationFilters(search) {
  const params = search instanceof URLSearchParams ? search : new URLSearchParams(search)
  return Object.fromEntries(VIOLATION_FILTER_KEYS.map((key) => [key, params.get(key) || '']))
}

export function updateViolationFilter(searchParams, key, value, resetPage = true) {
  const next = new URLSearchParams(searchParams)
  if (value) next.set(key, value)
  else next.delete(key)
  if (resetPage && key !== 'page') next.delete('page')
  return next
}
