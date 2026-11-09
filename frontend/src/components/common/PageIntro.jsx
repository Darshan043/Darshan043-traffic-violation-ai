export default function PageIntro({ eyebrow = 'TRAFFIC OPERATIONS', title, description, action }) {
  return <div className="page-intro"><div><span className="eyebrow">{eyebrow}</span><h2>{title}</h2>{description && <p>{description}</p>}</div>{action}</div>
}
