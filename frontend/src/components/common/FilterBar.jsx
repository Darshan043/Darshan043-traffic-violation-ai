export default function FilterBar({ children, onReset }) {
  return <div className="filter-bar"><div className="filter-controls">{children}</div>{onReset && <button type="button" className="button button-quiet" onClick={onReset}>Clear filters</button>}</div>
}
