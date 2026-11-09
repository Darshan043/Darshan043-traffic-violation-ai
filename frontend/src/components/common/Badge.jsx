const variants = {
  NO_HELMET: ['danger', 'No helmet'], NO_SEATBELT: ['danger', 'No seatbelt'],
  violation: ['danger', 'Violation'], VIOLATION: ['danger', 'Violation'],
  NEEDS_REVIEW: ['warning', 'Needs review'], unclear: ['warning', 'Needs review'], pending: ['warning', 'Pending review'],
  HELMET: ['success', 'Helmet compliant'], SEATBELT: ['success', 'Seatbelt compliant'], COMPLIANCE: ['success', 'Compliant'],
  confirmed: ['success', 'Confirmed'], rejected: ['info', 'Rejected'], not_required: ['success', 'No review needed'],
  online: ['success', 'Online'], processing: ['info', 'Processing'], offline: ['neutral', 'Offline'], error: ['danger', 'Error'],
}

export default function Badge({ value, label, tone }) {
  const [variant, defaultLabel] = variants[value] || ['info', String(value || 'Unknown').replaceAll('_', ' ')]
  return <span className={`badge badge-${tone || variant}`}><span className="badge-dot" aria-hidden="true" />{label || defaultLabel}</span>
}
