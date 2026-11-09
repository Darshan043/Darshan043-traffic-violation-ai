import { useEffect, useState } from 'react'
import { getEvidence } from '../../api/index.js'

export default function EvidenceImage({ path, alt, className = '' }) {
  const [loaded, setLoaded] = useState({ path: '', src: '', error: false })
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    if (!path) return undefined
    let active = true
    let objectUrl
    getEvidence(path).then((blob) => {
      objectUrl = URL.createObjectURL(blob)
      if (active) setLoaded({ path, src: objectUrl, error: false })
      else URL.revokeObjectURL(objectUrl)
    }).catch(() => { if (active) setLoaded({ path, src: '', error: true }) })
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [path, retry])
  if (!path) return <div className={`evidence-fallback ${className}`} role="img" aria-label={alt || 'Evidence unavailable'}>No image</div>
  if (loaded.path !== path || (!loaded.src && !loaded.error)) return <div className={`evidence-fallback ${className}`} role="status">Loading image…</div>
  if (loaded.error) return <div className={`evidence-fallback ${className}`} role="alert"><span>{alt || 'Evidence image unavailable'}</span><button type="button" onClick={() => setRetry((value) => value + 1)}>Retry</button></div>
  return <img className={className} src={loaded.src} alt={alt || 'Violation evidence'} />
}
