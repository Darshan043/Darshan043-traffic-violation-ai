export default function StatCard({ label, value, hint, icon: Icon }) {
  return <article className="stat-card"><div className="stat-card-top"><span>{label}</span>{Icon && <Icon size={18} aria-hidden="true" />}</div><strong>{value ?? '—'}</strong>{hint && <span className="stat-hint">{hint}</span>}</article>
}
