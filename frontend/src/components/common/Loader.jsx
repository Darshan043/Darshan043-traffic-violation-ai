export default function Loader({ label = 'Loading' }) {
  return <div className="state-box" role="status"><span className="spinner" aria-hidden="true" />{label}…</div>
}
