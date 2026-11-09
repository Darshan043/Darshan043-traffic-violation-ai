import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import { CheckCircle2, Info, X, XCircle } from 'lucide-react'

const ToastContext = createContext(null)
const toastIcons = { success: CheckCircle2, error: XCircle, info: Info }

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const removeToast = useCallback((id) => setToasts((items) => items.filter((item) => item.id !== id)), [])
  const toast = useCallback((message, kind = 'info') => {
    const id = crypto.randomUUID()
    setToasts((items) => [...items, { id, message, kind }])
    window.setTimeout(() => removeToast(id), 4500)
  }, [removeToast])
  const value = useMemo(() => ({ toast }), [toast])
  return <ToastContext.Provider value={value}>{children}<div className="toast-stack" aria-live="polite" aria-atomic="false">{toasts.map((item) => { const Icon = toastIcons[item.kind] || Info; return <div className={`toast toast-${item.kind}`} key={item.id} role={item.kind === 'error' ? 'alert' : 'status'}><Icon size={18} /><span>{item.message}</span><button type="button" aria-label="Dismiss notification" onClick={() => removeToast(item.id)}><X size={16} /></button></div> })}</div></ToastContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useToast() {
  const context = useContext(ToastContext)
  if (!context) throw new Error('useToast must be used inside ToastProvider')
  return context.toast
}
