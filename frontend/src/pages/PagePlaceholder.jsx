import { Construction } from 'lucide-react'

export default function PagePlaceholder({ title, description }) {
  return <section className="checkpoint-card"><span className="checkpoint-icon"><Construction size={21} /></span><div><span className="eyebrow">PART 4 SCREEN</span><h2>{title}</h2><p>{description}</p><span className="checkpoint-note">Navigation and role-aware layout are ready. This page’s data view will be added in Part 4.</span></div></section>
}
