import { useEffect } from 'react'
import { X } from 'lucide-react'

export default function Modal({ title, open, onClose, children, drawer = false }) {
  useEffect(() => {
    if (!open) return undefined
    const handleKey = (event) => { if (event.key === 'Escape') onClose?.() }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [open, onClose])
  if (!open) return null
  return <div className={`modal-backdrop${drawer ? ' drawer-backdrop' : ''}`} onMouseDown={(event) => { if (event.target === event.currentTarget) onClose?.() }}><section className={`modal-panel${drawer ? ' drawer-panel' : ''}`} role="dialog" aria-modal="true" aria-label={title}><header className="modal-header"><h2>{title}</h2><button className="icon-button" type="button" onClick={onClose} aria-label="Close"><X size={18} /></button></header><div className="modal-content">{children}</div></section></div>
}
