export default function ErrorBox({ error, onRetry }) {
  return <div className="error-box" role="alert"><div><strong>We couldn’t load this data.</strong><p>{error?.message || 'Please try again.'}</p></div>{onRetry && <button className="button button-secondary" type="button" onClick={onRetry}>Retry</button>}</div>
}
