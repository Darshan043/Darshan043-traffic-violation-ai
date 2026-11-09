import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import DataTable from './DataTable.jsx'

const columns = [{ key: 'name', label: 'Name' }]

describe('DataTable states', () => {
  it('shows loading feedback', () => {
    render(<DataTable columns={columns} loading />)
    expect(screen.getByRole('status')).toHaveTextContent('Loading table')
  })

  it('shows an empty state when there are no rows', () => {
    render(<DataTable columns={columns} rows={[]} emptyTitle="No cameras" />)
    expect(screen.getByText('No cameras')).toBeInTheDocument()
  })

  it('shows an error and offers a retry action', () => {
    const onRetry = vi.fn()
    render(<DataTable columns={columns} error={new Error('Request unavailable')} onRetry={onRetry} />)
    expect(screen.getByText('Request unavailable')).toBeInTheDocument()
    screen.getByRole('button', { name: 'Retry' }).click()
    expect(onRetry).toHaveBeenCalledOnce()
  })
})
