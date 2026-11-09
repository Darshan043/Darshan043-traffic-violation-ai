export default function Panel({ title, subtitle, action, children, className = '' }) {
  return <section className={`panel ${className}`}>{(title || subtitle || action) && <header className="panel-header"><div>{title && <h3>{title}</h3>}{subtitle && <p>{subtitle}</p>}</div>{action}</header>}{children}</section>
}
