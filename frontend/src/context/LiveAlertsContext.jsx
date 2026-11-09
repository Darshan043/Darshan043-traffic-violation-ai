import { createContext, useCallback, useContext, useMemo } from 'react'
import { useAlertsSocket } from '../hooks/useAlertsSocket.js'
import { useAuth } from './AuthContext.jsx'
import { useToast } from './ToastContext.jsx'

const LiveAlertsContext = createContext(null)

export function LiveAlertsProvider({ children }) {
  const { user } = useAuth()
  const toast = useToast()
  const onAlert = useCallback((alert) => {
    const label = alert.violation_type && alert.violation_type !== 'unknown' ? alert.violation_type : 'traffic event'
    toast(`New ${alert.provisional ? 'candidate' : 'alert'}: ${label}`, alert.provisional ? 'info' : 'error')
  }, [toast])
  const live = useAlertsSocket(user ? window.sessionStorage.getItem('traffic_access_token') : null, onAlert)
  const value = useMemo(() => live, [live])
  return <LiveAlertsContext.Provider value={value}>{children}</LiveAlertsContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useLiveAlerts() {
  const context = useContext(LiveAlertsContext)
  if (!context) throw new Error('useLiveAlerts must be used inside LiveAlertsProvider')
  return context
}
