export default function Pagination({ page, pages, onChange }) {
  if (pages <= 1) return null
  return <nav className="pagination" aria-label="Table pages"><button type="button" className="button button-secondary" disabled={page <= 1} onClick={() => onChange(page - 1)}>Previous</button><span>Page {page} of {pages}</span><button type="button" className="button button-secondary" disabled={page >= pages} onClick={() => onChange(page + 1)}>Next</button></nav>
}
