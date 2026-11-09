import { useCallback, useState } from 'react'
import { getViolation, reviewViolation } from '../api/index.js'
import { useAuth } from '../context/AuthContext.jsx'
import { can } from '../context/permissions.js'
import { useToast } from '../context/ToastContext.jsx'
import { useApiData } from '../hooks/useApiData.js'
import { formatDate, formatPercent } from '../utils/format.js'
import Badge from '../components/common/Badge.jsx'
import EmptyState from '../components/common/EmptyState.jsx'
import ErrorBox from '../components/common/ErrorBox.jsx'
import EvidenceImage from '../components/common/EvidenceImage.jsx'
import Loader from '../components/common/Loader.jsx'
import Modal from '../components/common/Modal.jsx'

function DetailBody({ selected, onReviewed }) {
  const loader = useCallback(() => getViolation(selected.event_id), [selected.event_id])
  const detail = useApiData(loader)
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [reviewError, setReviewError] = useState(null)
  const { user } = useAuth()
  const toast = useToast()
  const item = detail.data || selected
  const canReview = can(user?.role, 'review')

  const submitReview = async (finalDecision) => {
    setSaving(true)
    setReviewError(null)
    try {
      const updated = await reviewViolation(item.event_id, { final_decision: finalDecision, review_note: note })
      onReviewed(updated)
      toast('Review saved. The original AI result was kept unchanged.', 'success')
      setNote('')
      detail.reload()
    } catch (error) { setReviewError(error) }
    finally { setSaving(false) }
  }

  return <div className="violation-detail">
    {detail.loading && !detail.data ? <Loader label="Loading violation details" /> : detail.error ? <ErrorBox error={detail.error} onRetry={detail.reload} /> : !item ? <EmptyState title="No violation selected" /> : <>
      <div className="detail-heading"><div><span className="eyebrow">EVENT ID</span><h3>{item.event_id}</h3></div><Badge value={item.ai_result === 'unclear' ? 'NEEDS_REVIEW' : item.violation_type === 'helmet' ? 'NO_HELMET' : 'NO_SEATBELT'} /></div>
      <div className="detail-evidence-grid"><figure><EvidenceImage path={item.evidence?.composite || item.evidence?.full_frame} alt={`Full evidence for ${item.event_id}`} className="evidence-large" /><figcaption>Full evidence · original AI result</figcaption></figure><figure><EvidenceImage path={item.evidence?.driver_rider_crop} alt="Driver or rider crop" className="evidence-crop" /><figcaption>Driver / rider crop</figcaption></figure></div>
      <section className="detail-section"><h4>Detection details</h4><dl className="detail-grid"><div><dt>Track ID</dt><dd>{item.track_id}</dd></div><div><dt>Camera</dt><dd>{item.camera_id}</dd></div><div><dt>Event time</dt><dd>{formatDate(item.created_at)}</dd></div><div><dt>Confidence</dt><dd>{formatPercent(item.detection_confidence * 100)}</dd></div><div><dt>Reason code</dt><dd><code>{item.reason_code || '—'}</code></dd></div><div><dt>Review status</dt><dd><Badge value={item.review_status} /></dd></div><div className="ai-result-row"><dt>Original AI result</dt><dd><strong>{item.ai_result}</strong> <span>(never changed by human review)</span></dd></div></dl></section>
      <section className="detail-section"><h4>Review history</h4>{selected.review_history?.length ? <ol className="review-history">{selected.review_history.map((entry, index) => <li key={`${entry.reviewed_at}-${index}`}><strong>{entry.reviewed_by || 'Reviewer'}</strong><time>{formatDate(entry.reviewed_at)}</time><span>{entry.final_decision || 'Review saved'}{entry.review_note ? ` · ${entry.review_note}` : ''}</span></li>)}</ol> : <EmptyState title="No review history" description="No reviewer action has been recorded." />}</section>
      {canReview && <section className="detail-section review-panel"><h4>Review this event</h4><label className="form-label" htmlFor="review-note">Reviewer note</label><textarea id="review-note" className="field-input" rows="3" maxLength="1000" value={note} onChange={(event) => setNote(event.target.value)} placeholder="Add a short note (optional)" />{reviewError && <ErrorBox error={reviewError} /> }<div className="button-row"><button type="button" className="button button-primary" disabled={saving} onClick={() => submitReview('CONFIRMED_VIOLATION')}>Confirm violation</button><button type="button" className="button button-secondary" disabled={saving} onClick={() => submitReview('NOT_A_VIOLATION')}>Reject</button></div></section>}
    </>}
  </div>
}

export default function ViolationDetailDrawer({ selected, onClose, onReviewed }) {
  return <Modal title="Violation details" open={Boolean(selected)} onClose={onClose} drawer>{selected && <DetailBody key={selected.event_id} selected={selected} onReviewed={onReviewed} />}</Modal>
}
