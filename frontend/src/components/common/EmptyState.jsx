export default function EmptyState({ title = 'Nothing here yet', description = 'Data will appear here when it becomes available.' }) {
  return <div className="state-box empty-state"><span className="empty-mark" aria-hidden="true">—</span><strong>{title}</strong><span>{description}</span></div>
}
