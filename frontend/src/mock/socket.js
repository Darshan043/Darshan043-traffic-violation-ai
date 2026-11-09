import { mockViolations } from './data.js'

export function connectMockSocket(onMessage, onStatus = () => {}) {
  let closed = false
  let timeoutId
  onStatus(true)

  const scheduleNext = () => {
    const delay = 6000 + Math.floor(Math.random() * 4001)
    timeoutId = window.setTimeout(() => {
      if (closed) return
      const violation = {
        ...mockViolations[Math.floor(Math.random() * mockViolations.length)],
        event_id: `evt-live-${Date.now()}`,
        created_at: new Date().toISOString(),
      }
      onMessage({ type: 'violation', event: violation })
      scheduleNext()
    }, delay)
  }
  scheduleNext()

  return {
    close() {
      closed = true
      window.clearTimeout(timeoutId)
      onStatus(false)
    },
  }
}
