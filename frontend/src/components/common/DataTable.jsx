import EmptyState from './EmptyState.jsx'
import ErrorBox from './ErrorBox.jsx'
import Loader from './Loader.jsx'

export default function DataTable({ columns = [], rows = [], rowKey = 'id', loading, error, onRetry, emptyTitle, emptyDescription, onRowClick }) {
  if (loading) return <Loader label="Loading table" />
  if (error) return <ErrorBox error={error} onRetry={onRetry} />
  if (!rows.length) return <EmptyState title={emptyTitle || 'No records found'} description={emptyDescription} />
  return <div className="table-scroll"><table className="data-table"><thead><tr>{columns.map((column) => <th key={column.key} scope="col">{column.label}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={row[rowKey] ?? index} onClick={onRowClick ? () => onRowClick(row) : undefined} tabIndex={onRowClick ? 0 : undefined} onKeyDown={onRowClick ? (event) => { if (event.key === 'Enter') onRowClick(row) } : undefined}>{columns.map((column) => <td key={column.key}>{column.render ? column.render(row[column.key], row) : (row[column.key] ?? '—')}</td>)}</tr>)}</tbody></table></div>
}
