import { useEffect, useState } from 'react'
import { apiUrl, getToken } from '../api/client.js'
import { connectMockAlerts, isMockMode } from '../api/index.js'

const MAX_ALERTS = 50

function normalizeMessage(message) {
  if (!message?.event || !['violation', 'event_candidate'].includes(message.type)) return null
  const event = message.event
  return {
    ...event,
    event_id: event.event_id || `candidate-${event.camera_id || 'camera'}-${event.frame_idx ?? Date.now()}`,
    created_at: event.created_at || event.timestamp || new Date().toISOString(),
    detection_confidence: event.detection_confidence ?? event.confidence ?? null,
    ai_result: event.ai_result || event.decision || 'unclear',
    violation_type: event.violation_type || 'unknown',
    provisional: message.type === 'event_candidate' || Boolean(message.provisional),
  }
}

export function useAlertsSocket(token = getToken(), onAlert) {
  const [alerts, setAlerts] = useState([])
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    if (!token) return undefined
    let active = true
    let socket
    let reconnectTimer
    let retryDelay = 1000
    let mockConnection

    const onMessage = (raw) => {
      let message = raw
      if (typeof raw === 'string') {
        try { message = JSON.parse(raw) } catch { return }
      }
      const alert = normalizeMessage(message)
      if (!alert || !active) return
      setAlerts((current) => [alert, ...current.filter((item) => item.event_id !== alert.event_id)].slice(0, MAX_ALERTS))
      onAlert?.(alert)
    }

    if (isMockMode()) {
      mockConnection = connectMockAlerts(onMessage, (value) => { if (active) setConnected(value) })
    } else {
      const connect = () => {
        if (!active) return
        const url = new URL(apiUrl('/ws/alerts'))
        url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
        url.searchParams.set('token', token)
        socket = new WebSocket(url)
        socket.onopen = () => { if (active) { setConnected(true); retryDelay = 1000 } }
        socket.onmessage = (event) => onMessage(event.data)
        socket.onerror = () => socket?.close()
        socket.onclose = () => {
          if (!active) return
          setConnected(false)
          reconnectTimer = window.setTimeout(connect, retryDelay)
          retryDelay = Math.min(retryDelay * 2, 30000)
        }
      }
      connect()
    }

    return () => {
      active = false
      window.clearTimeout(reconnectTimer)
      mockConnection?.close()
      if (socket && socket.readyState < WebSocket.CLOSING) socket.close()
    }
  }, [token, onAlert])

  return { alerts, connected: Boolean(token) && connected }
}
